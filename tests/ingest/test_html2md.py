from __future__ import annotations

from ingest.html2md import TABS_END, TABS_START, extract_main, extract_page

URL = "https://olake.io/docs/writers/example/"


def page(fixture_text):
    return extract_page(fixture_text("docs_page.html"), URL)


def test_metadata(fixture_text):
    p = page(fixture_text)
    assert p["title"] == "OLake Example REST Catalog Setup"  # " | OLake" suffix dropped
    assert p["h1"] == "Example Catalog"
    assert p["breadcrumb"] == ["Destinations", "Catalogs"]  # no home icon, no active (current page) item
    assert p["canonical"] == URL
    assert {"prerequisites", "configuration", "authentication"} <= p["ids"]


def test_chrome_is_dropped(fixture_text):
    md = page(fixture_text)["markdown"]
    for junk in ("Navbar junk", "Sidebar item", "Site footer", "Edit this page", "Copy"):
        assert junk not in md


def test_headings_keep_anchor_without_hash_link(fixture_text):
    md = page(fixture_text)["markdown"]
    assert "## Prerequisites {#prerequisites}" in md.split("\n")
    assert "### Authentication {#authentication}" in md.split("\n")
    assert "​" not in md
    assert "Direct link" not in md


def test_nested_tabs_emitted_once_with_labels_and_markers(fixture_text):
    md = page(fixture_text)["markdown"]
    for label in ("Generic", "Nessie", "OLake UI", "OLake CLI"):
        assert md.count(f"**Tab: {label}**") == 1
    assert md.count("Fill the `Authentication Type` field") == 1  # the inner panel is not duplicated
    assert md.count(TABS_START) == 2 and md.count(TABS_END) == 2
    # the inner group sits inside the outer Generic panel, before the outer Nessie panel
    assert md.index("**Tab: Generic**") < md.index("**Tab: OLake UI**") < md.index("**Tab: OLake CLI**") \
        < md.index("**Tab: Nessie**")
    # lxml: labels are not concatenated despite the omitted </li> tags
    assert "GenericNessie" not in md and "OLake UIOLake CLI" not in md


def test_code_block_language_and_title(fixture_text):
    md = page(fixture_text)["markdown"]
    assert '```json title="destination.json"\n{\n  "type": "ICEBERG"\n}\n```' in md


def test_table_and_escaped_pipe(fixture_text):
    md = page(fixture_text)["markdown"]
    assert "| Parameter | Sample Value | Description |\n|---|---|---|" in md
    assert "| **REST Catalog URL**<br>`required` | `http://host:8181` | The REST endpoint. |" in md
    assert "Where data \\| metadata go." in md


def test_admonition_and_details(fixture_text):
    md = page(fixture_text)["markdown"]
    assert "> **Note: Catalog Name Supported for v0.3.5 and above:**\n> Only lowercase letters and underscores." in md
    assert "**Troubleshooting tips**\n\nCheck the endpoint is reachable." in md


def test_outside_main_content_skips_navigation():
    html = """<html><head><title>Ext Page</title></head><body><nav>Top nav links</nav>
    <main><nav class="md-sidebar">sidebar sidebar sidebar</nav><article class="md-content__inner">
    <h1 id="intro">Intro<a class="headerlink" href="#intro">¶</a></h1><p>""" + "Real content. " * 60 + """</p>
    </article></main><footer>foot</footer></body></html>"""
    out = extract_main(html, "https://example.org/page")
    assert out["selector"] == "article.md-content__inner"
    assert out["markdown"].startswith("# Intro {#intro}")
    assert "¶" not in out["markdown"] and "Top nav" not in out["markdown"] and "sidebar" not in out["markdown"]
