"""Polite HTTP fetching with an on-disk cache.

* at most 4 requests in flight (a thread pool around one httpx client), a descriptive User-Agent,
  gzip, a 20 s timeout and 2 retries on transport errors, 429 and 5xx;
* every 200 body is cached under .cache/html/<host>/<slug>.html with a .json sidecar holding the
  status, ETag, Last-Modified and fetch time; `offline=True` reads only from that cache;
* `conditional_get` sends If-None-Match for the sitemap poll (a 304 means "no deploy since").

The cache holds untrusted data: it is parsed, never executed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ingest import config

log = logging.getLogger("ingest.fetch")

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    status: int | None = None
    text: str = ""
    etag: str | None = None
    last_modified: str | None = None
    final_url: str | None = None
    fetched_at: str | None = None
    from_cache: bool = False
    error: str | None = None
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cache_path(url: str, root: Path | None = None) -> Path:
    """.cache/html/<host>/<path slug>.html; long slugs get a hash suffix."""
    parts = urlsplit(url)
    host = (parts.hostname or "unknown").lower()
    slug = re.sub(r"[^A-Za-z0-9._-]+", "__", (parts.path + ("?" + parts.query if parts.query else "")).strip("/"))
    slug = slug or "index"
    if len(slug) > 150:
        slug = slug[:120] + "-" + hashlib.sha256(slug.encode()).hexdigest()[:16]
    return (root or config.HTML_DIR) / host / f"{slug}.html"


def write_cache(res: FetchResult, root: Path | None = None) -> None:
    path = cache_path(res.url, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(res.text, encoding="utf-8")
    meta = {"url": res.url, "status": res.status, "etag": res.etag, "last_modified": res.last_modified,
            "final_url": res.final_url, "fetched_at": res.fetched_at}
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")


def read_cache(url: str, root: Path | None = None) -> FetchResult:
    path = cache_path(url, root)
    if not path.exists():
        return FetchResult(url, error="not in cache", from_cache=True)
    meta = {}
    if path.with_suffix(".json").exists():
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return FetchResult(url, status=meta.get("status", 200), text=path.read_text(encoding="utf-8"),
                       etag=meta.get("etag"), last_modified=meta.get("last_modified"),
                       final_url=meta.get("final_url"), fetched_at=meta.get("fetched_at"), from_cache=True)


def make_client(user_agent: str = config.USER_AGENT) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
                        timeout=config.HTTP_TIMEOUT_S, follow_redirects=True)


def get(client: httpx.Client, url: str, headers: dict | None = None, retries: int = config.HTTP_RETRIES) -> FetchResult:
    """One GET with retries on transport errors, 429 and 5xx. Never raises."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = client.get(url, headers=headers or {})
        except httpx.HTTPError as e:
            last_err = f"{type(e).__name__}: {e}"
        else:
            if r.status_code in RETRY_STATUS and attempt < retries:
                last_err = f"HTTP {r.status_code}"
            else:
                res = FetchResult(url, status=r.status_code, etag=r.headers.get("etag"),
                                  last_modified=r.headers.get("last-modified"), final_url=str(r.url),
                                  fetched_at=now_iso(), headers=dict(r.headers))
                if r.status_code == 200:
                    res.text = r.text
                elif r.status_code != 304:
                    res.error = f"HTTP {r.status_code}"
                return res
        time.sleep(1.0 + attempt)
    return FetchResult(url, error=last_err or "failed", fetched_at=now_iso())


def fetch_many(urls: list[str], *, offline: bool = False, root: Path | None = None,
               user_agent: str = config.USER_AGENT, concurrency: int = config.MAX_CONCURRENCY,
               client: httpx.Client | None = None) -> dict[str, FetchResult]:
    """Fetch every URL (at most `concurrency` at a time) and cache the 200s. Offline: cache only."""
    if offline:
        return {u: read_cache(u, root) for u in urls}
    own = client is None
    client = client or make_client(user_agent)
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, config.MAX_CONCURRENCY))) as pool:
            results = dict(zip(urls, pool.map(lambda u: get(client, u), urls)))
    finally:
        if own:
            client.close()
    for res in results.values():
        if res.ok:
            write_cache(res, root)
    return results


def conditional_get(url: str, etag: str | None, *, client: httpx.Client | None = None) -> FetchResult:
    """GET with If-None-Match. status 304 = unchanged since `etag` (only "no deploy", never content)."""
    own = client is None
    client = client or make_client()
    try:
        return get(client, url, headers={"If-None-Match": etag} if etag else None)
    finally:
        if own:
            client.close()
