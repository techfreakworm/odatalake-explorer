"""Retrieval benchmark -> poc/results/retrieval.json

    uv run python -I -m retrieval.bench --questions eval/seed.jsonl \
        --target 300 --target 600 \
        --dense BAAI/bge-small-en-v1.5 --dense BAAI/bge-base-en-v1.5 \
        --reranker Xenova/ms-marco-MiniLM-L-6-v2 --reranker BAAI/bge-reranker-base

A hit is a retrieved chunk whose normalised URL (no #anchor, no ?query, no
trailing slash, GitHub blob ref removed) equals a normalised expected source.
hit@k and MRR@10 are computed over chunk ranks for questions that have
expected sources. Latency: each query runs --repeat times after one warm-up.
"""

from __future__ import annotations

import argparse
import copy
import os
import platform
import statistics
import time
from pathlib import Path

import numpy as np
import psutil

from common.config import INDEX_DIR, POC_DIR, RESULTS_DIR, read_jsonl, write_json
from eval.questions import load_questions, normalize_url
from retrieval.index import BM25Index, DenseIndex, Reranker, emb_cache_path, rrf

PROC = psutil.Process()


def rss_mb() -> float:
    return round(PROC.memory_info().rss / 2**20, 1)


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 2)


def first_hit_rank(urls: list[str], expected: set[str]) -> int | None:
    for r, u in enumerate(urls, start=1):
        if normalize_url(u) in expected:
            return r
    return None


def quality(per_q: dict[str, int | None]) -> dict:
    n = len(per_q)
    out = {"n": n}
    for k in (1, 3, 5, 10):
        out[f"hit@{k}"] = round(sum(1 for r in per_q.values() if r and r <= k) / n, 3) if n else None
    out["mrr@10"] = round(sum(1 / r for r in per_q.values() if r and r <= 10) / n, 3) if n else None
    return out


def wordpiece_lengths(dense: DenseIndex, texts: list[str]) -> list[int] | None:
    try:
        tok = copy.deepcopy(dense.model.model.tokenizer)
        tok.no_truncation()
        tok.no_padding()
        return [len(e.ids) for e in tok.encode_batch(texts)]
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--target", type=int, action="append")
    ap.add_argument("--dense", action="append")
    ap.add_argument("--reranker", action="append")
    ap.add_argument("--threads", type=int, default=None, help="onnxruntime intra-op threads (default: all cores)")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--fuse-n", type=int, default=50)
    ap.add_argument("--rerank-n", type=int, default=20)
    ap.add_argument("--chunks-suffix", default="", help="e.g. '-blog' to use chunks-<t>-blog.jsonl")
    ap.add_argument("--reuse-embeddings", action="store_true", help="load cached chunk embeddings if present")
    ap.add_argument("--config-filter", default="", help="only run configs whose name contains this substring")
    ap.add_argument("--out", default=str(RESULTS_DIR / "retrieval.json"))
    args = ap.parse_args()
    targets = args.target or [300, 600]
    dense_models = args.dense or ["BAAI/bge-small-en-v1.5"]
    rerankers = args.reranker or []

    qs = load_questions(args.questions)
    with_src = [q for q in qs if q["expected_norm"]]
    report: dict = {
        "machine": {"platform": platform.platform(), "processor": platform.processor(), "cpu_count": os.cpu_count(),
                    "onnx_threads": args.threads or "default (all cores)"},
        "questions": {"file": Path(args.questions).name, "n_total": len(qs), "n_with_sources": len(with_src)},
        "settings": {"fuse_n": args.fuse_n, "rerank_n": args.rerank_n, "rrf_k": 60, "repeat": args.repeat,
                     "hit_definition": "chunk-level rank of first chunk whose normalised URL is an expected source"},
        "rss_mb": {"start": rss_mb()},
        "rerankers": {},
        "per_target": {},
    }

    rr_models = {}
    for name in rerankers:
        r = Reranker(name, threads=args.threads)
        rr_models[name] = r
        report["rerankers"][name] = {"load_s": round(r.load_s, 2)}
        report["rss_mb"][f"after_reranker:{name}"] = rss_mb()

    for target in targets:
        chunks = read_jsonl(INDEX_DIR / f"chunks-{target}{args.chunks_suffix}.jsonl")
        texts = [c["text"] for c in chunks]
        tr: dict = {"chunks": len(chunks), "embedding": {}, "configs": {}}
        bm = BM25Index(texts)
        tr["bm25_build_s"] = round(bm.build_s, 3)
        report["rss_mb"][f"after_bm25:{target}"] = rss_mb()

        dense: dict[str, DenseIndex] = {}
        for name in dense_models:
            d = DenseIndex(name, texts[:2], threads=args.threads, cache=False)  # loads model + warms the session
            npy = emb_cache_path(name, texts)
            if args.reuse_embeddings and npy.exists() and np.load(npy, mmap_mode="r").shape[0] == len(texts):
                d.matrix = np.load(npy)  # timings come from the run that produced the file
                tr["embedding"][name] = {"reused_cached_matrix": True, "dim": int(d.matrix.shape[1])}
            else:
                t0 = time.perf_counter()
                d.embed_passages(texts[:50])
                t50 = time.perf_counter() - t0
                t0 = time.perf_counter()
                d.matrix = d.embed_passages(texts)
                tfull = time.perf_counter() - t0
                np.save(npy, d.matrix)
                wp = wordpiece_lengths(d, texts)
                tr["embedding"][name] = {
                    "load_s": round(d.load_s, 2),
                    "embed_50_chunks_s": round(t50, 2),
                    "embed_full_corpus_s": round(tfull, 2),
                    "chunks_per_s": round(len(texts) / tfull, 1),
                    "dim": int(d.matrix.shape[1]),
                    "matrix_mb": round(d.matrix.nbytes / 2**20, 2),
                    "wordpiece_tokens_p50": int(np.median(wp)) if wp else None,
                    "wordpiece_over_512": sum(1 for x in wp if x > 512) if wp else None,
                }
            dense[name] = d
            report["rss_mb"][f"after_dense:{name}:{target}"] = rss_mb()
            print(target, name, tr["embedding"][name], flush=True)

        configs = [("bm25", None, None)]
        configs += [(f"dense:{m}", m, None) for m in dense_models]
        configs += [(f"hybrid:{m}", m, None) for m in dense_models]
        configs += [(f"hybrid:{m}+rerank:{r}", m, r) for m in dense_models for r in rerankers]
        configs += [(f"bm25+rerank:{r}", None, r) for r in rerankers]

        if args.config_filter:
            configs = [c for c in configs if args.config_filter in c[0] or c[0] == "bm25"]
        for cname, dm, rm in configs:
            lat: dict[str, list[float]] = {"bm25_ms": [], "dense_ms": [], "fuse_ms": [], "rerank_ms": [], "total_ms": []}
            per_q: dict[str, int | None] = {}
            top_scores: dict[str, float] = {}
            for q in qs:
                for rep in range(args.repeat + 1):
                    t0 = time.perf_counter()
                    b = bm.search(q["question"], args.fuse_n) if (cname.startswith(("bm25", "hybrid"))) else []
                    t1 = time.perf_counter()
                    de = dense[dm].search(q["question"], args.fuse_n) if dm else []
                    t2 = time.perf_counter()
                    if cname.startswith("bm25"):
                        ranked = b
                    elif cname.startswith("dense"):
                        ranked = de
                    else:
                        ranked = rrf(b, de)
                    t3 = time.perf_counter()
                    if rm:
                        cand = ranked[: args.rerank_n]
                        scores = rr_models[rm].rerank(q["question"], [texts[i] for i, _ in cand])
                        ranked = sorted(zip([i for i, _ in cand], scores), key=lambda kv: -kv[1])
                    t4 = time.perf_counter()
                    if rep == 0:
                        continue  # warm-up
                    lat["bm25_ms"].append((t1 - t0) * 1000)
                    lat["dense_ms"].append((t2 - t1) * 1000)
                    lat["fuse_ms"].append((t3 - t2) * 1000)
                    if rm:
                        lat["rerank_ms"].append((t4 - t3) * 1000)
                    lat["total_ms"].append((t4 - t0) * 1000)
                urls = [chunks[i]["url"] for i, _ in ranked[:10]]
                if q["expected_norm"]:
                    per_q[q["id"]] = first_hit_rank(urls, set(q["expected_norm"]))
                if rm and ranked:
                    top_scores[q["id"]] = round(float(ranked[0][1]), 4)
            entry = {
                **quality(per_q),
                "latency_ms": {k: {"p50": pct(v, 0.5), "p95": pct(v, 0.95)} for k, v in lat.items() if v},
                "first_hit_rank": per_q,
            }
            if top_scores:
                entry["top_rerank_score"] = top_scores
            tr["configs"][cname] = entry
            print(target, cname, {k: entry[k] for k in ("hit@1", "hit@3", "hit@5", "hit@10", "mrr@10")},
                  entry["latency_ms"].get("total_ms"), flush=True)
        report["per_target"][str(target)] = tr
    report["rss_mb"]["end"] = rss_mb()
    write_json(Path(args.out), report)


if __name__ == "__main__":
    main()
