from __future__ import annotations

import re

from index.chunk import (CHUNK_HARD_MAX, FIELDS, chunk_code, chunk_markdown, fences_balanced, ntok, parse_markdown,
                         render_header, tab_labels_in)
from index.sources import docs_chunks
from ingest.docs import page_hash
from ingest.html2md import extract_page

URL = "https://olake.io/docs/writers/example/"


def doc_page(fixture_text) -> dict:
    p = extract_page(fixture_text("docs_page.html"), URL)
    return {"url": URL, "lastmod": "2026-10-06", "source_type": "docs", "product": "go", "title": p["title"],
            "breadcrumb": p["breadcrumb"], "markdown": p["markdown"], "ids": p["ids"], "hash": page_hash(p["markdown"])}


def body(text: str) -> str:
    return text.split("\n\n", 1)[1]


def big_paragraph(n: int, word: str = "lorem") -> str:
    return " ".join(f"{word}{i}" for i in range(n))


# ----------------------------------------------------------------------------- header
def test_header_format():
    h = render_header("REST Catalog", "OLake Go", ["Destinations", "Catalogs"],
                      ["REST Catalog", "Tab: Nessie", "Configuration", "Tab: OLake UI"])
    assert h == "REST Catalog | OLake Go > Destinations > Catalogs > Configuration [Nessie > OLake UI]"
    assert render_header("T", None, [], []) == "T"


def test_every_docs_chunk_starts_with_the_context_header(fixture_text):
    chunks = docs_chunks(doc_page(fixture_text))
    assert chunks
    for c in chunks:
        first = c["text"].split("\n", 1)[0]
        assert first.startswith("OLake Example REST Catalog Setup | OLake Go > Destinations > Catalogs")
        assert c["text"].split("\n")[1] == ""  # header, blank line, Markdown body
        assert tuple(c) == FIELDS
        assert c["product"] == "go" and c["tier"] == 1 and c["doc_url"] == URL


# ----------------------------------------------------------------------------- tabs
def test_no_chunk_spans_two_tab_panels(fixture_text):
    for c in docs_chunks(doc_page(fixture_text)):
        assert len(tab_labels_in(c["text"])) <= 1


def test_tab_label_path_in_header(fixture_text):
    chunks = docs_chunks(doc_page(fixture_text))
    cli = next(c for c in chunks if "**Tab: OLake CLI**" in c["text"])
    assert cli["text"].split("\n", 1)[0].endswith("[Generic > OLake CLI]")
    nessie = next(c for c in chunks if "**Tab: Nessie**" in c["text"])
    assert nessie["text"].split("\n", 1)[0].endswith("[Nessie]")


def test_text_after_a_tab_group_belongs_to_no_tab(fixture_text):
    chunks = docs_chunks(doc_page(fixture_text))
    after = next(c for c in chunks if "Text after the tab group" in c["text"])
    assert "[" not in after["text"].split("\n", 1)[0]
    assert "**Tab:" not in after["text"]


def test_sibling_panels_with_equal_labels_never_merge():
    md = "\n\n".join(["# Page", "<!-- tabs:start -->", "**Tab: UI**", "first group ui", "**Tab: CLI**",
                      "first group cli", "<!-- tabs:end -->", "<!-- tabs:start -->", "**Tab: CLI**",
                      "second group cli", "<!-- tabs:end -->"])
    pieces = chunk_markdown(md, title="Page", lead="OLake Go")
    for r in pieces:
        assert body(r.text).count("**Tab: CLI**") <= 1


# ----------------------------------------------------------------------------- sizes, fences, tables
def test_nothing_over_hard_max_and_fences_balanced():
    code = "\n".join(f"line_{i} = {'x' * 40}" for i in range(400))
    md = f"# Title\n\n## Big code\n\n```python title=\"big.py\"\n{code}\n```\n\n## Prose\n\n{big_paragraph(2000)}\n"
    pieces = chunk_markdown(md, title="Big page", lead="OLake Go")
    assert len(pieces) > 4
    for r in pieces:
        assert ntok(r.text) <= CHUNK_HARD_MAX
        assert fences_balanced(r.text)
    code_pieces = [r for r in pieces if "```python" in r.text]
    assert len(code_pieces) > 1  # split at line boundaries, fence re-opened in every piece
    assert all(body(r.text).rstrip().endswith("```") for r in code_pieces)


def test_unterminated_fence_is_closed():
    pieces = chunk_markdown("# T\n\n```bash\necho hi\n", title="T")
    assert all(fences_balanced(r.text) for r in pieces)


def test_table_kept_whole_under_hard_max():
    rows = "\n".join(f"| key_{i} | value {i} |" for i in range(15))
    md = f"# T\n\nIntro text.\n\n## Types\n\n| Source type | Destination type |\n|---|---|\n{rows}\n\nAfter.\n"
    pieces = chunk_markdown(md, title="T")
    holders = [r for r in pieces if "| key_0 |" in r.text]
    assert len(holders) == 1 and all(f"| key_{i} |" in holders[0].text for i in range(15))


def test_oversized_table_split_at_rows_repeating_the_header():
    rows = "\n".join(f"| jsonb_{i} | string | {big_paragraph(12, 'note')} |" for i in range(120))
    md = f"# Types\n\n| Postgres type | Iceberg type | Notes |\n|---|---|---|\n{rows}\n"
    pieces = chunk_markdown(md, title="Type mapping")
    table_pieces = [r for r in pieces if "| jsonb_" in r.text]
    assert len(table_pieces) > 1
    seen = []
    for r in table_pieces:
        b = body(r.text)
        lines = [ln for ln in b.split("\n") if ln.startswith("|")]
        assert lines[0] == "| Postgres type | Iceberg type | Notes |" and lines[1] == "|---|---|---|"
        assert ntok(r.text) <= CHUNK_HARD_MAX
        seen += [ln for ln in lines[2:]]
    assert len(seen) == 120  # every row exactly once, never cut mid-row


def test_headings_are_not_orphaned():
    md = "# Page\n\nIntro.\n\n## Section A\n\n" + big_paragraph(600) + "\n\n## Section B\n\nShort text B.\n"
    pieces = chunk_markdown(md, title="Page")
    for r in pieces:
        blocks = parse_markdown(body(r.text))
        assert blocks[-1].kind not in ("heading", "tab"), r.text[-80:]
    first_a = next(r for r in pieces if "## Section A" in r.text)
    assert "lorem0" in first_a.text  # the heading travels with the start of its content


# ----------------------------------------------------------------------------- anchors and ids
def test_anchor_kept_only_if_the_id_exists(fixture_text):
    page = doc_page(fixture_text)
    chunks = docs_chunks(page)
    anchored = [c for c in chunks if c["anchor"]]
    assert anchored
    for c in anchored:
        assert c["anchor"] in page["ids"] and c["url"] == f"{URL}#{c['anchor']}"
    page["ids"] = set()  # same page, no ids: every anchor dropped
    for c in docs_chunks(page):
        assert c["anchor"] is None and c["url"] == URL


def test_stable_ids_and_hashes(fixture_text):
    a = docs_chunks(doc_page(fixture_text))
    b = docs_chunks(doc_page(fixture_text))
    assert [c["id"] for c in a] == [c["id"] for c in b]
    assert [c["hash"] for c in a] == [c["hash"] for c in b]
    assert [c["id"] for c in a] == [f"docs/writers/example#{i}" for i in range(len(a))]
    assert [c["ord"] for c in a] == list(range(len(a)))


def test_no_empty_chunks(fixture_text):
    for c in docs_chunks(doc_page(fixture_text)):
        assert body(c["text"]).strip()


# ----------------------------------------------------------------------------- yaml / go
def test_yaml_split_at_top_level_keys_with_line_numbers():
    sections = []
    for key in ("global", "olakeUI", "postgresql", "minio"):
        sections.append(f"# -- {key} settings\n{key}:\n" + "\n".join(f"  opt_{i}: {i}  # comment {i}" for i in range(60)))
    text = "\n".join(sections)
    lines = text.split("\n")
    pieces = chunk_code(text, "yaml", title="olake-helm: helm/olake/values.yaml", lead="GitHub repo")
    assert len(pieces) >= 4
    for p in pieces:
        assert ntok(p.text) <= CHUNK_HARD_MAX and fences_balanced(p.text)
        inner = body(p.text).split("\n")[1:-1]
        assert inner == lines[p.start - 1:p.end]  # 1-based inclusive line range matches the source
    assert any(p.section_path and p.section_path[0] == "postgresql" for p in pieces)


def test_go_split_at_declarations_drops_imports():
    funcs = "\n\n".join(f"// cmd{i} does a thing\nfunc cmd{i}() {{\n" + "\n".join(f"\tx{j} := {j}" for j in range(50)) + "\n}"
                        for i in range(4))
    text = f"package protocol\n\nimport (\n\t\"fmt\"\n)\n\n{funcs}\n"
    pieces = chunk_code(text, "go", title="olake: protocol/root.go")
    assert pieces and all("import (" not in p.text for p in pieces)
    assert any(re.search(r"^func cmd0\(\)", body(p.text), re.M) for p in pieces)
    assert all(ntok(p.text) <= CHUNK_HARD_MAX for p in pieces)
