"""Fetch olake.io pages listed in the sitemap and extract them to Markdown.

    uv run python -I -m ingest.docs [--blog]

Writes (outside the repo, under $ASK_OLAKE_CACHE):
    html/<section>/<slug>.html      raw HTML (untrusted data, never executed)
    corpus/docs.jsonl               one record per page: url, title, breadcrumb,
                                    lastmod, etag, sha256, markdown
    corpus/blog.jsonl               same for /blog/ pages when --blog is given
    corpus/fetch_docs.json          timings
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import time
import xml.etree.ElementTree as ET

import httpx

from common.config import (
    CORPUS_DIR, HTML_DIR, MAX_CONCURRENCY, SITEMAP_URL, USER_AGENT, ensure_dirs, write_json, write_jsonl,
)
from ingest.html2md import extract_page

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for url in root.findall("sm:url", NS):
        loc = url.findtext("sm:loc", default="", namespaces=NS).strip()
        lastmod = url.findtext("sm:lastmod", default=None, namespaces=NS)
        out.append({"url": loc, "lastmod": lastmod})
    return out


def section_of(url: str) -> str:
    m = re.match(r"https://olake\.io/(docs|blog)/", url)
    return m.group(1) if m else "other"


def slug_of(url: str) -> str:
    path = re.sub(r"^https://olake\.io/", "", url).strip("/")
    return re.sub(r"[^A-Za-z0-9._-]+", "__", path) or "index"


async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, entry: dict) -> dict:
    async with sem:
        t0 = time.perf_counter()
        for attempt in range(3):
            try:
                r = await client.get(entry["url"])
                break
            except httpx.HTTPError as e:  # transient network error -> retry
                if attempt == 2:
                    return {**entry, "error": repr(e)}
                await asyncio.sleep(1 + attempt)
        elapsed = time.perf_counter() - t0
    rec = {
        **entry,
        "status": r.status_code,
        "final_url": str(r.url),
        "etag": r.headers.get("etag"),
        "last_modified": r.headers.get("last-modified"),
        "bytes_html": len(r.content),
        "fetch_s": round(elapsed, 3),
    }
    if r.status_code != 200:
        rec["error"] = f"HTTP {r.status_code}"
        return rec
    section = section_of(entry["url"])
    path = HTML_DIR / section / f"{slug_of(entry['url'])}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    rec["html_path"] = str(path.relative_to(HTML_DIR))
    rec["_html"] = r.text
    return rec


def select(entries: list[dict], include_blog: bool) -> list[dict]:
    wanted = [e for e in entries if section_of(e["url"]) == "docs"]
    if include_blog:
        wanted += [e for e in entries if section_of(e["url"]) == "blog" and e["url"] != "https://olake.io/blog/"]
    return wanted


def load_offline(include_blog: bool) -> tuple[list[dict], list[dict]]:
    """Re-extract from the cached sitemap + HTML (no network)."""
    import json
    entries = parse_sitemap((CORPUS_DIR / "sitemap.xml").read_text())
    meta = {}
    for section in ("docs", "blog"):
        p = CORPUS_DIR / f"{section}.jsonl"
        if p.exists():
            for line in p.open():
                r = json.loads(line)
                meta[r["url"]] = {k: r.get(k) for k in ("status", "final_url", "etag", "last_modified", "bytes_html", "fetch_s", "html_path")}
    fetched = []
    for e in select(entries, include_blog):
        m = meta.get(e["url"])
        if not m:
            fetched.append({**e, "error": "not in cache"})
            continue
        fetched.append({**e, **m, "_html": (HTML_DIR / m["html_path"]).read_text()})
    return entries, fetched


async def run(include_blog: bool, offline: bool) -> None:
    ensure_dirs()
    t_start = time.perf_counter()
    fetch_s = 0.0
    if offline:
        entries, fetched = load_offline(include_blog)
        wanted = fetched
    else:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(headers=headers, timeout=30, follow_redirects=True) as client:
            sm = await client.get(SITEMAP_URL)
            sm.raise_for_status()
            (CORPUS_DIR / "sitemap.xml").write_bytes(sm.content)
            entries = parse_sitemap(sm.text)
            wanted = select(entries, include_blog)
            sem = asyncio.Semaphore(MAX_CONCURRENCY)
            fetched, section_fetch_s = [], {}
            for section in ("docs", "blog"):  # timed separately so docs-only cost is visible
                batch = [e for e in wanted if section_of(e["url"]) == section]
                if not batch:
                    continue
                t_fetch = time.perf_counter()
                fetched += await asyncio.gather(*(fetch_one(client, sem, e) for e in batch))
                section_fetch_s[section] = round(time.perf_counter() - t_fetch, 2)
            fetch_s = sum(section_fetch_s.values())

    t_extract = time.perf_counter()
    by_section: dict[str, list[dict]] = {"docs": [], "blog": []}
    errors = []
    for rec in fetched:
        if "error" in rec:
            errors.append({k: rec.get(k) for k in ("url", "status", "error")})
            continue
        page = extract_page(rec.pop("_html"), rec["url"])
        md = page["markdown"]
        rec.update(
            {
                "section": section_of(rec["url"]),
                "title": page["title"],
                "h1": page["h1"],
                "description": page["description"],
                "breadcrumb": page["breadcrumb"],
                "canonical": page["canonical"],
                "last_updated": page["last_updated"],
                "extract_stats": page["extract_stats"],
                "sha256": hashlib.sha256(md.encode()).hexdigest(),
                "markdown": md,
            }
        )
        if page["canonical"].rstrip("/") != rec["url"].rstrip("/"):
            rec["canonical_mismatch"] = True
        by_section[rec["section"]].append(rec)
    extract_s = time.perf_counter() - t_extract

    for section, rows in by_section.items():
        if rows:
            rows.sort(key=lambda r: r["url"])
            write_jsonl(CORPUS_DIR / f"{section}.jsonl", rows)
    timing = {
        "sitemap_urls": len(entries),
        "requested": len(wanted),
        "fetched_ok": sum(len(v) for v in by_section.values()),
        "per_section": {k: len(v) for k, v in by_section.items()},
        "errors": errors,
        "concurrency": MAX_CONCURRENCY,
        "fetch_wall_s": round(fetch_s, 2),
        "fetch_wall_s_by_section": {} if offline else section_fetch_s,
        "extract_wall_s": round(extract_s, 2),
        "total_wall_s": round(time.perf_counter() - t_start, 2),
        "html_bytes": sum(r.get("bytes_html", 0) for r in fetched),
        "per_page_fetch_s_p50": sorted(r.get("fetch_s", 0) for r in fetched)[len(fetched) // 2] if fetched else None,
    }
    if offline:
        timing["offline_reextract"] = True
        print(timing)
        return
    write_json(CORPUS_DIR / "fetch_docs.json", timing)
    print(timing)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog", action="store_true", help="also fetch /blog/ posts (measured separately)")
    ap.add_argument("--offline", action="store_true", help="re-extract from cached HTML, no network")
    args = ap.parse_args()
    asyncio.run(run(args.blog, args.offline))


if __name__ == "__main__":
    main()
