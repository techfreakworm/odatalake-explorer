"""Query-time latency under CPU budgets -> poc/results/latency_threads.json

    uv run python -I -m retrieval.latency --questions eval/seed.jsonl

Simulates small serving boxes by capping onnxruntime intra-op threads (2, 4)
against the default (all cores). Measures, per query: dense query embedding
(bge-small, bge-base), and cross-encoder rerank of the fused top-N candidates
(N = 10 / 20) with and without truncating passages to ~256 tokens of text.
Process RSS is recorded after each model loads.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import psutil

from common.config import INDEX_DIR, POC_DIR, RESULTS_DIR, read_jsonl, write_json
from eval.questions import load_questions
from retrieval.index import BM25Index, DenseIndex, Reranker, rrf


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1)


def timeit(fn, qs, repeat=2):
    fn(qs[0])  # warm-up
    out = []
    for _ in range(repeat):
        for q in qs:
            t0 = time.perf_counter()
            fn(q)
            out.append((time.perf_counter() - t0) * 1000)
    return {"p50": pct(out, 0.5), "p95": pct(out, 0.95), "n": len(out)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--threads", type=int, action="append")
    ap.add_argument("--n-queries", type=int, default=8)
    args = ap.parse_args()
    qs = [q["question"] for q in load_questions(args.questions)][: args.n_queries]
    chunks = read_jsonl(INDEX_DIR / f"chunks-{args.target}.jsonl")
    texts = [c["text"] for c in chunks]
    bm = BM25Index(texts)
    proc = psutil.Process()
    report = {"target": args.target, "n_queries": len(qs), "rss_mb_after_bm25": round(proc.memory_info().rss / 2**20),
              "by_threads": {}}
    for th in args.threads or [2, 4, 0]:
        threads = th or None
        label = str(th) if th else "default(all cores)"
        res: dict = {}
        small = DenseIndex("BAAI/bge-small-en-v1.5", texts, threads=threads)  # cached matrix from the bench
        res["rss_mb_after_bge_small"] = round(proc.memory_info().rss / 2**20)
        res["query_embed_bge_small_ms"] = timeit(lambda q: small.embed_query(q), qs)
        base = DenseIndex("BAAI/bge-base-en-v1.5", texts, threads=threads)
        res["query_embed_bge_base_ms"] = timeit(lambda q: base.embed_query(q), qs)
        cands = {q: [i for i, _ in rrf(bm.search(q, 50), small.search(q, 50))] for q in qs}
        for rname in ("Xenova/ms-marco-MiniLM-L-6-v2", "BAAI/bge-reranker-base"):
            rr = Reranker(rname, threads=threads)
            res[f"rss_mb_after_{rname.split('/')[-1]}"] = round(proc.memory_info().rss / 2**20)
            for n in (10, 20):
                res[f"rerank_{rname.split('/')[-1]}_top{n}_ms"] = timeit(
                    lambda q, n=n: rr.rerank(q, [texts[i] for i in cands[q][:n]]), qs, repeat=1)
            if "MiniLM" in rname:
                res[f"rerank_{rname.split('/')[-1]}_top20_trunc1000chars_ms"] = timeit(
                    lambda q: rr.rerank(q, [texts[i][:1000] for i in cands[q][:20]]), qs, repeat=1)
            del rr
        report["by_threads"][label] = res
        print(label, res, flush=True)
    write_json(RESULTS_DIR / "latency_threads.json", report)


if __name__ == "__main__":
    main()
