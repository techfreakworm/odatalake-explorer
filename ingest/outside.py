"""Curated outside pages (tier 4): main-content extraction, labelled in the chunk header.

Labels: "outside OLake docs", and "upstream Amoro; Fusion may differ" for Amoro pages. A page that
answers 403 or fails is skipped with a log line (no browser User-Agent spoofing).
"""

from __future__ import annotations

import hashlib
import logging

from ingest import config
from ingest.fetch import fetch_many
from ingest.html2md import extract_main

log = logging.getLogger("ingest.outside")


def fetch_outside(*, offline: bool = False, pages: tuple[tuple[str, str], ...] = config.OUTSIDE_PAGES
                  ) -> tuple[list[dict], list[dict]]:
    """Returns (page records {url, label, title, markdown, ids, hash, n}, skipped [{url, status, error}])."""
    results = fetch_many([u for u, _ in pages], offline=offline)
    recs, skipped = [], []
    for n, (url, label) in enumerate(pages):
        res = results[url]
        if not res.ok:
            skipped.append({"url": url, "status": res.status, "error": res.error})
            log.warning("outside page skipped: %s (%s)", url, res.error or res.status)
            continue
        page = extract_main(res.text, url)
        if not page["markdown"].strip():
            skipped.append({"url": url, "status": res.status, "error": "no main content found"})
            log.warning("outside page skipped: %s (no main content found)", url)
            continue
        recs.append({"url": url, "label": label, "n": n, "title": page["title"], "markdown": page["markdown"],
                     "ids": page["ids"], "selector": page.get("selector"),
                     "hash": hashlib.sha256(page["markdown"].encode("utf-8")).hexdigest()})
    return recs, skipped
