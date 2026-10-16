"""Gate + one-rewrite (CRAG-lite) policy, measured without generation -> poc/results/gate-rewrite.json

    uv run python -I -m answer.rewrite_probe --questions ../docs/eval-questions.md

Every question is rewritten once (LLM, reasoning off) into search keywords or NONE, and both the
original and the rewritten query are scored with each gate signal. The policy
    score(q) >= T                                  -> generate
    score(q) <  T: rewrite; NONE or score(rw) < T  -> decline, else generate on the rewrite's passages
is then evaluated offline for a sweep of thresholds T per signal: abstain recall on the
must-abstain rows, false declines on must-answer rows, and how often the rewrite fires.
The model's own answerable/citation check runs after this stage and is measured by the /ask run.
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from answer.pipeline import AskPipeline
from common.config import RESULTS_DIR, write_json
from eval.questions import load_questions, must_abstain
from retrieval.index import Reranker


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--out", default=str(RESULTS_DIR / "gate-rewrite.json"))
    ap.add_argument("--rewrite-version", default="v1", choices=["v1", "v2"])
    ap.add_argument("--ids", default="", help="comma-separated subset of question ids")
    args = ap.parse_args()
    qs = load_questions(args.questions)
    if args.ids:
        qs = [q for q in qs if q["id"] in set(args.ids.split(","))]
    pipe = AskPipeline(target=300, dense_model="BAAI/bge-small-en-v1.5", reranker_model=None, gate_signal="dense_max_cos",
                       rewrite_version=args.rewrite_version)
    tiny = Reranker("flashrank:ms-marco-TinyBERT-L-2-v2")

    def scores(query: str) -> dict:
        hits, _, cos = pipe.retrieve(query)
        cand = [pipe.chunks[h["idx"]]["text"] for h in hits[:10]]
        return {"dense_max_cos": cos, "tinybert_top@10": max(tiny.rerank(query, cand)) if cand else 0.0}

    pipe.client.chat.completions.create(model=pipe.model, max_tokens=5, reasoning_effort="none",
                                        messages=[{"role": "user", "content": "Reply OK."}])  # warm the model
    rows = []
    t_run = time.perf_counter()
    for q in qs:
        s0 = scores(q["question"])
        rw, usage = pipe.rewrite_query(q["question"])
        is_none = rw.strip().upper().startswith("NONE") or not rw.strip()
        s1 = scores(rw) if not is_none else None
        rows.append({"id": q["id"], "type": q["type"], "must_abstain": must_abstain(q), "rewrite": rw[:200],
                     "rewrite_none": is_none, "score": s0, "score_after_rewrite": s1, **usage})
        print(q["id"], q["type"], "NONE" if is_none else rw[:70], s0, s1, usage.get("rewrite_ms"), flush=True)
    wall = time.perf_counter() - t_run

    sweeps = {"dense_max_cos": [0.68, 0.69, 0.70, 0.71, 0.72, 0.73, 0.74, 0.75, 0.76, 0.78, 0.80],
              "tinybert_top@10": [0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]}
    must = [r for r in rows if r["must_abstain"]]
    answer = [r for r in rows if not r["must_abstain"]]
    results = {}
    for sig, ts in sweeps.items():
        res = []
        for t in ts:
            def declined(r, t=t, sig=sig):
                if r["score"][sig] >= t:
                    return False
                if r["rewrite_none"]:
                    return True
                return r["score_after_rewrite"][sig] < t
            fired = sum(1 for r in rows if r["score"][sig] < t)
            gate_only_fa = sum(1 for r in answer if r["score"][sig] < t)
            res.append({
                "threshold": t,
                "rewrite_fires": fired, "rewrite_fire_rate": round(fired / len(rows), 3),
                "abstain_recall": round(sum(declined(r) for r in must) / len(must), 3),
                "false_declines": sum(declined(r) for r in answer),
                "false_decline_ids": [r["id"] for r in answer if declined(r)],
                "missed_abstain_ids": [r["id"] for r in must if not declined(r)],
                "gate_only_recall": round(sum(1 for r in must if r["score"][sig] < t) / len(must), 3),
                "gate_only_false_declines": gate_only_fa,
            })
        results[sig] = res
    lat = [r["rewrite_ms"] for r in rows]
    report = {
        "questions": {"file": Path(args.questions).name, "n": len(qs), "must_abstain": len(must), "must_answer": len(answer)},
        "setup": {"retrieval": "hybrid bge-small, no reranker", "rewrite_llm": f"{pipe.model} reasoning_effort=none, max_tokens 64",
                  "policy": "score >= T -> generate; else rewrite once; NONE or rewritten score < T -> decline"},
        "rewrite_cost": {"latency_ms_p50": round(statistics.median(lat), 1), "latency_ms_p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))], 1),
                         "prompt_tokens_mean": round(statistics.mean(r["rewrite_prompt_tokens"] or 0 for r in rows), 1),
                         "completion_tokens_mean": round(statistics.mean(r["rewrite_completion_tokens"] or 0 for r in rows), 1),
                         "none_outputs": {"must_abstain": sum(r["rewrite_none"] for r in must),
                                          "must_answer": sum(r["rewrite_none"] for r in answer)}},
        "run_wall_s": round(wall, 1),
        "sweep": results,
        "per_question": rows,
    }
    write_json(Path(args.out), report)
    for sig, res in results.items():
        for x in res:
            print(sig, x["threshold"], "fires", x["rewrite_fires"], "recall", x["abstain_recall"], "false declines",
                  x["false_declines"], x["false_decline_ids"], "| gate-only recall", x["gate_only_recall"], "FA", x["gate_only_false_declines"])
    print(report["rewrite_cost"])


if __name__ == "__main__":
    main()
