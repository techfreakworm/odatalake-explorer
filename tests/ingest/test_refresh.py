"""refresh_once decisions with mocked HTTP and git (no network, fake embedder)."""

from __future__ import annotations

import pytest

import index.embed
import index.refresh as refresh
from index import sources
from index.build import latest_versions_card, publish
from index.chunk import sha256
from index.lock import load_state, save_state
from index.manifest import load_version, read_current
from ingest import config
from ingest.docs import SitemapResult, page_hash
from ingest.github import release_url


OLD, NEW = "a" * 40, "b" * 40
A, B = "https://olake.io/docs/connectors/alpha/", "https://olake.io/docs/connectors/beta/"
TAGS = {"v0.12.0": "1" * 40, "v0.12.1": "2" * 40}


def page(url: str, text: str) -> dict:
    md = f"# {url.rsplit('/', 2)[-2].title()}\n\n## Setup {{#setup}}\n\n{text}\n"
    return {"url": url, "lastmod": "2026-10-06", "source_type": "docs", "product": "go",
            "title": f"OLake {url.rsplit('/', 2)[-2]} connector", "breadcrumb": ["Sources"], "markdown": md,
            "ids": {"setup"}, "hash": page_hash(md)}


def repo_file(path: str, text: str, commit: str = OLD) -> dict:
    from ingest.github import prepare_text
    kind, text = prepare_text("olake", path, text)
    return {"repo": "olake", "path": path, "kind": kind, "text": text, "branch": "master", "commit": commit,
            "commit_date": "2026-10-15T18:47:35+05:30"}


def release(tag: str, date: str, body: str = "notes") -> dict:
    return {"repo": "olake", "tag": tag, "name": "", "url": release_url("olake", tag), "published_at": date,
            "prerelease": False, "body": body}


RELEASES = [release("v0.12.1", "2026-10-15T13:27:40Z", "Fixed MariaDB CDC."),
            release("v0.12.0", "2026-10-07T00:00:00Z", "Kafka upsert.")]
FILES = {
    "README.md": "# OLake\n\nOLake Go replicates databases to Iceberg.\n",
    "drivers/postgres/README.md": "# Postgres driver\n\nUses pgoutput for CDC.\n",
    "protocol/root.go": "package protocol\n\n// root command\nfunc Root() {\n\tx := 1\n}\n",
}


def sitemap_xml(*urls: str) -> str:
    locs = "".join(f"<url><loc>{u}</loc><lastmod>2026-10-06</lastmod></url>" for u in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'


@pytest.fixture
def seeded(isolated, monkeypatch):
    """A small index: two docs pages, three olake repo files, two releases and the latest-versions card."""
    monkeypatch.setattr(config, "REPOS", ("olake",))
    root = isolated / "index"
    pages = [page(A, "Alpha supports full refresh."), page(B, "Beta supports CDC.")]
    rels = sources.mark_latest("olake", RELEASES)
    files = [repo_file(p, t) for p, t in FILES.items()]
    card = latest_versions_card({"olake": rels}, [p["url"] for p in pages])
    chunks = [c for p in pages for c in sources.docs_chunks(p)]
    chunks += [c for r in rels for c in sources.release_gh_chunks(r)]
    chunks += [c for f in files for c in sources.repo_chunks(f)]
    chunks += sources.factcard_chunks(card)
    chunks = sources.sort_chunks(chunks)
    src = {"repo_files": {f"olake/{f['path']}": sha256(f["text"]) for f in files},
           "releases": {f"olake@{r['tag']}": sha256(sources.release_markdown(r)[1]) for r in rels},
           "faq": {}, "factcards": {card["name"]: card["hash"]}}
    docs = {"sitemap": config.SITEMAP_URL, "sitemap_etag": 'W/"old"', "lastmod_max": "2026-10-06",
            "pages": {p["url"]: {"lastmod": p["lastmod"], "hash": p["hash"]} for p in pages}}
    version, _, _ = publish(root, chunks, model="fake-model", docs=docs,
                            repos={"olake": {"branch": "master", "commit": OLD, "commit_date": "2026-10-15T18:47:35+05:30"}},
                            releases={"olake": {"tag": "v0.12.1", "published_at": "2026-10-15T13:27:40Z"}},
                            denylist_skipped=[], sources_info=src, build_info={"command": "test"})
    save_state({"sitemap_etag": 'W/"old"', "tags": {"olake": refresh.tag_fingerprint(TAGS)}})
    index.embed.Embedder.calls = []
    calls: dict[str, list] = {"fetch_docs": [], "compare": [], "fetch_file": [], "releases": []}

    monkeypatch.setattr(refresh, "fetch_sitemap", lambda etag=None, offline=False: SitemapResult(304, "", etag, None))
    monkeypatch.setattr(refresh, "fetch_faqs", lambda offline=False: ([], []))
    monkeypatch.setattr(refresh, "ls_remote_head", lambda repo: OLD)
    monkeypatch.setattr(refresh, "ls_remote_tags", lambda repo: dict(TAGS))

    def fake_releases(repo, max_age_s=900, offline=False, **kw):
        calls["releases"].append((repo, offline))
        return [dict(r) for r in RELEASES]
    monkeypatch.setattr(refresh, "fetch_releases", fake_releases)

    def no_clone(*a, **kw):
        raise AssertionError("refresh should not clone when the compare API works")
    monkeypatch.setattr(refresh, "clone_repo", no_clone)
    return {"root": root, "version": version, "pages": pages, "calls": calls, "monkeypatch": monkeypatch}


def docs_200(seeded, pages: list[dict], etag='W/"new"'):
    mp = seeded["monkeypatch"]
    urls = [p["url"] for p in pages]
    mp.setattr(refresh, "fetch_sitemap", lambda etag_=None, offline=False, **kw: SitemapResult(
        200, sitemap_xml(*urls), etag, "Sat, 17 Oct 2026 04:00:00 GMT"))
    by_url = {p["url"]: p for p in pages}

    def fake_fetch_docs(entries, offline=False):
        seeded["calls"]["fetch_docs"].append([e.url for e in entries])
        return [by_url[e.url] for e in entries], []
    mp.setattr(refresh, "fetch_docs", fake_fetch_docs)


def chunk_ids(root) -> list[str]:
    return [c["id"] for c in load_version(root)[1]]


# ----------------------------------------------------------------------------- docs
def test_sitemap_304_is_a_noop(seeded):
    mp = seeded["monkeypatch"]
    mp.setattr(refresh, "fetch_docs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch on 304")))
    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == []
    assert r["changed"] is False and r["version"] is None and r["written"] is False
    assert r["docs"]["sitemap_status"] == 304
    assert read_current(seeded["root"]) == seeded["version"]
    assert index.embed.Embedder.calls == [] and seeded["calls"]["releases"] == []


def test_one_changed_page_reembeds_only_its_chunks(seeded):
    before = {c["id"]: c for c in load_version(seeded["root"])[1]}
    alpha, _ = seeded["pages"]
    beta2 = page(B, "Beta supports CDC and incremental sync now.")
    docs_200(seeded, [alpha, beta2])
    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == [] and r["changed"] is True and r["written"] is True
    assert r["docs"]["changed"] == [B] and r["docs"]["added"] == [] and r["docs"]["removed"] == []
    assert read_current(seeded["root"]) == r["version"] != seeded["version"]
    manifest, chunks, matrix = load_version(seeded["root"])
    assert matrix.shape[0] == len(chunks)
    new_hashes = [c["hash"] for c in chunks if c["hash"] not in {b["hash"] for b in before.values()}]
    assert new_hashes and r["embedded"] == len(new_hashes)
    assert all("Beta supports CDC and incremental" in t or "beta" in t.lower() for t in index.embed.Embedder.calls)
    assert len(index.embed.Embedder.calls) == len(new_hashes)
    for c in chunks:  # alpha's chunks are byte-identical
        if c["doc_url"] == A:
            assert before[c["id"]] == c
    assert manifest["docs"]["pages"][B]["hash"] == beta2["hash"]
    assert manifest["docs"]["sitemap_etag"] == 'W/"new"'
    assert load_state()["sitemap_etag"] == 'W/"new"'


def test_sitemap_200_without_content_change_stores_the_etag_only(seeded):
    docs_200(seeded, seeded["pages"])
    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == [] and r["changed"] is False and r["version"] is None
    assert read_current(seeded["root"]) == seeded["version"]
    assert load_state()["sitemap_etag"] == 'W/"new"'  # next poll: a cheap 304 again
    assert index.embed.Embedder.calls == []


def test_removed_url_is_tombstoned(seeded):
    alpha, _ = seeded["pages"]
    docs_200(seeded, [alpha])
    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == [] and r["written"] is True and r["docs"]["removed"] == [B]
    manifest, chunks, _ = load_version(seeded["root"])
    assert not [c for c in chunks if c["doc_url"] == B]
    assert B not in manifest["docs"]["pages"] and A in manifest["docs"]["pages"]
    assert r["embedded"] == 0  # nothing new to embed


def test_check_mode_writes_nothing(seeded):
    alpha, _ = seeded["pages"]
    docs_200(seeded, [alpha, page(B, "Changed text for beta.")])
    r = refresh.refresh_once(seeded["root"], check=True)
    assert r["errors"] == [] and r["changed"] is True and r["written"] is False and r["version"] is None
    assert read_current(seeded["root"]) == seeded["version"]
    assert load_state()["sitemap_etag"] == 'W/"old"'
    assert index.embed.Embedder.calls == []


# ----------------------------------------------------------------------------- repos
def test_new_repo_sha_refetches_only_allowlisted_changed_files(seeded):
    mp, calls = seeded["monkeypatch"], seeded["calls"]
    mp.setattr(refresh, "ls_remote_head", lambda repo: NEW)
    changed = [
        {"filename": "README.md", "status": "modified", "previous_filename": None},
        {"filename": "drivers/postgres/README.md", "status": "modified", "previous_filename": None},
        {"filename": "drivers/mysql/README.md", "status": "added", "previous_filename": None},
        {"filename": "drivers/postgres/internal/config.go", "status": "modified", "previous_filename": None},
        {"filename": "go.mod", "status": "modified", "previous_filename": None},
        {"filename": ".github/workflows/ci.yml", "status": "modified", "previous_filename": None},
        {"filename": "drivers/postgres/internal/cdc_test.go", "status": "added", "previous_filename": None},
    ]

    def fake_compare(repo, old, new, **kw):
        calls["compare"].append((repo, old, new))
        return changed, "2026-10-17T01:00:00Z"
    new_text = {"README.md": "# OLake\n\nOLake Go now also writes Parquet.\n",
                "drivers/postgres/README.md": "# Postgres driver\n\nUses pgoutput; wal2json is deprecated.\n",
                "drivers/mysql/README.md": "# MySQL driver\n\nReads the binlog.\n"}

    def fake_fetch_file(repo, ref, path, **kw):
        calls["fetch_file"].append((repo, ref, path))
        return new_text[path]
    mp.setattr(refresh, "compare_files", fake_compare)
    mp.setattr(refresh, "fetch_file_at", fake_fetch_file)

    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == [] and r["written"] is True
    assert calls["compare"] == [("olake", OLD, NEW)]
    assert sorted(p for _, _, p in calls["fetch_file"]) == ["README.md", "drivers/mysql/README.md",
                                                            "drivers/postgres/README.md"]
    assert all(ref == NEW for _, ref, _ in calls["fetch_file"])
    assert r["repos"]["olake"]["method"] == "compare"
    manifest, chunks, _ = load_version(seeded["root"])
    assert manifest["repos"]["olake"] == {"branch": "master", "commit": NEW, "commit_date": "2026-10-17T01:00:00Z"}
    repo_chunks = [c for c in chunks if c["source_type"] == "repo"]
    assert repo_chunks and all(c["commit"] == NEW and f"/blob/{NEW}/" in c["url"] for c in repo_chunks)
    assert all("/blob/master/" in c["doc_url"] for c in repo_chunks)
    texts = " ".join(c["text"] for c in repo_chunks)
    assert "writes Parquet" in texts and "Reads the binlog" in texts and "func Root()" in texts
    # root.go was not in the change list: same text, same hash, nothing re-embedded for it
    assert not any("func Root" in t for t in index.embed.Embedder.calls)
    assert manifest["sources"]["repo_files"]["olake/drivers/mysql/README.md"] == sha256(
        repo_file("drivers/mysql/README.md", new_text["drivers/mysql/README.md"])["text"])


def test_head_moved_without_allowlisted_change_writes_no_version(seeded):
    mp, calls = seeded["monkeypatch"], seeded["calls"]
    mp.setattr(refresh, "ls_remote_head", lambda repo: NEW)

    def fake_compare(repo, old, new, **kw):
        calls["compare"].append(new)
        return [{"filename": "go.mod", "status": "modified", "previous_filename": None}], "2026-10-17T01:00:00Z"
    mp.setattr(refresh, "compare_files", fake_compare)
    mp.setattr(refresh, "fetch_file_at", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch")))
    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == [] and r["changed"] is False and read_current(seeded["root"]) == seeded["version"]
    assert load_state()["repos_checked"]["olake"] == NEW
    refresh.refresh_once(seeded["root"])
    assert calls["compare"] == [NEW]  # the second poll does not call the compare API again


# ----------------------------------------------------------------------------- releases
def test_new_release_tag_adds_release_notes_and_updates_latest(seeded):
    mp = seeded["monkeypatch"]
    tags = dict(TAGS, **{"v0.12.2": "3" * 40})
    mp.setattr(refresh, "ls_remote_tags", lambda repo: tags)
    rels = [release("v0.12.2", "2026-10-17T00:00:00Z", "New: Oracle CDC preview.")] + RELEASES
    mp.setattr(refresh, "fetch_releases", lambda repo, max_age_s=900, offline=False, **kw: [dict(r) for r in rels])
    r = refresh.refresh_once(seeded["root"])
    assert r["errors"] == [] and r["written"] is True
    assert set(r["releases"]["olake"]["changed"]) == {"v0.12.2", "v0.12.1"}  # v0.12.1 is no longer "latest"
    manifest, chunks, _ = load_version(seeded["root"])
    assert manifest["releases"]["olake"]["tag"] == "v0.12.2"
    ids = {c["id"].split("#")[0] for c in chunks}
    assert "release-gh/olake/v0.12.2" in ids
    card = [c for c in chunks if c["id"].startswith("factcard/latest-versions")]
    assert card and card[0]["doc_url"] == release_url("olake", "v0.12.2")
    assert load_state()["tags"]["olake"] == refresh.tag_fingerprint(tags)


def test_concurrent_call_reports_busy(seeded):
    assert refresh._LOCK.acquire(blocking=False)
    try:
        r = refresh.refresh_once(seeded["root"])
    finally:
        refresh._LOCK.release()
    assert r["skipped"] == "busy" and r["changed"] is False


def test_no_index_is_reported_not_raised(isolated):
    r = refresh.refresh_once(isolated / "empty-index")
    assert r["changed"] is False and r["errors"] and "index.build" in r["errors"][0]


def test_refresh_prunes_to_current_and_previous(seeded):
    from index.manifest import list_versions
    alpha, beta = seeded["pages"]
    docs_200(seeded, [alpha, page(B, "Beta: first change.")], etag='W/"v2"')
    r1 = refresh.refresh_once(seeded["root"])
    assert r1["written"] and r1["pruned"] == []
    docs_200(seeded, [alpha, page(B, "Beta: second change.")], etag='W/"v3"')
    r2 = refresh.refresh_once(seeded["root"])
    assert r2["written"] and r2["pruned"] == [seeded["version"]]
    assert list_versions(seeded["root"]) == [r1["version"], r2["version"]]
    assert read_current(seeded["root"]) == r2["version"]
