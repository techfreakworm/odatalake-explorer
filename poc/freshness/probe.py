"""Freshness probe -> poc/results/freshness.json

    uv run python -I -m freshness.probe

1. Conditional GET (If-None-Match / If-Modified-Since) on a docs page and on
   sitemap.xml: does olake.io answer 304, and what do ETag/Last-Modified encode?
2. GitHub REST API commits endpoint, unauthenticated and (if `gh` or
   GITHUB_TOKEN gives a token) authenticated: does a 304 come back, and does it
   count against X-RateLimit? Measured via GET /rate_limit, which is free.
3. `git ls-remote` HEAD check (no REST rate limit) and its latency.
4. Sitemap lastmod diff routine, run on cached-vs-live and on a synthetic edit.
The token is only held in memory; nothing secret is written.
"""

from __future__ import annotations

import copy
import os
import subprocess
import time
from datetime import datetime, timezone

import httpx

from common.config import CORPUS_DIR, GITHUB_ORG, REPOS, RESULTS_DIR, USER_AGENT, read_jsonl, write_json
from ingest.docs import parse_sitemap

DOC_URL = "https://olake.io/docs/connectors/postgres/"
SITEMAP = "https://olake.io/sitemap.xml"


def timed_get(client: httpx.Client, url: str, headers: dict | None = None) -> tuple[httpx.Response, float]:
    t0 = time.perf_counter()
    r = client.get(url, headers=headers or {})
    return r, round((time.perf_counter() - t0) * 1000, 1)


def conditional_probe(client: httpx.Client, url: str) -> dict:
    r1, ms1 = timed_get(client, url)
    etag, lm = r1.headers.get("etag"), r1.headers.get("last-modified")
    r2, ms2 = timed_get(client, url, {"If-None-Match": etag} if etag else {})
    r3, ms3 = timed_get(client, url, {"If-Modified-Since": lm} if lm else {})
    r4, ms4 = timed_get(client, url, {"If-None-Match": 'W/"00000000-0"'})
    out = {
        "url": url,
        "first": {"status": r1.status_code, "bytes": len(r1.content), "ms": ms1, "etag": etag, "last_modified": lm,
                  "cache_control": r1.headers.get("cache-control"), "age": r1.headers.get("age"),
                  "x_cache": r1.headers.get("x-cache"), "server": r1.headers.get("server")},
        "if_none_match": {"status": r2.status_code, "bytes": len(r2.content), "ms": ms2},
        "if_modified_since": {"status": r3.status_code, "bytes": len(r3.content), "ms": ms3},
        "stale_etag": {"status": r4.status_code, "bytes": len(r4.content), "ms": ms4},
    }
    # nginx-style ETag "<hex mtime>-<hex size>": decode to show it is a deploy timestamp, not a content hash
    if etag:
        core = etag.removeprefix("W/").strip('"')
        if "-" in core:
            mt, size = core.split("-", 1)
            try:
                out["etag_decoded"] = {
                    "mtime_utc": datetime.fromtimestamp(int(mt, 16), tz=timezone.utc).isoformat(),
                    "size_bytes": int(size, 16),
                }
            except ValueError:
                pass
    return out


def gh_token() -> str | None:
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip() or None
    except Exception:
        return None


def rate(client: httpx.Client, headers: dict) -> dict:
    r = client.get("https://api.github.com/rate_limit", headers=headers)
    core = r.json().get("resources", {}).get("core", {})
    return {"limit": core.get("limit"), "remaining": core.get("remaining"), "used": core.get("used")}


def github_probe(client: httpx.Client, token: str | None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{GITHUB_ORG}/olake/commits?per_page=1"
    before = rate(client, headers)
    r1, ms1 = timed_get(client, url, headers)
    after_200 = rate(client, headers)
    etag = r1.headers.get("etag")
    conds = []
    for _ in range(3):
        r2, ms2 = timed_get(client, url, {**headers, "If-None-Match": etag})
        conds.append({"status": r2.status_code, "ms": ms2,
                      "x_ratelimit_remaining_header": r2.headers.get("x-ratelimit-remaining")})
    after_304 = rate(client, headers)
    # cheapest "what is HEAD?" call: commits/<branch> with the sha media type
    r3, ms3 = timed_get(client, f"https://api.github.com/repos/{GITHUB_ORG}/olake/commits/HEAD",
                        {**headers, "Accept": "application/vnd.github.sha"})
    return {
        "authenticated": bool(token),
        "rate_before": before,
        "first": {"status": r1.status_code, "ms": ms1, "etag": etag,
                  "x_ratelimit_remaining_header": r1.headers.get("x-ratelimit-remaining")},
        "rate_after_200": after_200,
        "conditional_requests": conds,
        "rate_after_3x_conditional": after_304,
        "conditional_cost": (after_200["used"] is not None and after_304["used"] is not None
                             and after_304["used"] - after_200["used"]),
        "sha_media_type": {"status": r3.status_code, "ms": ms3, "body": r3.text.strip()[:40]},
    }


def ls_remote_probe() -> dict:
    fetch = {r["repo"]: r["sha"] for r in __import__("json").loads((CORPUS_DIR / "fetch_repos.json").read_text())["repos"]}
    out = {}
    for repo in REPOS:
        t0 = time.perf_counter()
        res = subprocess.run(["git", "ls-remote", f"https://github.com/{GITHUB_ORG}/{repo}.git", "HEAD"],
                             capture_output=True, text=True)
        sha = res.stdout.split()[0] if res.stdout else None
        out[repo] = {"ms": round((time.perf_counter() - t0) * 1000, 1), "head": sha,
                     "indexed_sha": fetch.get(repo), "changed_since_index": sha != fetch.get(repo)}
    return out


def diff_sitemaps(old: list[dict], new: list[dict], prefix: str = "https://olake.io/docs/") -> dict:
    o = {e["url"]: e.get("lastmod") for e in old if e["url"].startswith(prefix)}
    n = {e["url"]: e.get("lastmod") for e in new if e["url"].startswith(prefix)}
    return {
        "added": sorted(set(n) - set(o)),
        "removed": sorted(set(o) - set(n)),
        "lastmod_changed": sorted(u for u in set(o) & set(n) if o[u] != n[u]),
    }


def main() -> None:
    out: dict = {"probed_at": datetime.now(timezone.utc).isoformat()}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        out["docs_page"] = conditional_probe(client, DOC_URL)
        out["sitemap"] = conditional_probe(client, SITEMAP)
        live = parse_sitemap(client.get(SITEMAP).text)
        out["github_unauthenticated"] = github_probe(client, None)
        token = gh_token()
        out["github_authenticated"] = github_probe(client, token) if token else "no token available"
    out["git_ls_remote"] = ls_remote_probe()

    cached = parse_sitemap((CORPUS_DIR / "sitemap.xml").read_text())
    synthetic = copy.deepcopy(cached)
    docs_entries = [e for e in synthetic if e["url"].startswith("https://olake.io/docs/")]
    docs_entries[0]["lastmod"] = "2099-01-01"
    synthetic.remove(docs_entries[1])
    synthetic.append({"url": "https://olake.io/docs/new-page/", "lastmod": "2099-01-01"})
    out["sitemap_diff"] = {"cached_vs_live": diff_sitemaps(cached, live), "synthetic_check": diff_sitemaps(cached, synthetic)}

    docs = read_jsonl(CORPUS_DIR / "docs.jsonl")
    lm = {}
    for r in docs:
        lm[r["last_modified"]] = lm.get(r["last_modified"], 0) + 1
    lastmods = {}
    for r in docs:
        lastmods[r["lastmod"]] = lastmods.get(r["lastmod"], 0) + 1
    out["observations"] = {
        "docs_pages_by_http_last_modified": lm,
        "docs_pages_by_sitemap_lastmod": dict(sorted(lastmods.items(), key=lambda kv: -kv[1])),
    }
    write_json(RESULTS_DIR / "freshness.json", out)
    import json
    print(json.dumps({k: v for k, v in out.items() if k != "observations"}, indent=1)[:6000])


if __name__ == "__main__":
    main()
