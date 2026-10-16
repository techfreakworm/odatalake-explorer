"""BM25 probe over the active index.

    uv run python -m index.probe "<question>" [-k 5] [--version V]

Prints the top k chunks as: rank, score, source_type, doc_url, id. BM25 (bm25s, English stopwords,
Snowball stemmer) over each chunk's text, header included.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import bm25s
import Stemmer

from index.config import INDEX_DIR
from index.manifest import load_version

_stemmer = Stemmer.Stemmer("english")


def tokenize(texts: list[str]):
    return bm25s.tokenize(texts, stopwords="en", stemmer=_stemmer, return_ids=False, show_progress=False)


class BM25:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.model = bm25s.BM25()
        self.model.index(tokenize([c["text"] for c in chunks]), show_progress=False)

    def search(self, query: str, k: int = 5) -> list[tuple[dict, float]]:
        toks = tokenize([query])
        if not toks or not toks[0]:
            return []
        try:
            idx, scores = self.model.retrieve(toks, k=min(k, len(self.chunks)), show_progress=False, n_threads=1)
        except Exception:  # every query term out of vocabulary  # noqa: BLE001
            return []
        return [(self.chunks[int(i)], float(s)) for i, s in zip(idx[0], scores[0]) if s > 0]


def probe(question: str, k: int = 5, index_root: Path = INDEX_DIR, version: str | None = None) -> list[dict]:
    _, chunks, _ = load_version(index_root, version)
    return [{"rank": r, "score": round(s, 3), "source_type": c["source_type"], "doc_url": c["doc_url"], "id": c["id"]}
            for r, (c, s) in enumerate(BM25(chunks).search(question, k), start=1)]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="BM25 top-k over the active index")
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--version", default=None, help="an index version (default: CURRENT)")
    ap.add_argument("--index-dir", type=Path, default=INDEX_DIR)
    args = ap.parse_args(argv)
    for hit in probe(args.question, args.k, args.index_dir, args.version):
        print(f"{hit['rank']}. {hit['score']:>7.3f}  {hit['source_type']:<10} {hit['doc_url']}  {hit['id']}")


if __name__ == "__main__":
    main()
