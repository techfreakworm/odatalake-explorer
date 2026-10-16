"""olake.io sitemap -> the docs URL list (url, lastmod, source_type, product), minus the denylist.

doc_url policy (research.md §3.5): the sitemap URL exactly, i.e. https, the apex host, a trailing
slash, the original case, no query and no fragment. `canonical_docs_url` maps the other spellings
of a docs URL (http, www, no slash, #anchor, ?query) to that form; it never changes path case.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ingest import config

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@dataclass(frozen=True)
class DocEntry:
    url: str
    lastmod: str | None
    source_type: str  # docs | release
    product: str      # go | fusion


def parse_sitemap(xml_text: str | bytes) -> list[dict]:
    """[{url, lastmod}] in sitemap order."""
    root = ET.fromstring(xml_text)
    out = []
    for url in root.findall("sm:url", NS):
        loc = (url.findtext("sm:loc", default="", namespaces=NS) or "").strip()
        lastmod = url.findtext("sm:lastmod", default=None, namespaces=NS)
        if loc:
            out.append({"url": loc, "lastmod": lastmod.strip() if lastmod else None})
    return out


def canonical_docs_url(url: str) -> str:
    """https + apex host + trailing slash, no query, no fragment; path case is kept."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or "/"
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urlunsplit(("https", host, path, "", ""))


def path_of(url: str) -> str:
    return urlsplit(url).path


def is_denylisted(url: str, denylist: tuple[str, ...] = config.DENYLIST) -> bool:
    return path_of(canonical_docs_url(url)) in set(denylist)


def source_type_of(url: str) -> str:
    return "release" if url.startswith(config.RELEASE_PREFIXES) else "docs"


def product_of(url: str) -> str:
    return "fusion" if url.startswith(config.FUSION_PREFIX) else "go"


def select_docs(entries: list[dict], denylist: tuple[str, ...] = config.DENYLIST) -> tuple[list[DocEntry], list[str]]:
    """Return (kept docs entries, skipped denylisted URLs), both in sitemap order."""
    kept, skipped = [], []
    seen = set()
    for e in entries:
        url = e["url"]
        if not url.startswith(config.DOCS_PREFIX) or url in seen:
            continue
        seen.add(url)
        if is_denylisted(url, denylist):
            skipped.append(url)
            continue
        kept.append(DocEntry(url, e.get("lastmod"), source_type_of(url), product_of(url)))
    return kept, skipped


def docs_urls(entries: list[dict]) -> list[str]:
    """Every /docs/ URL in the sitemap (before the denylist)."""
    return [e["url"] for e in entries if e["url"].startswith(config.DOCS_PREFIX)]
