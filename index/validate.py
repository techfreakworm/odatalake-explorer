"""Validate the active index against contract I1 and the acceptance rules.

    uv run python -m index.validate [--version V]     exit 0 = valid, 1 = problems

Checks: the I1 chunk fields; every doc_url is a kept sitemap URL, a releases/tag URL, a
github.com/datazip-inc blob URL, a curated issue URL, a curated outside URL or a FAQ page (never
raw.githubusercontent.com or a legacy path); no empty chunk, none over the hard max, fences
balanced, no chunk spanning two tab panels, product set on docs chunks; the manifest's I1 keys;
embeddings float32 [n_chunks, dim], L2-normalized.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from index.build import BLOB_URL, RELEASE_URL, validate
from index.config import INDEX_DIR
from index.manifest import load_version, read_current
from ingest import config

MANIFEST_KEYS = ("version", "built_at", "embed_model", "embed_query_prefix", "dim", "chunker", "counts", "docs",
                 "repos", "releases", "denylist_skipped")


def doc_url_kind(c: dict, kept: set[str]) -> str:
    u = c["doc_url"]
    if u in kept:
        return "sitemap docs URL"
    if RELEASE_URL.match(u):
        return "releases/tag URL"
    if BLOB_URL.match(u):
        return "datazip-inc blob URL"
    if u in config.CURATED_ISSUES:
        return "curated issue URL"
    if u in {p for p, _ in config.OUTSIDE_PAGES}:
        return "curated outside URL"
    if u in {p for p, _ in config.FAQ_PAGES}:
        return "FAQ page"
    return "NOT ALLOWED"


def check(index_root: Path = INDEX_DIR, version: str | None = None) -> tuple[list[str], dict]:
    manifest, chunks, matrix = load_version(index_root, version)
    kept = set(manifest["docs"]["pages"])
    problems = validate(chunks, kept, manifest["chunker"]["hard_max"])
    problems += [f"manifest: missing {k}" for k in MANIFEST_KEYS if k not in manifest]
    if matrix.dtype != np.float32 or matrix.shape != (len(chunks), manifest["dim"]):
        problems.append(f"embeddings: {matrix.dtype} {matrix.shape}, expected float32 ({len(chunks)}, {manifest['dim']})")
    else:
        norms = np.linalg.norm(matrix, axis=1)
        if len(norms) and float(np.abs(norms - 1).max()) > 1e-3:
            problems.append(f"embeddings: rows not L2-normalized (max |norm-1| {float(np.abs(norms - 1).max()):.4f})")
    docs_pages = {c["doc_url"] for c in chunks if c["source_type"] in ("docs", "release")}
    if docs_pages != kept:
        problems.append(f"docs pages with chunks ({len(docs_pages)}) != manifest docs pages ({len(kept)})")
    kinds = Counter(doc_url_kind(c, kept) for c in chunks)
    if kinds.get("NOT ALLOWED"):
        problems.append(f"{kinds['NOT ALLOWED']} chunks with a doc_url outside the citation policy")
    stats = {"version": manifest["version"], "chunks": len(chunks), "docs_release_pages": len(docs_pages),
             "doc_url_kinds": dict(kinds), "max_tokens": max((c["tokens"] for c in chunks), default=0),
             "by_source_type": dict(Counter(c["source_type"] for c in chunks))}
    return problems, stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Validate the active index")
    ap.add_argument("--version", default=None)
    ap.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    args = ap.parse_args(argv)
    if not read_current(args.index_dir) and not args.version:
        sys.exit(f"no CURRENT in {args.index_dir}")
    problems, stats = check(args.index_dir, args.version)
    print(f"index {stats['version']}: {stats['chunks']} chunks, {stats['docs_release_pages']} docs + release pages, "
          f"max {stats['max_tokens']} tokens")
    for kind, n in sorted(stats["doc_url_kinds"].items()):
        print(f"  doc_url {kind}: {n}")
    for p in problems[:50]:
        print(f"PROBLEM {p}")
    print("valid" if not problems else f"{len(problems)} problems")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
