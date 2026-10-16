"""Fetch the latest GitHub release notes of the OLake repos (fresher than the docs' release pages).

    uv run python -I -m ingest.releases [--per-repo 10]

Uses the authenticated `gh` CLI (5000 req/h; 4 requests in total here). Writes
$ASK_OLAKE_CACHE/corpus/releases.jsonl with one record per release: repo, tag,
url (https://github.com/<org>/<repo>/releases/tag/<tag>), published_at and the
release body as Markdown.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time

from common.config import CORPUS_DIR, GITHUB_ORG, REPOS, ensure_dirs, write_json, write_jsonl


def fetch(repo: str, per_repo: int) -> list[dict]:
    out = subprocess.run(["gh", "api", f"repos/{GITHUB_ORG}/{repo}/releases?per_page={per_repo}"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-repo", type=int, default=10)
    args = ap.parse_args()
    ensure_dirs()
    t0 = time.perf_counter()
    rows, summary = [], {}
    for repo in REPOS:
        rels = [r for r in fetch(repo, args.per_repo) if not r.get("draft")]
        summary[repo] = {"releases": len(rels), "newest": rels[0]["tag_name"] if rels else None,
                         "oldest_kept": rels[-1]["tag_name"] if rels else None}
        for r in rels:
            body = (r.get("body") or "").replace("\r\n", "\n").strip()
            title = f"{repo} {r['tag_name']} release notes" + (f": {r['name']}" if r.get("name") and r["name"] != r["tag_name"] else "")
            md = f"# {title}\n\nPublished {r.get('published_at', '')[:10]}" + (" (pre-release)" if r.get("prerelease") else "") + f"\n\n{body}\n"
            rows.append({
                "repo": repo, "tag": r["tag_name"], "url": r["html_url"], "title": title,
                "published_at": r.get("published_at"), "prerelease": r.get("prerelease", False),
                "markdown": md, "sha256": hashlib.sha256(md.encode()).hexdigest(),
            })
    write_jsonl(CORPUS_DIR / "releases.jsonl", rows)
    summary_all = {"fetch_s": round(time.perf_counter() - t0, 2), "per_repo": summary, "releases": len(rows)}
    write_json(CORPUS_DIR / "fetch_releases.json", summary_all)
    print(summary_all)


if __name__ == "__main__":
    main()
