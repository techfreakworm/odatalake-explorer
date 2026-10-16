from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from index import sources
from index.build import latest_versions_card, validate
from index.chunk import FIELDS
from index.manifest import counts_of, list_versions, new_version, prune, read_current, swap_current, write_version
from ingest.faq import parse_faq

FAQ_HTML = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"SoftwareApplication",
"name":"OLake"}</script><script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage",
"mainEntity":[{"@type":"Question","name":"Is OLake Go open source?","acceptedAnswer":{"@type":"Answer",
"text":"Yes. <b>Apache 2.0</b> licensed."}},{"@type":"Question","name":"Enterprise plan?","acceptedAnswer":
{"@type":"Answer","text":"Reach out at hello@olake.io"}}]}</script></head><body></body></html>"""


# ----------------------------------------------------------------------------- faq
def test_faq_jsonld_one_record_per_question():
    qas = parse_faq(FAQ_HTML)
    assert qas == [{"question": "Is OLake Go open source?", "answer": "Yes. Apache 2.0 licensed."},
                   {"question": "Enterprise plan?", "answer": "Reach out at hello@olake.io"}]
    recs = [{"page_url": "https://olake.io/olake-go/", "label": "OLake Go product FAQ", "n": n, **qa}
            for n, qa in enumerate(qas)]
    chunks = [c for r in recs for c in sources.faq_chunks(r)]
    assert [c["id"] for c in chunks] == ["faq/olake-go/0#0", "faq/olake-go/1#0"]
    assert all(c["doc_url"] == "https://olake.io/olake-go/" and c["source_type"] == "faq" for c in chunks)
    assert "### Is OLake Go open source?" in chunks[0]["text"]


# ----------------------------------------------------------------------------- versions and CURRENT
def tiny_index(root, version, built_at="2026-10-17T04:12:00Z"):
    chunk = sources.make_chunk(id="docs/x#0", source_type="docs", product="go", doc_url="https://olake.io/docs/x/",
                               url="https://olake.io/docs/x/", title="X", section_path=["X"], text="X | OLake Go\n\nbody",
                               ord=0)
    write_version(root, version, [chunk], np.ones((1, 4), dtype=np.float32) / 2, {"version": version,
                                                                                    "built_at": built_at})


def test_version_names_and_collisions(tmp_path):
    now = datetime(2026, 10, 17, 4, 12, 33, tzinfo=timezone.utc)
    assert new_version(tmp_path, now) == "20261017T0412Z"
    tiny_index(tmp_path, "20261017T0412Z")
    assert new_version(tmp_path, now) == "20261017T0412Z-2"


def test_current_swap_is_atomic_and_validated(tmp_path):
    tiny_index(tmp_path, "20261017T0412Z")
    swap_current(tmp_path, "20261017T0412Z")
    assert (tmp_path / "CURRENT").read_text() == "20261017T0412Z\n"
    assert read_current(tmp_path) == "20261017T0412Z"
    assert not list(tmp_path.glob(".CURRENT*"))  # no temp file left behind
    with pytest.raises(FileNotFoundError):
        swap_current(tmp_path, "20991231T0000Z")
    assert read_current(tmp_path) == "20261017T0412Z"


def test_write_version_refuses_mismatched_rows(tmp_path):
    with pytest.raises(ValueError):
        write_version(tmp_path, "v", [{"id": "a"}], np.ones((2, 4), dtype=np.float32), {})


def test_prune_keeps_current_and_previous(tmp_path):
    for i, v in enumerate(["20261017T0100Z", "20261017T0200Z", "20261017T0300Z", "20261017T0400Z"]):
        tiny_index(tmp_path, v, built_at=f"2026-10-17T0{i + 1}:00:00Z")
    swap_current(tmp_path, "20261017T0300Z")
    removed = prune(tmp_path)
    assert sorted(removed) == ["20261017T0100Z", "20261017T0400Z"]
    assert list_versions(tmp_path) == ["20261017T0200Z", "20261017T0300Z"]


def test_counts_by_source_type():
    mk = lambda i, st, url: {"id": f"{st}/{i}#0", "source_type": st, "doc_url": url}  # noqa: E731
    counts = counts_of([mk(1, "docs", "a"), mk(2, "docs", "a"), mk(3, "release", "b"), mk(4, "factcard", "a"),
                        mk(5, "repo", "r")])
    assert counts["pages"] == 2 and counts["chunks"] == 5
    assert counts["by_source_type"]["docs"] == {"pages": 1, "chunks": 2}
    assert counts["by_source_type"]["factcard"] == {"pages": 1, "chunks": 1}


# ----------------------------------------------------------------------------- fact cards and issues
CARD = {
    "name": "demo", "title": "Demo card", "cite_urls": ["https://olake.io/docs/"], "hash": "x",
    "body": "# Demo\n<!-- cite: https://olake.io/docs/ -->\n\nIntro fact.\n\n"
            "## Oracle\n<!-- cite: https://olake.io/docs/connectors/oracle/ https://olake.io/docs/ -->\n\n"
            "- Oracle has no CDC.\n\n"
            "## MSSQL\n<!-- cite: https://olake.io/docs/connectors/mssql/ -->\n\n- MSSQL has CDC.\n",
}


def test_factcard_sections_carry_their_own_citations():
    chunks = sources.factcard_chunks(CARD)
    by = {c["section_path"][-1]: c for c in chunks}
    assert by["Oracle"]["cite_urls"] == ["https://olake.io/docs/connectors/oracle/", "https://olake.io/docs/"]
    assert by["Oracle"]["doc_url"] == "https://olake.io/docs/connectors/oracle/"
    assert by["MSSQL"]["cite_urls"] == ["https://olake.io/docs/connectors/mssql/"]
    assert all("<!--" not in c["text"] for c in chunks)
    assert all(c["source_type"] == "factcard" and c["tier"] == 1 for c in chunks)
    assert sources.card_cite_urls(CARD)[0] == "https://olake.io/docs/"


def test_real_factcards_load_and_cite_only_allowed_urls():
    cards = sources.load_factcards()
    names = {c["name"] for c in cards}
    assert {"source-sync-modes", "destinations-catalogs", "feature-minimum-versions",
            "unsupported-and-undocumented", "known-contradictions"} <= names
    for card in cards:
        for u in sources.card_cite_urls(card):
            assert u.startswith(("https://olake.io/docs/", "https://olake.io/olake-go/", "https://olake.io/olake-fusion/"))


def test_issue_chunk_wording():
    issue = {"url": "https://github.com/datazip-inc/olake/issues/867", "repo": "olake", "number": 867,
             "title": "Incremental jobs from Oracle to Iceberg do not pick up changes", "state": "closed",
             "updated_at": "2026-04-14T13:18:36Z", "body": "long body"}
    c = sources.issue_chunk(issue, {"fixed_in": "v0.6.0", "facts": "- Symptom: zero rows ingested.\n"})
    assert "Known issue #867 in datazip-inc/olake (closed; fixed in v0.6.0)" in c["text"]
    assert c["doc_url"] == issue["url"] and c["tier"] == 2 and tuple(c) == FIELDS
    open_issue = dict(issue, state="open")
    assert "(open):" in sources.issue_chunk(open_issue, {"fixed_in": None, "facts": "x"})["text"]


def test_curated_issue_notes_cover_every_curated_issue():
    from ingest import config
    notes = sources.load_issue_notes()
    assert set(notes) == set(config.CURATED_ISSUES)


def test_latest_release_flag_and_card():
    rels = [{"repo": "olake-helm", "tag": "v0.4.0", "url": "https://github.com/datazip-inc/olake-helm/releases/tag/v0.4.0",
             "published_at": "2026-10-08T12:18:32Z", "prerelease": False, "name": "", "body": "worker"},
            {"repo": "olake-helm", "tag": "olake-0.0.30", "published_at": "2026-10-08T12:00:00Z",
             "url": "https://github.com/datazip-inc/olake-helm/releases/tag/olake-0.0.30", "prerelease": False,
             "name": "", "body": "chart"},
            {"repo": "olake-helm", "tag": "v0.3.11", "published_at": "2026-09-10T00:00:00Z",
             "url": "https://github.com/datazip-inc/olake-helm/releases/tag/v0.3.11", "prerelease": False,
             "name": "", "body": "old"}]
    marked = sources.mark_latest("olake-helm", rels)
    assert [bool(r.get("latest")) for r in marked] == [True, True, False]
    assert "latest datazip-inc/olake-helm worker release" in sources.release_markdown(marked[0])[1]
    card = latest_versions_card({"olake-helm": marked}, ["https://olake.io/docs/release/ingestion/v0.9.0/",
                                                         "https://olake.io/docs/release/ingestion/v0.12.0/"])
    assert "worker v0.4.0 (2026-10-08) and Helm chart olake-0.0.30 (2026-10-08)" in card["body"]
    assert card["cite_urls"] == ["https://github.com/datazip-inc/olake-helm/releases/tag/v0.4.0",
                                 "https://olake.io/docs/release/ingestion/v0.12.0/"]
    assert "2026-10-17" not in card["body"]  # no build date: the card only changes with the data


# ----------------------------------------------------------------------------- validation
def test_validate_flags_contract_violations():
    good = sources.make_chunk(id="docs/a#0", source_type="docs", product="go", doc_url="https://olake.io/docs/a/",
                              url="https://olake.io/docs/a/#x", anchor="x", title="A", section_path=["A"],
                              text="A | OLake Go\n\nbody text", ord=0)
    assert validate([good], {"https://olake.io/docs/a/"}) == []
    bad = [
        dict(good, id="docs/a#1", product=None),
        dict(good, id="docs/a#2", doc_url="https://olake.io/docs/legacy/"),
        sources.make_chunk(id="docs/a#3", source_type="docs", product="go", doc_url="https://olake.io/docs/a/",
                           url="https://olake.io/docs/a/", title="A", section_path=[], text="A | OLake Go\n\n```json\n{",
                           ord=3),
        sources.make_chunk(id="r#0", source_type="repo", doc_url="https://raw.githubusercontent.com/datazip-inc/olake/x",
                           url="https://raw.githubusercontent.com/datazip-inc/olake/x", title="r", section_path=[],
                           text="r\n\nbody", ord=0),
        sources.make_chunk(id="docs/a#4", source_type="docs", product="go", doc_url="https://olake.io/docs/a/",
                           url="https://olake.io/docs/a/", title="A", section_path=[], text="A | OLake Go\n\n", ord=4),
        sources.make_chunk(id="docs/a#5", source_type="docs", product="go", doc_url="https://olake.io/docs/a/",
                           url="https://olake.io/docs/a/", title="A", section_path=[], ord=5,
                           text="A\n\n**Tab: UI**\n\nx\n\n**Tab: CLI**\n\ny"),
    ]
    problems = " | ".join(validate([good] + bad, {"https://olake.io/docs/a/"}))
    for needle in ("docs/a#1: product not set", "docs/a#2: doc_url", "docs/a#3: unbalanced code fence",
                   "r#0: raw.githubusercontent.com", "docs/a#4: empty chunk", "docs/a#5: spans two tab panels"):
        assert needle in problems
    assert "duplicate id" not in problems
    assert "duplicate id docs/a#0" in " ".join(validate([good, good], {"https://olake.io/docs/a/"}))


def test_manifest_has_no_absolute_paths(tmp_path):
    tiny_index(tmp_path, "20261017T0412Z")
    text = (tmp_path / "20261017T0412Z" / "manifest.json").read_text()
    assert str(Path.home()) not in text and str(tmp_path) not in text
    json.loads(text)
