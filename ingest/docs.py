"""Docs pages: sitemap -> rendered HTML -> extracted Markdown page records.

    fetch_sitemap(offline)  -> SitemapResult (xml text, ETag, Last-Modified)
    fetch_docs(entries)     -> [page records] (url, lastmod, source_type, product, title, breadcrumb,
                               markdown, ids, hash) plus a list of errors

The page hash is the sha256 of the extracted Markdown: the only content signal (HTTP ETag,
Last-Modified and sitemap lastmod are not).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from ingest import config
from ingest.fetch import conditional_get, fetch_many, read_cache, write_cache
from ingest.html2md import extract_page
from ingest.sitemap import DocEntry, canonical_docs_url

log = logging.getLogger("ingest.docs")


@dataclass
class SitemapResult:
    status: int | None
    text: str
    etag: str | None
    last_modified: str | None
    from_cache: bool = False
    error: str | None = None


def fetch_sitemap(*, offline: bool = False, etag: str | None = None) -> SitemapResult:
    """GET the sitemap (conditional when `etag` is given). Offline: the cached copy."""
    if offline:
        res = read_cache(config.SITEMAP_URL)
        if res.error:
            raise RuntimeError("offline and no cached sitemap.xml (run one online build first)")
        return SitemapResult(200, res.text, res.etag, res.last_modified, from_cache=True)
    res = conditional_get(config.SITEMAP_URL, etag)
    if res.status == 304:
        return SitemapResult(304, "", res.etag or etag, res.last_modified)
    if not res.ok:
        return SitemapResult(res.status, "", None, None, error=res.error or f"HTTP {res.status}")
    write_cache(res)
    return SitemapResult(200, res.text, res.etag, res.last_modified)


def page_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def extract_doc(entry: DocEntry, html: str) -> dict:
    page = extract_page(html, entry.url)
    canonical = page.get("canonical") or entry.url
    if canonical_docs_url(canonical) != entry.url:
        log.warning("canonical link differs from the sitemap URL: %s -> %s (the sitemap URL is cited)",
                    entry.url, canonical)
    return {
        "url": entry.url, "lastmod": entry.lastmod, "source_type": entry.source_type, "product": entry.product,
        "title": page["title"] or page["h1"] or entry.url, "breadcrumb": page["breadcrumb"],
        "markdown": page["markdown"], "ids": page["ids"], "hash": page_hash(page["markdown"]),
        "stats": page["extract_stats"],
    }


def fetch_docs(entries: list[DocEntry], *, offline: bool = False) -> tuple[list[dict], list[dict]]:
    """Fetch (or read from the cache) and extract every page. Returns (pages, errors)."""
    results = fetch_many([e.url for e in entries], offline=offline)
    pages, errors = [], []
    for e in entries:
        res = results[e.url]
        if not res.ok:
            errors.append({"url": e.url, "status": res.status, "error": res.error})
            log.warning("docs page skipped: %s (%s)", e.url, res.error or res.status)
            continue
        if res.final_url and canonical_docs_url(res.final_url) != e.url:
            log.warning("docs page redirected: %s -> %s", e.url, res.final_url)
        page = extract_doc(e, res.text)
        if not page["markdown"].strip():
            errors.append({"url": e.url, "status": res.status, "error": "empty article"})
            log.warning("docs page has no article text: %s", e.url)
            continue
        pages.append(page)
    return pages, errors
