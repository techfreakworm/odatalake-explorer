"""Fast scorer for any POST /ask endpoint -> poc/results/eval_run.json

    uv run python -I -m eval.score --url http://127.0.0.1:8000/ask --questions eval/seed.jsonl
    # judge: any OpenAI-compatible endpoint
    JUDGE_BASE_URL=... JUDGE_MODEL=... JUDGE_API_KEY=... uv run python -I -m eval.score ...

Reports: schema validity (exactly {"answer": str, "sources": [str]}), source hit
rate (normalised URL match), abstain correctness by question type, latency
p50/p95, and an LLM-as-judge fact-coverage score over the must-mention facts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from common.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, POC_DIR, RESULTS_DIR, write_json
from eval.questions import ABSTAIN_TYPES, load_questions, normalize_url

IDK = re.compile(r"\b(i (do not|don't) know|not (covered|mentioned|documented|available) in|"
                 r"(docs|documentation|context|passages) (do|does) not (cover|mention|contain|say)|"
                 r"no information|can(not|'t) (help|answer)|unable to (find|answer)|outside (the )?scope|"
                 r"only (help|answer) (with )?(questions )?about olake)\b", re.I)

JUDGE_PROMPT = """You grade answers from a documentation assistant. Given a question, the assistant's answer and a list of required facts, decide for each fact whether the answer states it (paraphrase and equivalent values count; partial or vague mentions do not). Also flag whether the answer contradicts any required fact.
Reply with JSON only: {"covered": [true/false for each fact, in order], "contradiction": true/false}"""


def schema_ok(body) -> tuple[bool, str]:
    if not isinstance(body, dict):
        return False, "not an object"
    if set(body) != {"answer", "sources"}:
        return False, f"keys {sorted(body)}"
    if not isinstance(body["answer"], str) or not body["answer"].strip():
        return False, "answer not a non-empty string"
    if not isinstance(body["sources"], list) or not all(isinstance(s, str) for s in body["sources"]):
        return False, "sources not a list of strings"
    if not all(re.match(r"https?://", s) for s in body["sources"]):
        return False, "source is not an http(s) URL"
    return True, ""


def is_abstain(body: dict) -> bool:
    """No sources, or the answer opens with an "I don't know"-style sentence (a caveat later in a
    sourced answer does not count)."""
    return not body.get("sources") or bool(IDK.search(body.get("answer", "")[:160]))


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1) if xs else None


async def ask_one(client: httpx.AsyncClient, url: str, q: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(url, json={"question": q["question"]})
            ms = (time.perf_counter() - t0) * 1000
            try:
                body = r.json()
            except json.JSONDecodeError:
                body = None
            return {"status": r.status_code, "ms": round(ms, 1), "body": body}
        except httpx.HTTPError as e:
            return {"status": None, "ms": round((time.perf_counter() - t0) * 1000, 1), "body": None, "error": repr(e)}


async def judge_one(judge: AsyncOpenAI, model: str, q: dict, answer: str, sem: asyncio.Semaphore) -> dict:
    facts = q["must_mention"]
    user = json.dumps({"question": q["question"], "answer": answer, "required_facts": facts}, ensure_ascii=False)
    # ollama's OpenAI endpoint ignores "/no_think"; reasoning_effort="none" is what turns qwen3 thinking off
    effort = os.environ.get("JUDGE_REASONING_EFFORT", "none" if "qwen3" in model else "")
    extra = {"reasoning_effort": effort} if effort else {}
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await judge.chat.completions.create(
                model=model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": user}], **extra)
            text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S)
            obj = json.loads(text[text.find("{"): text.rfind("}") + 1])
            covered = [bool(x) for x in obj.get("covered", [])][: len(facts)]
            covered += [False] * (len(facts) - len(covered))
            return {"covered": covered, "coverage": round(sum(covered) / len(facts), 3),
                    "contradiction": bool(obj.get("contradiction")), "judge_ms": round((time.perf_counter() - t0) * 1000)}
        except Exception as e:  # noqa: BLE001
            return {"error": repr(e)[:200]}


async def run(args) -> dict:
    qs = load_questions(args.questions)
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        results = await asyncio.gather(*(ask_one(client, args.url, q, sem) for q in qs))
    ask_wall = time.perf_counter() - t0

    rows = []
    for q, res in zip(qs, results):
        body = res.get("body")
        ok, why = schema_ok(body) if res["status"] == 200 else (False, f"HTTP {res['status']}")
        abst = is_abstain(body) if ok else None
        exp = set(q["expected_norm"])
        hit = (any(normalize_url(s) in exp for s in body["sources"]) if ok and exp else None)
        if q["type"] in ABSTAIN_TYPES:
            correct = abst is True
        elif q["type"] in ("answerable", "negative"):
            correct = ok and not abst
        else:  # false-premise: decided by the judge (premise corrected) below
            correct = None
        rows.append({"id": q["id"], "type": q["type"], "status": res["status"], "ms": res["ms"], "schema_ok": ok,
                     "schema_error": why or None, "abstained": abst, "source_hit": hit, "abstain_correct": correct,
                     "sources": body.get("sources") if ok else None,
                     "answer": (body.get("answer") if ok else None)})

    judge_wall = 0.0
    if not args.no_judge:
        judge = AsyncOpenAI(base_url=os.environ.get("JUDGE_BASE_URL", LLM_BASE_URL),
                            api_key=os.environ.get("JUDGE_API_KEY", LLM_API_KEY), timeout=300)
        model = os.environ.get("JUDGE_MODEL", LLM_MODEL)
        jsem = asyncio.Semaphore(args.judge_concurrency)
        todo = [(q, r) for q, r in zip(qs, rows) if r["schema_ok"] and q["must_mention"]]
        t1 = time.perf_counter()
        verdicts = await asyncio.gather(*(judge_one(judge, model, q, r["answer"], jsem) for q, r in todo))
        judge_wall = time.perf_counter() - t1
        for (q, r), v in zip(todo, verdicts):
            r["judge"] = v
            if q["type"] == "false-premise" and "coverage" in v:
                r["abstain_correct"] = v["coverage"] >= 0.5 and not v["contradiction"]

    def frac(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(bool(x) for x in xs) / len(xs), 3) if xs else None

    by_type = {}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        cov = [r["judge"]["coverage"] for r in sub if "judge" in r and "coverage" in r["judge"]]
        by_type[t] = {"n": len(sub), "behaviour_correct": frac([r["abstain_correct"] for r in sub]),
                      "source_hit": frac([r["source_hit"] for r in sub]),
                      "fact_coverage_mean": round(sum(cov) / len(cov), 3) if cov else None}
    cov_all = [r["judge"]["coverage"] for r in rows if "judge" in r and "coverage" in r["judge"]]
    lat = [r["ms"] for r in rows if r["status"] == 200]
    return {
        "endpoint": args.url,
        "questions": {"file": Path(args.questions).name, "n": len(qs)},
        "concurrency": args.concurrency,
        "summary": {
            "schema_valid": frac([r["schema_ok"] for r in rows]),
            "source_hit_rate": frac([r["source_hit"] for r in rows]),
            "behaviour_correct": frac([r["abstain_correct"] for r in rows]),
            "fact_coverage_mean": round(sum(cov_all) / len(cov_all), 3) if cov_all else None,
            "latency_ms": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "max": max(lat) if lat else None},
            "ask_wall_s": round(ask_wall, 1),
            "judge_wall_s": round(judge_wall, 1),
            "total_wall_s": round(ask_wall + judge_wall, 1),
        },
        "by_type": by_type,
        "per_question": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/ask")
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--judge-concurrency", type=int, default=2)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", default=str(RESULTS_DIR / "eval_run.json"))
    args = ap.parse_args()
    report = asyncio.run(run(args))
    write_json(Path(args.out), report)
    print(json.dumps({"summary": report["summary"], "by_type": report["by_type"]}, indent=1))


if __name__ == "__main__":
    main()
