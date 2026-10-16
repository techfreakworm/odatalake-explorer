"""Retrieval benchmark -> poc/results/retrieval*.json

    uv run python -I -m retrieval.bench --questions ../docs/eval-questions.md --target 300 \
        --dense BAAI/bge-small-en-v1.5 \
        --reranker flashrank:ms-marco-TinyBERT-L-2-v2 --reranker Xenova/ms-marco-MiniLM-L-6-v2 \
        --reranker BAAI/bge-reranker-base --rerank-n 10 --rerank-n 20 \
        --blog-weight 1.0 --blog-weight 0.5 --repeat 1 --reuse-embeddings --out results/retrieval-v2.json

Configs per target: bm25, dense:<m>, hybrid:<m> (RRF k=60 over the top --fuse-n of each),
hybrid:<m>+rerank:<r>@<n> (cross-encoder over the fused top n), optionally
bm25+rerank:<r>@<n>, and with --blog-weight W, hybrid:<m>+blog@W (blog-tier chunks join
both indexes and their fused score is multiplied by W).

A hit is a retrieved chunk whose normalised URL (no #anchor, no ?query, no trailing slash,
GitHub blob ref removed) equals a normalised expected source. hit@k and MRR@10 use chunk
ranks over the rows that have expected sources; hit@6 = an expected source is among the
passages a 6-passage prompt would see. Latency: each query runs --repeat times after one
warm-up (repeat 0 = quality only).
"""

from __future__ import annotations

import argparse
import copy
import os
import platform
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import psutil

from common.config import INDEX_DIR, POC_DIR, RESULTS_DIR, read_jsonl, write_json
from eval.questions import load_questions, normalize_url
from retrieval.index import BM25Index, DenseIndex, Reranker, emb_cache_path, rrf

PROC = psutil.Process()
KS = (1, 3, 5, 6, 10)


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
    for k in KS:
        out[f"hit@{k}"] = round(sum(1 for r in per_q.values() if r and r <= k) / n, 3) if n else None
    out["mrr@10"] = round(sum(1 / r for r in per_q.values() if r and r <= 10) / n, 3) if n else None
    return out


def by_category(per_q: dict[str, int | None], cat: dict[str, str]) -> dict:
    groups: dict[str, dict] = defaultdict(dict)
    for qid, r in per_q.items():
        groups[cat[qid]][qid] = r
    return {c: {k: v for k, v in quality(g).items() if k in ("n", "hit@1", "hit@5", "hit@10", "mrr@10")}
            for c, g in sorted(groups.items())}


def wordpiece_lengths(dense: DenseIndex, texts: list[str]) -> list[int] | None:
    try:
        tok = copy.deepcopy(dense.model.model.tokenizer)
        tok.no_truncation()
        tok.no_padding()
        return [len(e.ids) for e in tok.encode_batch(texts)]
    except Exception:
        return None


def build_dense(name: str, texts: list[str], args, info: dict | None) -> DenseIndex:
    d = DenseIndex(name, texts[:2], threads=args.threads, cache=False)  # loads model + warms the session
    npy = emb_cache_path(name, texts)
    if args.reuse_embeddings and npy.exists() and np.load(npy, mmap_mode="r").shape[0] == len(texts):
        d.matrix = np.load(npy)
        if info is not None:
            info[name] = {"reused_cached_matrix": True, "dim": int(d.matrix.shape[1])}
        return d
    t0 = time.perf_counter()
    d.embed_passages(texts[:50])
    t50 = time.perf_counter() - t0
    t0 = time.perf_counter()
    d.matrix = d.embed_passages(texts)
    tfull = time.perf_counter() - t0
    np.save(npy, d.matrix)
    if info is not None:
        wp = wordpiece_lengths(d, texts)
        info[name] = {
            "load_s": round(d.load_s, 2), "embed_50_chunks_s": round(t50, 2), "embed_full_corpus_s": round(tfull, 2),
            "chunks_per_s": round(len(texts) / tfull, 1), "dim": int(d.matrix.shape[1]),
            "matrix_mb": round(d.matrix.nbytes / 2**20, 2),
            "wordpiece_tokens_p50": int(np.median(wp)) if wp else None,
            "wordpiece_over_512": sum(1 for x in wp if x > 512) if wp else None,
        }
    return d


def evaluate(qs: list[dict], rank_fn, urls_of, repeat: int, cat: dict[str, str]) -> dict:
    """rank_fn(question) -> (ranked [(idx, score)], {stage: ms}); urls_of(idx) -> citation URL."""
    lat: dict[str, list[float]] = defaultdict(list)
    per_q: dict[str, int | None] = {}
    top_scores: dict[str, float] = {}
    for q in qs:
        for rep in range(repeat + 1):
            ranked, t = rank_fn(q["question"])
            if rep == 0 and repeat > 0:
                continue  # warm-up
            for k, v in t.items():
                lat[k].append(v)
        if q["expected_norm"]:
            per_q[q["id"]] = first_hit_rank([urls_of(i) for i, _ in ranked[:10]], set(q["expected_norm"]))
        if ranked:
            top_scores[q["id"]] = round(float(ranked[0][1]), 4)
    return {**quality(per_q), "by_category": by_category(per_q, cat),
            "latency_ms": {k: {"p50": pct(v, 0.5), "p95": pct(v, 0.95)} for k, v in lat.items()} if repeat else {},
            "first_hit_rank": per_q, "top_score": top_scores}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--target", type=int, action="append")
    ap.add_argument("--dense", action="append")
    ap.add_argument("--reranker", action="append")
    ap.add_argument("--rerank-n", type=int, action="append", help="cross-encoder depth(s) over the fused list")
    ap.add_argument("--rerank-bm25", action="store_true", help="also rerank BM25-only candidates")
    ap.add_argument("--blog-weight", type=float, action="append", help="hybrid + blog tier at this RRF weight")
    ap.add_argument("--threads", type=int, default=None, help="onnxruntime intra-op threads (default: all cores)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--fuse-n", type=int, default=50)
    ap.add_argument("--reuse-embeddings", action="store_true", help="load cached chunk embeddings if present")
    ap.add_argument("--out", default=str(RESULTS_DIR / "retrieval.json"))
    args = ap.parse_args()
    targets = args.target or [300]
    dense_models = args.dense or ["BAAI/bge-small-en-v1.5"]
    rerank_ns = args.rerank_n or [20]

    qs = load_questions(args.questions)
    cat = {q["id"]: q.get("category", "") for q in qs}
    report: dict = {
        "machine": {"platform": platform.platform(), "cpu_count": os.cpu_count(),
                    "onnx_threads": args.threads or "default (all cores)"},
        "questions": {"file": Path(args.questions).name, "n_total": len(qs),
                      "n_with_sources": sum(1 for q in qs if q["expected_norm"])},
        "settings": {"fuse_n": args.fuse_n, "rerank_n": rerank_ns, "rrf_k": 60, "repeat": args.repeat,
                     "hit_definition": "chunk-level rank of first chunk whose normalised URL is an expected source"},
        "rss_mb": {"start": rss_mb()},
        "rerankers": {},
        "per_target": {},
    }
    rr_models = {}
    for name in args.reranker or []:
        r = Reranker(name, threads=args.threads)
        rr_models[name] = r
        report["rerankers"][name] = {"load_s": round(r.load_s, 2)}
        report["rss_mb"][f"after_reranker:{name}"] = rss_mb()

    for target in targets:
        chunks = read_jsonl(INDEX_DIR / f"chunks-{target}.jsonl")
        texts = [c["text"] for c in chunks]
        tr: dict = {"chunks": len(chunks), "embedding": {}, "configs": {}}
        bm = BM25Index(texts)
        tr["bm25_build_s"] = round(bm.build_s, 3)
        dense = {m: build_dense(m, texts, args, tr["embedding"]) for m in dense_models}
        report["rss_mb"][f"after_indexes:{target}"] = rss_mb()

        def ranker(mode, dm=None, rm=None, n=None):
            def fn(question):
                t = {}
                t0 = time.perf_counter()
                b = bm.search(question, args.fuse_n) if mode in ("bm25", "hybrid") else []
                t["bm25_ms"] = (time.perf_counter() - t0) * 1000
                t1 = time.perf_counter()
                d = dense[dm].search(question, args.fuse_n) if dm else []
                t["dense_ms"] = (time.perf_counter() - t1) * 1000
                ranked = b if mode == "bm25" else d if mode == "dense" else rrf(b, d)
                if rm:
                    t2 = time.perf_counter()
                    cand = ranked[:n]
                    scores = rr_models[rm].rerank(question, [texts[i] for i, _ in cand])
                    ranked = sorted(zip([i for i, _ in cand], scores), key=lambda kv: -kv[1])
                    t["rerank_ms"] = (time.perf_counter() - t2) * 1000
                t["total_ms"] = (time.perf_counter() - t0) * 1000
                return ranked, t
            return fn

        configs = [("bm25", ranker("bm25"))]
        configs += [(f"dense:{m}", ranker("dense", m)) for m in dense_models]
        configs += [(f"hybrid:{m}", ranker("hybrid", m)) for m in dense_models]
        configs += [(f"hybrid:{m}+rerank:{r}@{n}", ranker("hybrid", m, r, n))
                    for m in dense_models for r in rr_models for n in rerank_ns]
        if args.rerank_bm25:
            configs += [(f"bm25+rerank:{r}@{n}", ranker("bm25", None, r, n)) for r in rr_models for n in rerank_ns]
        for cname, fn in configs:
            entry = evaluate(qs, fn, lambda i: chunks[i]["url"], args.repeat, cat)
            tr["configs"][cname] = entry
            print(target, cname, {k: entry[k] for k in ("hit@1", "hit@5", "hit@6", "hit@10", "mrr@10")},
                  entry["latency_ms"].get("rerank_ms") or entry["latency_ms"].get("total_ms"), flush=True)

        if args.blog_weight:  # blog tier: separate chunks joining both indexes, fused score x weight
            blog = read_jsonl(INDEX_DIR / f"chunks-{target}-blogtier.jsonl")
            all_chunks = chunks + blog
            all_texts = texts + [c["text"] for c in blog]
            is_blog = np.array([False] * len(chunks) + [True] * len(blog))
            bm_all = BM25Index(all_texts)
            tr["blog_tier"] = {"blog_chunks": len(blog), "embedding": {}, "configs": {}}
            for m in dense_models:
                d_all = build_dense(m, all_texts, args, tr["blog_tier"]["embedding"])
                for w in args.blog_weight:
                    def fn(question, d_all=d_all, w=w):
                        t0 = time.perf_counter()
                        fused = rrf(bm_all.search(question, args.fuse_n), d_all.search(question, args.fuse_n))
                        fused = sorted(((i, s * (w if is_blog[i] else 1.0)) for i, s in fused), key=lambda kv: -kv[1])
                        return fused, {"total_ms": (time.perf_counter() - t0) * 1000}
                    entry = evaluate(qs, fn, lambda i: all_chunks[i]["url"], args.repeat, cat)
                    in_top6 = [sum(1 for i, _ in fn(q["question"])[0][:6] if is_blog[i]) for q in qs]
                    entry["blog_chunks_in_top6_mean"] = round(float(np.mean(in_top6)), 2)
                    tr["blog_tier"]["configs"][f"hybrid:{m}+blog@{w}"] = entry
                    print(target, f"hybrid:{m}+blog@{w}", {k: entry[k] for k in ("hit@1", "hit@5", "hit@6", "hit@10", "mrr@10")},
                          "blog chunks in top 6:", entry["blog_chunks_in_top6_mean"], flush=True)
        report["per_target"][str(target)] = tr
    report["rss_mb"]["end"] = rss_mb()
    write_json(Path(args.out), report)


if __name__ == "__main__":
    main()
