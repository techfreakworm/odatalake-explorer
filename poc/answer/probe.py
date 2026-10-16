"""Answer + abstain probe -> poc/results/answer.json

    uv run python -I -m answer.probe --questions eval/seed.jsonl [--think-probe]

Every question is generated (even when the gate would abstain) so that both
abstain policies are evaluated on the same outputs:
  (a) gate:  abstain if top reranker score < threshold (tuned here on the set)
  (b) model: abstain if answerable=false or no valid citation
Should-abstain types: out-of-scope, unanswerable, adversarial. False-premise
rows are reported separately (correcting the premise with a citation is fine).
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from answer.pipeline import AskPipeline
from common.config import LLM_MODEL, POC_DIR, RESULTS_DIR, write_json
from eval.questions import ABSTAIN_TYPES, load_questions, normalize_url

ANSWER_TYPES = {"answerable", "negative"}


def pct(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1) if xs else None


def abstain_metrics(rows: list[dict], decide) -> dict:
    should = [r for r in rows if r["type"] in ABSTAIN_TYPES]
    answer = [r for r in rows if r["type"] in ANSWER_TYPES]
    abst = [r for r in rows if r["type"] in ABSTAIN_TYPES | ANSWER_TYPES and decide(r)]
    tp = sum(1 for r in abst if r["type"] in ABSTAIN_TYPES)
    return {
        "abstained": len(abst),
        "precision": round(tp / len(abst), 3) if abst else None,
        "recall": round(tp / len(should), 3) if should else None,
        "false_abstain_rate": round(sum(1 for r in answer if decide(r)) / len(answer), 3) if answer else None,
        "n_should_abstain": len(should),
        "n_should_answer": len(answer),
    }


def tune_gate(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["top_score"] is not None and r["type"] in ABSTAIN_TYPES | ANSWER_TYPES]
    cands = sorted({r["top_score"] for r in scored})
    thresholds = [cands[0] - 1] + [(a + b) / 2 for a, b in zip(cands, cands[1:])] + [cands[-1] + 1]
    best = None
    for t in thresholds:
        m = abstain_metrics(scored, lambda r, t=t: r["top_score"] < t)
        recall = m["recall"] or 0.0
        far = m["false_abstain_rate"] or 0.0
        bal = (recall + (1 - far)) / 2  # balanced accuracy; ties -> fewer false abstains
        key = (round(bal, 6), -far)
        if best is None or key > best[0]:
            best = (key, t, m)
    return {"threshold": round(best[1], 4), "balanced_accuracy": best[0][0], **best[2]}


def think_probe(pipe: AskPipeline, question: str) -> dict:
    out = {}
    hits, _ = pipe.retriever.search(question, k=10)
    from answer.pipeline import build_context
    context, _ = build_context(pipe.chunks, hits, pipe.max_passages)
    import uuid
    for mode in ("default", "no_think_tag", "think_false", "reasoning_none"):
        pipe.think_mode = mode
        try:
            raw, t, usage = pipe.generate(question, context, nonce=uuid.uuid4().hex)
            out[mode] = {**t, **usage, "has_think_tag": "<think>" in raw, "output_chars": len(raw)}
        except Exception as e:  # noqa: BLE001
            out[mode] = {"error": repr(e)[:300]}
        print("think-probe", mode, out[mode], flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--dense", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--reranker", default="Xenova/ms-marco-MiniLM-L-6-v2")
    ap.add_argument("--max-passages", type=int, default=6)
    ap.add_argument("--think-mode", default="reasoning_none",
                    help="default | no_think_tag (/no_think) | think_false (extra_body think=false) | reasoning_none")
    ap.add_argument("--think-probe", action="store_true")
    ap.add_argument("--out", default=str(RESULTS_DIR / "answer.json"))
    args = ap.parse_args()

    qs = load_questions(args.questions)
    pipe = AskPipeline(target=args.target, dense_model=args.dense, reranker_model=args.reranker,
                       max_passages=args.max_passages, think_mode=args.think_mode)
    report: dict = {
        "llm": {"model": LLM_MODEL, "endpoint": "ollama OpenAI-compatible /v1", "temperature": 0,
                "response_format": "json_object", "think_mode": args.think_mode},
        "retrieval": {"target": args.target, "dense": args.dense, "reranker": args.reranker,
                      "max_passages": args.max_passages},
        "questions": {"file": Path(args.questions).name, "n": len(qs)},
    }
    t0 = time.perf_counter()  # load the model into memory so the first measured call is warm
    pipe.client.chat.completions.create(model=pipe.model, max_tokens=5,
                                        messages=[{"role": "user", "content": "Reply OK. /no_think"}])
    report["llm"]["warmup_load_s"] = round(time.perf_counter() - t0, 1)
    if args.think_probe:
        report["think_probe"] = think_probe(pipe, qs[0]["question"])
        pipe.think_mode = args.think_mode

    rows = []
    t_run = time.perf_counter()
    for q in qs:
        res = pipe.ask(q["question"], force_generate=True)
        exp = set(q["expected_norm"])
        src_hit = any(normalize_url(u) in exp for u in res.sources) if exp else None
        row = {
            "id": q["id"], "type": q["type"], "question": q["question"],
            "top_score": None if res.top_score is None else round(res.top_score, 4),
            "model_answerable": res.model_answerable, "policy_b_abstain": res.abstained, "reason": res.reason,
            "sources": res.sources, "source_hit": src_hit, "answer": res.answer,
            "timings_ms": res.timings_ms, "usage": res.usage,
        }
        rows.append(row)
        print(q["id"], q["type"], row["reason"], row["top_score"], src_hit, res.timings_ms, res.usage, flush=True)
    report["run_wall_s"] = round(time.perf_counter() - t_run, 1)

    gate = tune_gate(rows)
    thr = gate["threshold"]
    report["policy_a_gate"] = gate
    report["policy_b_model"] = abstain_metrics(rows, lambda r: r["policy_b_abstain"])
    report["policy_a_or_b"] = abstain_metrics(rows, lambda r: r["policy_b_abstain"] or (r["top_score"] or -99) < thr)
    for r in rows:
        r["policy_a_abstain"] = (r["top_score"] if r["top_score"] is not None else -99) < thr
    by_type: dict[str, dict] = {}
    for r in rows:
        bt = by_type.setdefault(r["type"], {"n": 0, "policy_a_abstained": 0, "policy_b_abstained": 0, "source_hit": 0})
        bt["n"] += 1
        bt["policy_a_abstained"] += r["policy_a_abstain"]
        bt["policy_b_abstained"] += r["policy_b_abstain"]
        bt["source_hit"] += bool(r["source_hit"])
    report["by_type"] = by_type
    ans = [r for r in rows if r["type"] in ANSWER_TYPES]
    report["answered_source_hit_rate"] = round(sum(bool(r["source_hit"]) for r in ans) / len(ans), 3) if ans else None
    gen = [r for r in rows if r["timings_ms"].get("llm_total_ms")]
    report["latency_ms"] = {
        k: {"p50": pct([r["timings_ms"].get(k) for r in gen], 0.5), "p95": pct([r["timings_ms"].get(k) for r in gen], 0.95)}
        for k in ("retrieval_ms", "rerank_ms", "llm_ttft_ms", "llm_total_ms", "total_ms")
    }
    pt = [r["usage"].get("prompt_tokens") for r in gen if r["usage"].get("prompt_tokens")]
    ct = [r["usage"].get("completion_tokens") for r in gen if r["usage"].get("completion_tokens")]
    report["tokens_per_answer"] = {
        "prompt_mean": round(statistics.mean(pt), 1) if pt else None,
        "prompt_max": max(pt) if pt else None,
        "completion_mean": round(statistics.mean(ct), 1) if ct else None,
        "completion_max": max(ct) if ct else None,
        "tokenizer": "model-reported usage (qwen3 tokenizer via ollama)",
    }
    report["per_question"] = rows
    write_json(Path(args.out), report)
    print({k: report[k] for k in ("policy_a_gate", "policy_b_model", "policy_a_or_b", "latency_ms", "tokens_per_answer")})


if __name__ == "__main__":
    main()
