"""Retriever used by the benchmark, the answer probe and the API.

BM25 (bm25s + Snowball stemmer), dense (fastembed ONNX, cosine on normalised
vectors held in a numpy matrix), hybrid via reciprocal rank fusion (k=60) and
an optional fastembed cross-encoder rerank of the fused top-N.
"""

from __future__ import annotations

import hashlib
import time

import bm25s
import numpy as np
import Stemmer

from common.config import INDEX_DIR, MODEL_DIR

QUERY_PREFIX = {  # instruction prefixes recommended by the model authors for short queries
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-m": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-s": "Represent this sentence for searching relevant passages: ",
}
RRF_K = 60

_stemmer = Stemmer.Stemmer("english")


def emb_cache_path(model_name: str, texts: list[str]):
    """Embeddings are cached by model + exact chunk texts, so re-chunking never reuses stale vectors."""
    key = hashlib.sha256(("\x00".join(texts) + model_name).encode()).hexdigest()[:16]
    return INDEX_DIR / f"emb-{model_name.replace('/', '_')}-{key}.npy"


def _tok(texts: list[str]) -> list[list[str]]:
    return bm25s.tokenize(texts, stopwords="en", stemmer=_stemmer, return_ids=False, show_progress=False)


class BM25Index:
    def __init__(self, texts: list[str]):
        t0 = time.perf_counter()
        self.model = bm25s.BM25()
        self.model.index(_tok(texts), show_progress=False)
        self.build_s = time.perf_counter() - t0
        self.n = len(texts)

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        toks = _tok([query])
        if not toks[0]:
            return []
        try:
            idx, scores = self.model.retrieve(toks, k=min(k, self.n), show_progress=False, n_threads=1)
        except Exception:  # every query term out of vocabulary
            return []
        return [(int(i), float(s)) for i, s in zip(idx[0], scores[0]) if s > 0]


class DenseIndex:
    def __init__(self, model_name: str, texts: list[str], threads: int | None = None, cache: bool = True):
        from fastembed import TextEmbedding

        t0 = time.perf_counter()
        self.model = TextEmbedding(model_name, cache_dir=str(MODEL_DIR), threads=threads)
        self.load_s = time.perf_counter() - t0
        self.name = model_name
        self.prefix = QUERY_PREFIX.get(model_name, "")
        path = emb_cache_path(model_name, texts)
        self.embed_s = None
        if cache and path.exists():
            self.matrix = np.load(path)
        else:
            t1 = time.perf_counter()
            self.matrix = self.embed_passages(texts)
            self.embed_s = time.perf_counter() - t1
            if cache:
                INDEX_DIR.mkdir(parents=True, exist_ok=True)
                np.save(path, self.matrix)

    def embed_passages(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        # length-sorted batches waste less compute on padding; results are put back in input order
        order = np.argsort([len(t) for t in texts], kind="stable")
        vecs = np.asarray(list(self.model.passage_embed([texts[i] for i in order], batch_size=batch_size)),
                          dtype=np.float32)
        out = np.empty_like(vecs)
        out[order] = vecs
        return out / np.linalg.norm(out, axis=1, keepdims=True)

    def embed_query(self, query: str) -> np.ndarray:
        v = np.asarray(next(iter(self.model.query_embed(self.prefix + query))), dtype=np.float32)
        return v / np.linalg.norm(v)

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        q = self.embed_query(query)
        sims = self.matrix @ q
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(i), float(sims[i])) for i in top]


class Reranker:
    def __init__(self, model_name: str, threads: int | None = None):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        t0 = time.perf_counter()
        self.model = TextCrossEncoder(model_name, cache_dir=str(MODEL_DIR), threads=threads)
        self.load_s = time.perf_counter() - t0
        self.name = model_name

    def rerank(self, query: str, docs: list[str]) -> list[float]:
        return [float(s) for s in self.model.rerank(query, docs, batch_size=32)]


def rrf(*ranked_lists: list[tuple[int, float]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, (idx, _) in enumerate(lst, start=1):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])


class Retriever:
    """mode: bm25 | dense | hybrid; reranker optional (applied to the fused top `rerank_n`)."""

    def __init__(self, chunks: list[dict], dense_model: str | None = None, reranker_model: str | None = None,
                 threads: int | None = None, fuse_n: int = 50, rerank_n: int = 20):
        self.chunks = chunks
        texts = [c["text"] for c in chunks]
        self.bm25 = BM25Index(texts)
        self.dense = DenseIndex(dense_model, texts, threads=threads) if dense_model else None
        self.reranker = Reranker(reranker_model, threads=threads) if reranker_model else None
        self.fuse_n = fuse_n
        self.rerank_n = rerank_n

    def search(self, query: str, k: int = 10, mode: str = "hybrid", rerank: bool = True) -> tuple[list[dict], dict]:
        t: dict[str, float] = {}
        t0 = time.perf_counter()
        bm = self.bm25.search(query, self.fuse_n) if mode in ("bm25", "hybrid") else []
        t["bm25_ms"] = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        de = self.dense.search(query, self.fuse_n) if mode in ("dense", "hybrid") and self.dense else []
        t["dense_ms"] = (time.perf_counter() - t1) * 1000
        t2 = time.perf_counter()
        if mode == "bm25":
            ranked = bm
        elif mode == "dense":
            ranked = de
        else:
            ranked = rrf(bm, de)
        t["fuse_ms"] = (time.perf_counter() - t2) * 1000
        rerank_scores = None
        if rerank and self.reranker and ranked:
            t3 = time.perf_counter()
            cand = ranked[: self.rerank_n]
            scores = self.reranker.rerank(query, [self.chunks[i]["text"] for i, _ in cand])
            ranked = sorted(zip([i for i, _ in cand], scores), key=lambda kv: -kv[1])
            rerank_scores = True
            t["rerank_ms"] = (time.perf_counter() - t3) * 1000
        t["total_ms"] = (time.perf_counter() - t0) * 1000
        hits = []
        for i, s in ranked[:k]:
            c = self.chunks[i]
            hits.append({"idx": i, "score": s, "url": c["url"], "doc_url": c["doc_url"], "id": c["id"],
                         "rerank": rerank_scores is not None})
        return hits, t
