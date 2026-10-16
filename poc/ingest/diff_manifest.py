"""Diff two docs manifests written by ingest.manifest.

    uv run python -I -m ingest.diff_manifest OLD.json NEW.json

Prints added, removed and changed URLs (changed = different sha256 of the
extracted Markdown), plus pages whose sitemap lastmod moved without a content
change. Re-chunk and re-embed only the added and changed pages.
"""

from __future__ import annotations

import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: python -I -m ingest.diff_manifest OLD.json NEW.json")
    old, new = load(sys.argv[1]), load(sys.argv[2])
    o = {p["url"]: p for p in old["docs"]}
    n = {p["url"]: p for p in new["docs"]}
    added = sorted(set(n) - set(o))
    removed = sorted(set(o) - set(n))
    changed = sorted(u for u in set(o) & set(n) if o[u]["sha256"] != n[u]["sha256"])
    lastmod_only = sorted(u for u in set(o) & set(n)
                          if o[u]["sha256"] == n[u]["sha256"] and o[u].get("lastmod") != n[u].get("lastmod"))
    if old.get("extractor_commit") != new.get("extractor_commit"):
        print(f"WARNING: extractor changed ({old.get('extractor_commit')} -> {new.get('extractor_commit')}); "
              "content hashes may differ for every page")
    print(f"old: {sys.argv[1]} ({len(o)} pages, crawled {old.get('crawled_at')})")
    print(f"new: {sys.argv[2]} ({len(n)} pages, crawled {new.get('crawled_at')})")
    print(f"added {len(added)}, removed {len(removed)}, changed {len(changed)}, "
          f"lastmod moved without content change {len(lastmod_only)}")
    for label, urls in (("ADDED", added), ("REMOVED", removed), ("CHANGED", changed)):
        for u in urls:
            delta = ""
            if label == "CHANGED":
                delta = f"  ({o[u]['tokens']} -> {n[u]['tokens']} tokens)"
            print(f"{label:8s} {u}{delta}")


if __name__ == "__main__":
    main()
