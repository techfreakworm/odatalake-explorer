"""Write a durable manifest of the extracted docs corpus.

    uv run python -I -m ingest.manifest [--out results/docs-manifest-YYYY-MM-DD.json]

One record per docs page: url, title, sitemap lastmod, page "Last updated",
o200k tokens, Markdown bytes and the sha256 of the extracted Markdown. The
extractor commit is recorded too: hashes are only comparable between manifests
produced by the same extractor (ingest/html2md.py).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess

import tiktoken

from common.config import CORPUS_DIR, POC_DIR, RESULTS_DIR, read_jsonl, write_json

ENC = tiktoken.get_encoding("o200k_base")


def extractor_commit() -> str | None:
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h", "--", "ingest/html2md.py"], cwd=POC_DIR,
                             capture_output=True, text=True, check=True).stdout.strip()
        return out or None
    except Exception:  # noqa: BLE001  (not a git checkout)
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RESULTS_DIR / f"docs-manifest-{dt.date.today().isoformat()}.json"))
    args = ap.parse_args()
    fetch = json.loads((CORPUS_DIR / "fetch_docs.json").read_text()) if (CORPUS_DIR / "fetch_docs.json").exists() else {}
    pages = []
    for r in read_jsonl(CORPUS_DIR / "docs.jsonl"):
        md = r["markdown"]
        pages.append({
            "url": r["url"],
            "title": r["title"],
            "lastmod": r.get("lastmod"),
            "last_updated": r.get("last_updated"),
            "tokens": len(ENC.encode(md, disallowed_special=())),
            "md_bytes": len(md.encode()),
            "sha256": r["sha256"],
        })
    pages.sort(key=lambda p: p["url"])
    corpus_mtime = dt.datetime.fromtimestamp((CORPUS_DIR / "docs.jsonl").stat().st_mtime, tz=dt.timezone.utc)
    manifest = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "crawled_at": corpus_mtime.isoformat(timespec="seconds"),  # when docs.jsonl was written
        "extractor": "poc/ingest/html2md.py",
        "extractor_commit": extractor_commit(),
        "tokenizer": "tiktoken o200k_base",
        "sitemap_urls": fetch.get("sitemap_urls"),
        "pages": len(pages),
        "total_tokens": sum(p["tokens"] for p in pages),
        "docs": pages,
    }
    write_json(__import__("pathlib").Path(args.out), manifest)
    print(f"wrote {args.out}: {len(pages)} pages, {manifest['total_tokens']:,} tokens")


if __name__ == "__main__":
    main()
