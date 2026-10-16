"""Fast scorer for any POST /ask endpoint -> poc/results/eval_run.json

    uv run python -I -m eval.score --url http://127.0.0.1:8000/ask --questions ../docs/eval-questions.md
    # judge: any OpenAI-compatible endpoint
    JUDGE_BASE_URL=... JUDGE_MODEL=... JUDGE_API_KEY=... uv run python -I -m eval.score ...

Implements the scoring method in docs/eval-questions.md:
  schema      HTTP 200 and exactly {"answer": non-empty str, "sources": [http(s) URL, ...]}
  abstain     sources empty, or the answer matches the don't-know pattern
  behaviour   unanswerable / out-of-scope / adversarial-without-sources must abstain;
              answerable / negative / false-premise / adversarial-with-sources must not
  source hit  any returned source equals any expected source after normalisation
  judge       per must-mention fact: stated or not (+ contradiction flag); each
              "BEHAVIOR:" item is a pass/fail behaviour check; "Script: sources
              non-empty" hints are also checked deterministically
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
from eval.questions import load_questions, must_abstain, normalize_url

IDK = re.compile(r"\b(i (do not|don't) know|not (covered|mentioned|documented|available) in|"
                 r"(docs|documentation|context|passages) (do|does) not (cover|mention|contain|say)|"
                 r"no information|can(not|'t) (help|answer)|unable to (find|answer)|outside (the )?scope|"
                 r"only (help|answer) (with )?(questions )?about olake)\b", re.I)

JUDGE_PROMPT = """You grade answers from a documentation assistant.
Input: the question, the assistant's answer, the list of source URLs it returned, required facts, and behaviour checks.
- For each required fact decide whether the answer states it. Paraphrases and equivalent values count; partial or vague mentions do not.
- For each behaviour check decide whether the answer (and its sources list) satisfies it.
- Flag whether the answer contradicts any required fact.
Reply with JSON only: {"covered": [true/false per fact, in order], "behavior_ok": [true/false per behaviour check, in order], "contradiction": true/false}"""


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


def is_abstain(body: dict, qtype: str = "") -> bool:
    """Sources empty, or the answer matches the don't-know pattern anywhere. Negative and
    false-premise rows are answer rows scored on their must-mention facts ("not supported ..."),
    so for them only an empty sources list counts as an abstain."""
    if not body.get("sources"):
        return True
    if qtype in ("negative", "false-premise"):
        return False
    return bool(IDK.search(body.get("answer", "")))


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1) if xs else None


async def ask_one(client: httpx.AsyncClient, url: str, q: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(url, json={"question": q["question"]}, headers={"X-Request-ID": f"eval-{q['id']}"})
            ms = (time.perf_counter() - t0) * 1000
            try:
                body = r.json()
            except json.JSONDecodeError:
                body = None
            dbg = {k: r.headers.get(f"x-ask-{k}") for k in ("reason", "rewrite", "gate-score", "debug")}
            return {"status": r.status_code, "ms": round(ms, 1), "body": body,
                    "server": {k: v for k, v in dbg.items() if v is not None}}
        except httpx.HTTPError as e:
            return {"status": None, "ms": round((time.perf_counter() - t0) * 1000, 1), "body": None, "error": repr(e)}


async def judge_one(judge: AsyncOpenAI, model: str, q: dict, body: dict, sem: asyncio.Semaphore) -> dict:
    facts, behav = q["must_mention"], q.get("behavior", [])
    user = json.dumps({"question": q["question"], "answer": body["answer"], "sources": body["sources"],
                       "required_facts": facts, "behaviour_checks": behav}, ensure_ascii=False)
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
        except Exception as e:  # noqa: BLE001
            return {"error": repr(e)[:200]}
    covered = [bool(x) for x in obj.get("covered", [])][: len(facts)]
    covered += [False] * (len(facts) - len(covered))
    bok = [bool(x) for x in obj.get("behavior_ok", [])][: len(behav)]
    bok += [False] * (len(behav) - len(bok))
    for i, b in enumerate(behav):  # deterministic script hint
        if re.search(r"script:[^.]*sources non-empty", b, re.I) and not body["sources"]:
            bok[i] = False
    out = {"covered": covered, "behavior_ok": bok, "contradiction": bool(obj.get("contradiction")),
           "judge_ms": round((time.perf_counter() - t0) * 1000)}
    if facts:
        out["coverage"] = round(sum(covered) / len(facts), 3)
    if behav:
        out["behavior_pass"] = all(bok)
    return out


def frac(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(bool(x) for x in xs) / len(xs), 3) if xs else None


async def run(args) -> dict:
    qs = load_questions(args.questions)
    if args.ids:
        keep = set(args.ids.split(","))
        qs = [q for q in qs if q["id"] in keep]
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        results = await asyncio.gather(*(ask_one(client, args.url, q, sem) for q in qs))
    ask_wall = time.perf_counter() - t0

    rows = []
    for q, res in zip(qs, results):
        body = res.get("body")
        ok, why = schema_ok(body) if res["status"] == 200 else (False, f"HTTP {res['status']}")
        abst = is_abstain(body, q["type"]) if ok else None
        exp = set(q["expected_norm"])
        hit = (any(normalize_url(s) in exp for s in body["sources"]) if ok and exp else None)
        should_abstain = must_abstain(q)
        correct = (abst is True) if should_abstain else bool(ok and abst is False)
        rows.append({"id": q["id"], "type": q["type"], "must_abstain": should_abstain, "status": res["status"],
                     "ms": res["ms"], "schema_ok": ok, "schema_error": why or None, "abstained": abst,
                     "source_hit": hit, "behaviour_correct": correct,
                     "sources": body.get("sources") if ok else None, "answer": body.get("answer") if ok else None,
                     "server": res.get("server") or None})

    judge_wall = 0.0
    if not args.no_judge:
        judge = AsyncOpenAI(base_url=os.environ.get("JUDGE_BASE_URL", LLM_BASE_URL),
                            api_key=os.environ.get("JUDGE_API_KEY", LLM_API_KEY), timeout=300)
        model = os.environ.get("JUDGE_MODEL", LLM_MODEL)
        jsem = asyncio.Semaphore(args.judge_concurrency)
        todo = [(q, r) for q, r in zip(qs, rows) if r["schema_ok"] and (q["must_mention"] or q.get("behavior"))]
        t1 = time.perf_counter()
        verdicts = await asyncio.gather(*(judge_one(judge, model, q, {"answer": r["answer"], "sources": r["sources"]},
                                                    jsem) for q, r in todo))
        judge_wall = time.perf_counter() - t1
        for (_, r), v in zip(todo, verdicts):
            r["judge"] = v

    def summarize(sub: list[dict]) -> dict:
        cov = [r["judge"]["coverage"] for r in sub if "coverage" in r.get("judge", {})]
        bp = [r["judge"]["behavior_pass"] for r in sub if "behavior_pass" in r.get("judge", {})]
        return {"n": len(sub), "schema_valid": frac([r["schema_ok"] for r in sub]),
                "behaviour_correct": frac([r["behaviour_correct"] for r in sub]),
                "source_hit": frac([r["source_hit"] for r in sub]),
                "fact_coverage_mean": round(sum(cov) / len(cov), 3) if cov else None,
                "judged_behavior_pass": frac(bp),
                "contradictions": sum(1 for r in sub if r.get("judge", {}).get("contradiction"))}

    by_type = {t: summarize([r for r in rows if r["type"] == t]) for t in sorted({r["type"] for r in rows})}
    lat = [r["ms"] for r in rows if r["status"] == 200]
    abst_rows = [r for r in rows if r["type"] in ("unanswerable", "out-of-scope")]
    ans_rows = [r for r in rows if r["type"] == "answerable"]
    summary = summarize(rows)
    reasons: dict[str, int] = {}
    for r in rows:
        if r.get("server") and r["server"].get("reason"):
            reasons[r["server"]["reason"]] = reasons.get(r["server"]["reason"], 0) + 1
    if reasons:
        summary["server_reasons"] = reasons
        summary["rewrite_fired"] = sum(1 for r in rows if (r.get("server") or {}).get("rewrite") == "1")
    must_answer = [r for r in rows if not r["must_abstain"]]
    summary["false_abstain_rate_all_must_answer"] = frac([r["abstained"] for r in must_answer])
    summary.update({
        "abstain_recall_unanswerable_out_of_scope": frac([r["abstained"] for r in abst_rows]),
        "false_abstain_rate_answerable": frac([r["abstained"] for r in ans_rows]),
        "http_5xx": sum(1 for r in rows if (r["status"] or 0) >= 500),
        "latency_ms": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "max": max(lat) if lat else None},
        "ask_wall_s": round(ask_wall, 1),
        "judge_wall_s": round(judge_wall, 1),
        "total_wall_s": round(ask_wall + judge_wall, 1),
    })
    return {"endpoint": args.url, "questions": {"file": Path(args.questions).name, "n": len(qs)},
            "concurrency": args.concurrency, "judge_model": None if args.no_judge else os.environ.get("JUDGE_MODEL", LLM_MODEL),
            "summary": summary, "by_type": by_type, "per_question": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/ask")
    ap.add_argument("--questions", default=str(POC_DIR / "eval" / "seed.jsonl"))
    ap.add_argument("--ids", default="", help="comma-separated subset of question ids")
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
