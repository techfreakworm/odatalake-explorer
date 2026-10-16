from __future__ import annotations

import pytest

from ingest import config
from ingest.sitemap import canonical_docs_url, docs_urls, is_denylisted, parse_sitemap, select_docs


def test_parse_and_select_docs(fixture_text):
    entries = parse_sitemap(fixture_text("sitemap.xml"))
    assert len(entries) == 10
    assert docs_urls(entries).count("https://olake.io/docs/connectors/postgres/") == 2  # raw list keeps dupes
    kept, skipped = select_docs(entries)
    urls = [e.url for e in kept]
    assert urls == [
        "https://olake.io/docs/",
        "https://olake.io/docs/connectors/postgres/",
        "https://olake.io/docs/release/ingestion/v0.12.0/",
        "https://olake.io/docs/fusion/release/maintenance/v0.1.0/",
        "https://olake.io/docs/fusion/compaction/configuration/",
    ]  # sitemap order, deduplicated, no blog or marketing pages
    assert skipped == ["https://olake.io/docs/connectors/overview/", "https://olake.io/docs/core/configs/source/"]
    by = {e.url: e for e in kept}
    assert by["https://olake.io/docs/release/ingestion/v0.12.0/"].source_type == "release"
    assert by["https://olake.io/docs/fusion/release/maintenance/v0.1.0/"].source_type == "release"
    assert by["https://olake.io/docs/fusion/release/maintenance/v0.1.0/"].product == "fusion"
    assert by["https://olake.io/docs/fusion/compaction/configuration/"].product == "fusion"
    assert by["https://olake.io/docs/connectors/postgres/"].product == "go"
    assert by["https://olake.io/docs/connectors/postgres/"].source_type == "docs"
    assert by["https://olake.io/docs/connectors/postgres/"].lastmod == "2026-10-15"


def test_denylist_has_the_16_pages_and_matches_any_spelling():
    assert len(config.DENYLIST) == 16
    assert is_denylisted("https://olake.io/docs/core/configs/writer/")
    assert is_denylisted("http://www.olake.io/docs/core/configs/writer")
    assert is_denylisted("https://olake.io/docs/core/configs/writer/#anchor")
    assert not is_denylisted("https://olake.io/docs/writers/parquet/config/")


def test_custom_denylist_is_reversible(fixture_text):
    kept, skipped = select_docs(parse_sitemap(fixture_text("sitemap.xml")), denylist=())
    assert skipped == [] and "https://olake.io/docs/connectors/overview/" in [e.url for e in kept]


@pytest.mark.parametrize("raw,canon", [
    ("https://olake.io/docs/connectors/postgres/", "https://olake.io/docs/connectors/postgres/"),
    ("http://olake.io/docs/connectors/postgres", "https://olake.io/docs/connectors/postgres/"),
    ("https://www.olake.io/docs/connectors/postgres/", "https://olake.io/docs/connectors/postgres/"),
    ("https://OLAKE.io/docs/connectors/postgres/#cdc", "https://olake.io/docs/connectors/postgres/"),
    ("https://olake.io/docs/connectors/postgres/?tab=cli#x", "https://olake.io/docs/connectors/postgres/"),
    ("https://olake.io/customer-stories/lendingkart-Improved-Data-Correctness",
     "https://olake.io/customer-stories/lendingkart-Improved-Data-Correctness/"),  # path case is kept
    ("https://olake.io/sitemap.xml", "https://olake.io/sitemap.xml"),  # files get no slash
])
def test_canonical_docs_url(raw, canon):
    assert canonical_docs_url(raw) == canon
