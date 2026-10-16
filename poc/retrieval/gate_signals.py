"""Compare cheap off-topic gate signals -> poc/results/gate-signals.json

    uv run python -I -m retrieval.gate_signals --questions ../docs/eval-questions.md

Signals per question (hybrid bge-small retrieval, no reranker in the ranking path):
  dense_max_cos   top cosine of the query against all chunk vectors (free: already computed)
  bm25_max        top BM25 score (free)
  minilm_top@N    top Xenova/ms-marco-MiniLM-L-6-v2 score over the fused top N
  tinybert_top@N  top FlashRank ms-marco-TinyBERT-L-2-v2 score over the fused top N
Rows: must-abstain = unanswerable + out-of-scope (+ adversarial without sources);
must-answer = everything else. For each signal: the threshold that keeps 0 false abstains
(abstain iff score < threshold), the recall it reaches, the best balanced threshold, and ROC AUC.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from common.config import INDEX_DIR, POC_DIR, RESULTS_DIR, read_jsonl, write_json
from eval.questions import load_questions, must_abstain
from retrieval.index import BM25Index, DenseIndex, Reranker, rrf


def analyse(scores: dict[str, float], abstain_ids: set[str]) -> dict:
    pos = sorted(scores[i] for i in scores if i in abstain_ids)       # should abstain (want LOW scores)
    neg = sorted(scores[i] for i in scores if i not in abstain_ids)   # should answer
    lo_ans = neg[0]
    zero_fa_thr = lo_ans  # abstain iff score < lowest must-answer score
    recall0 = sum(1 for s in pos if s < zero_fa_thr) / len(pos)
    best = None
    cands = sorted(set(pos + neg))
    for t in [cands[0] - 1e-9] + [(a + b) / 2 for a, b in zip(cands, cands[1:])] + [cands[-1] + 1e-9]:
        rec = sum(1 for s in pos if s < t) / len(pos)
        far = sum(1 for s in neg if s < t) / len(neg)
        bal = (rec + 1 - far) / 2
        if best is None or (bal, -far) > (best["balanced_accuracy"], -best["false_abstain"]):
            best = {"threshold": round(t, 4), "recall": round(rec, 3), "false_abstain": round(far, 3),
                    "balanced_accuracy": round(bal, 3)}
    # ROC AUC: probability that a random must-abstain row scores below a random must-answer row
    auc = np.mean([[1.0 if p < n else 0.5 if p == n else 0.0 for n in neg] for p in pos])
    return {
        "zero_false_abstain": {"threshold": round(zero_fa_thr, 4), "recall": round(recall0, 3),
                               "abstained_ids": sorted(i for i in scores if i in abstain_ids and scores[i] < zero_fa_thr)},
        "best_balanced": best,
        "auc": round(float(auc), 3),
        "lowest_must_answer": sorted(((i, round(scores[i], 4)) for i in scores if i not in abstain_ids),
                                     key=lambda kv: kv[1])[:5],
        "highest_must_abstain": sorted(((i, round(scores[i], 4)) for i in scores if i in abstain_ids),
                                       key=lambda kv: -kv[1])[:5],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--dense", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--rerank-n", type=int, action="append")
    ap.add_argument("--out", default=str(RESULTS_DIR / "gate-signals.json"))
    args = ap.parse_args()
    ns = args.rerank_n or [10, 20]
    qs = load_questions(args.questions)
    abstain_ids = {q["id"] for q in qs if must_abstain(q)}
    chunks = read_jsonl(INDEX_DIR / f"chunks-{args.target}.jsonl")
    texts = [c["text"] for c in chunks]
    bm = BM25Index(texts)
    dense = DenseIndex(args.dense, texts)
    rr = {"minilm": Reranker("Xenova/ms-marco-MiniLM-L-6-v2"), "tinybert": Reranker("flashrank:ms-marco-TinyBERT-L-2-v2")}
    signals: dict[str, dict[str, float]] = {}
    lat: dict[str, list[float]] = {}

    def put(name, qid, val, ms):
        signals.setdefault(name, {})[qid] = float(val)
        lat.setdefault(name, []).append(ms)

    for q in qs:
        t0 = time.perf_counter()
        b = bm.search(q["question"], 50)
        t1 = time.perf_counter()
        d = dense.search(q["question"], 50)
        t2 = time.perf_counter()
        put("bm25_max", q["id"], b[0][1] if b else 0.0, (t1 - t0) * 1000)
        put("dense_max_cos", q["id"], d[0][1] if d else 0.0, (t2 - t1) * 1000)
        fused = [i for i, _ in rrf(b, d)]
        for name, model in rr.items():
            for n in ns:
                t3 = time.perf_counter()
                s = model.rerank(q["question"], [texts[i] for i in fused[:n]])
                put(f"{name}_top@{n}", q["id"], max(s) if s else -99.0, (time.perf_counter() - t3) * 1000)
    out = {
        "questions": {"file": Path(args.questions).name, "n": len(qs), "must_abstain": len(abstain_ids),
                      "must_answer": len(qs) - len(abstain_ids)},
        "retrieval": {"chunks": f"chunks-{args.target}.jsonl", "dense": args.dense, "fusion": "RRF k=60, top 50 each"},
        "signals": {name: {**analyse(vals, abstain_ids),
                           "latency_ms_p50": round(float(np.median(lat[name])), 2)} for name, vals in signals.items()},
        "per_question": {q["id"]: {"type": q["type"], "must_abstain": q["id"] in abstain_ids,
                                   **{name: round(vals[q["id"]], 4) for name, vals in signals.items()}} for q in qs},
    }
    write_json(Path(args.out), out)
    for name, a in out["signals"].items():
        print(f"{name:18s} AUC {a['auc']:.3f} | 0-FA threshold {a['zero_false_abstain']['threshold']:>9} recall "
              f"{a['zero_false_abstain']['recall']:.2f} | best balanced {a['best_balanced']} | p50 {a['latency_ms_p50']} ms")


if __name__ == "__main__":
    main()
