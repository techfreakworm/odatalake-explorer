"""Eval runner for any Ask OLake deployment (plan §4.5 D2; method: eval/questions.md "Scoring method").

    uv run python -m eval.run --base-url URL [--ids A,B] [--types t1,t2] [--limit N] [--concurrency 4]
        [--timeout 60] [--judge] [--judge-concurrency 1] [--retrieval-only] [--compare FILE] [--label TEXT]
        [--out eval/results/<name>.json]

Full run: POST {base}/ask per question with X-Request-ID: eval-<ID> and Cache-Control: no-cache; record status, body,
latency and the X-Ask-Reason / X-Ask-Gate-Score / X-Ask-Cache headers; then the deterministic checks:
  schema     HTTP 200 and exactly {"answer": non-empty str, "sources": [http(s) URL, ...]}
  contract   I2: 200 / 422 / 503 only, always exactly {"answer", "sources"}; 422 and 503 with sources []
  abstain    sources empty ("empty_sources"), or the answer matches the don't-know pattern ("pattern:<phrase>");
             negative and false-premise rows only count empty sources (their correct answers say "not supported")
  behaviour  by Type: unanswerable, out-of-scope and adversarial-without-sources must abstain; the rest must not
  source hit any returned source equals any expected source after normalize_url (lenient)
  canary     with CANARY set, any answer containing it fails the row (and the run)
  latency    p50 / p95 / max over the HTTP 200 responses
--judge adds the LLM judge (JUDGE_BASE_URL, JUDGE_API_KEY, JUDGE_MODEL, JUDGE_REASONING_EFFORT; temperature 0):
must-mention fact coverage, BEHAVIOR checks (AND-ed with their deterministic "Script:" hints) and contradictions.

--retrieval-only: POST {base}/debug/retrieve (a server started with DEBUG=1) for every row; hit@1/3/5/10 and MRR@10
over the 82 rows with expected sources (by the URL /ask would cite for each hit), overall and per category, each
row's first-hit rank and gate score, and the gate-calibration line. No LLM.

--compare FILE prints what changed against an earlier result of the same mode. Exit 1 on any contract failure or
canary leak.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from eval.questions import QUESTIONS_FILE, TYPES, load_questions, normalize_url

RESULTS_DIR = Path(__file__).resolve().parent / "results"
GATE_MARGIN = 0.02

# ----------------------------------------------------------------------------- deterministic checks
IDK = re.compile(
    r"\b(?:i (?:do not|don't) know"
    r"|not (?:covered|mentioned|documented|described|available) (?:in|by)"
    r"|(?:the )?(?:docs|documentation|context|passages|sources|pages) (?:do|does) not (?:cover|mention|contain|say|describe)"
    r"|(?:the )?(?:docs|documentation|context|passages|sources|pages) (?:don't|doesn't) (?:cover|mention|contain|say|describe)"
    r"|no information(?=\s*(?:[.!;]|$)| (?:about|on|in|regarding|for|is (?:available|provided|given)"
    r"|was (?:found|provided|given))\b)"
    r"|no (?:\w+ ){0,5}(?:is |are |was |were )?(?:mentioned|documented|specified|stated|given|listed) (?:in|by) "
    r"(?:the )?(?:provided |available |indexed |olake )?(?:passages|docs|documentation|context|sources|pages)"
    r"|can(?:not|'t) (?:help with|answer)"
    r"|(?:i|we) can(?:not|'t) help"
    r"|unable to (?:find|answer)"
    r"|i (?:could not|couldn't) find (?:this|that|it|anything|any information|information)"
    r"|outside (?:the )?scope"
    r"|only (?:help|answer) (?:with )?(?:questions )?about olake)\b",
    re.I,
)
SCRIPT_HINT = re.compile(r"script:\s*([^.]*)", re.I)
# The server's degraded 200 (contract I2: never a 429 or 5xx): the most relevant pages instead of an answer. It is
# neither a real answer nor a decline, so it counts as an abstain of kind "degraded:<reason>" and is never correct.
DEGRADED_REASONS = ("llm_failed", "ask_timeout", "queue_timeout", "rate_limited", "budget_exhausted")
DEGRADED_TEXT = "i couldn't generate an answer right now"


def schema_check(status: int | None, body) -> tuple[bool, str | None]:
    """The eval schema: HTTP 200 and exactly {"answer": non-empty str, "sources": [http(s) URL, ...]}."""
    if status != 200:
        return False, f"HTTP {status}"
    if not isinstance(body, dict):
        return False, "body is not a JSON object"
    if set(body) != {"answer", "sources"}:
        return False, f"keys {sorted(body)}"
    if not isinstance(body["answer"], str) or not body["answer"].strip():
        return False, "answer is not a non-empty string"
    if not isinstance(body["sources"], list) or not all(isinstance(s, str) for s in body["sources"]):
        return False, "sources is not a list of strings"
    if not all(re.match(r"https?://", s) for s in body["sources"]):
        return False, "a source is not an http(s) URL"
    return True, None


def contract_check(status: int | None, body, error: str | None = None) -> str | None:
    """None when the response honours contract I2 for /ask (also on 422 and 503), else what broke."""
    if status is None:
        return f"no response ({error or 'transport error'})"
    if status not in (200, 422, 503):
        return f"HTTP {status} (only 200, 422 and 503 are allowed)"
    if not isinstance(body, dict) or set(body) != {"answer", "sources"}:
        return f"HTTP {status} body is not exactly {{answer, sources}}"
    if not isinstance(body["answer"], str) or not isinstance(body["sources"], list):
        return f"HTTP {status} answer/sources have the wrong types"
    if status != 200 and body["sources"]:
        return f"HTTP {status} with non-empty sources"
    if status == 200:
        ok, why = schema_check(status, body)
        if not ok:
            return why
    return None


def _norm_text(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").replace("`", "")


def idk_phrase(answer: str) -> str | None:
    m = IDK.search(_norm_text(answer or ""))
    return m.group(0).lower() if m else None


def degraded_kind(answer: str | None, reason: str | None) -> str | None:
    """"degraded:<reason>" for the server's degraded answer (by X-Ask-Reason, or by its text), else None."""
    if reason in DEGRADED_REASONS:
        return f"degraded:{reason}"
    if _norm_text(answer or "").strip().lower().startswith(DEGRADED_TEXT):
        return f"degraded:{reason or 'text'}"
    return None


def abstain_info(body: dict, qtype: str, reason: str | None = None) -> tuple[bool, str | None, str | None]:
    """(abstained, abstain_kind, idk_phrase). abstain_kind is "degraded:<reason>", "empty_sources",
    "pattern:<phrase>" or None; the phrase is recorded even where it does not count (negative and false-premise rows
    skip pattern matching)."""
    phrase = idk_phrase(body.get("answer", ""))
    degraded = degraded_kind(body.get("answer"), reason)
    if degraded:
        return True, degraded, phrase
    if not body.get("sources"):
        return True, "empty_sources", phrase
    if qtype in ("negative", "false-premise"):
        return False, None, phrase
    if phrase:
        return True, f"pattern:{phrase}", phrase
    return False, None, phrase


def source_hit(q: dict, sources: list[str] | None) -> bool | None:
    """None for rows without expected sources; a schema failure on a row with sources is a miss."""
    if not q["expected_norm"]:
        return None
    exp = set(q["expected_norm"])
    return any(normalize_url(s) in exp for s in sources or [])


def behaviour_correct(q: dict, schema_ok: bool, abstained: bool | None) -> bool:
    if q["must_abstain"]:
        return abstained is True
    return bool(schema_ok and abstained is False)


def script_checks(q: dict, sources: list[str] | None) -> list[dict]:
    """Deterministic checks from "Script:" hints in BEHAVIOR items: "sources non-empty" and "includes the ... page"
    (that page is the row's expected source)."""
    out = []
    for i, b in enumerate(q.get("behavior", [])):
        m = SCRIPT_HINT.search(b)
        if not m:
            continue
        hint = m.group(1).strip().lower()
        checks = {}
        if "non-empty" in hint:
            checks["sources_non_empty"] = bool(sources)
        if "includes" in hint:
            checks["includes_expected_page"] = bool(source_hit(q, sources))
        if checks:
            out.append({"behavior_index": i, "hint": m.group(1).strip(), "checks": checks, "ok": all(checks.values())})
    return out


def canary_leaked(answer: str | None, canary: str | None) -> bool:
    return bool(canary and answer and canary.lower() in answer.lower())


def pct(xs: list[float], p: float) -> float | None:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1) if xs else None


def latency_block(ms: list) -> dict:
    """p50 / p95 / max / n of the numeric values (rows that failed have no time)."""
    lat = [x for x in ms if isinstance(x, (int, float))]
    return {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "max": max(lat) if lat else None, "n": len(lat)}


def frac(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(bool(x) for x in xs) / len(xs), 3) if xs else None


def to_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- HTTP
def base_url(url: str) -> str:
    """Accept https://host or https://host/ask."""
    url = url.rstrip("/")
    return url[: -len("/ask")] if url.endswith("/ask") else url


async def get_json(client: httpx.AsyncClient, url: str) -> dict | None:
    try:
        r = await client.get(url)
        return r.json() if r.status_code == 200 else {"status": r.status_code}
    except (httpx.HTTPError, json.JSONDecodeError) as e:
        return {"error": f"{type(e).__name__}: {e}"[:200]}


async def ask_one(client: httpx.AsyncClient, base: str, q: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{base}/ask", json={"question": q["question"]},
                                  headers={"X-Request-ID": f"eval-{q['id']}", "Cache-Control": "no-cache"})
        except httpx.HTTPError as e:
            return {"status": None, "ms": round((time.perf_counter() - t0) * 1000, 1), "body": None,
                    "error": f"{type(e).__name__}: {e}"[:300], "headers": {}}
        ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            body = r.json()
        except json.JSONDecodeError:
            body = None
        headers = {k: r.headers.get(h) for k, h in (("reason", "x-ask-reason"), ("gate_score", "x-ask-gate-score"),
                                                     ("cache", "x-ask-cache"), ("request_id", "x-request-id"),
                                                     ("server_timing", "server-timing"))}
        return {"status": r.status_code, "ms": ms, "body": body, "error": None,
                "headers": {k: v for k, v in headers.items() if v is not None},
                "raw": None if body is not None else r.text[:300]}


# ----------------------------------------------------------------------------- judge
JUDGE_PROMPT = """You grade answers from a documentation assistant.
Input: the question, the assistant's answer, the list of source URLs it returned, required facts, and behaviour checks.
- For each required fact decide whether the answer states it. Paraphrases and equivalent values count; partial or vague mentions do not.
- For each behaviour check decide whether the answer (and its sources list) satisfies it.
- Flag whether the answer contradicts any required fact.
Reply with JSON only: {"covered": [true/false per fact, in order], "behavior_ok": [true/false per behaviour check, in order], "contradiction": true/false}"""


def judge_settings() -> dict:
    model = os.environ.get("JUDGE_MODEL") or os.environ.get("LLM_MODEL") or "qwen3:32b"
    effort = os.environ.get("JUDGE_REASONING_EFFORT")
    if effort is None:
        effort = "none" if "qwen3" in model.lower() else ""
    return {"base_url": os.environ.get("JUDGE_BASE_URL") or os.environ.get("LLM_BASE_URL") or "http://127.0.0.1:11434/v1",
            "api_key": os.environ.get("JUDGE_API_KEY") or os.environ.get("LLM_API_KEY") or "ollama",
            "model": model, "reasoning_effort": effort or None}


def parse_judge(text: str, n_facts: int, n_behav: int) -> dict:
    """Defensive parse of the judge's reply: strip <think>, take the outermost JSON object, coerce the lists."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the judge reply")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("judge reply is not an object")

    def bools(v, n):
        v = v if isinstance(v, list) else []
        out = [x is True or (isinstance(x, str) and x.strip().lower() in ("true", "yes")) for x in v][:n]
        return out + [False] * (n - len(out))
    contradiction = obj.get("contradiction")
    return {"covered": bools(obj.get("covered"), n_facts), "behavior_ok": bools(obj.get("behavior_ok"), n_behav),
            "contradiction": contradiction is True or (isinstance(contradiction, str) and contradiction.lower() == "true")}


async def judge_one(client, settings: dict, q: dict, row: dict, sem: asyncio.Semaphore, retries: int = 1) -> dict:
    facts, behav = q["must_mention"], q.get("behavior", [])
    user = json.dumps({"question": q["question"], "answer": row["answer"], "sources": row["sources"],
                       "required_facts": facts, "behaviour_checks": behav}, ensure_ascii=False)
    extra = {"reasoning_effort": settings["reasoning_effort"]} if settings["reasoning_effort"] else {}
    async with sem:
        t0 = time.perf_counter()
        last = None
        for _ in range(retries + 1):
            try:
                resp = await client.chat.completions.create(
                    model=settings["model"], temperature=0, response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": user}], **extra)
                verdict = parse_judge(resp.choices[0].message.content or "", len(facts), len(behav))
                break
            except Exception as e:  # noqa: BLE001  (timeouts, HTTP errors, unparseable replies: retried once)
                last = f"{type(e).__name__}: {e}"[:200]
        else:
            return {"error": last, "judge_ms": round((time.perf_counter() - t0) * 1000)}
    out = {**verdict, "judge_ms": round((time.perf_counter() - t0) * 1000)}
    raw = list(out["behavior_ok"])
    for s in row.get("script") or []:  # a Script hint must also hold for its BEHAVIOR item to pass
        i = s["behavior_index"]
        if i < len(out["behavior_ok"]):
            out["behavior_ok"][i] = out["behavior_ok"][i] and s["ok"]
    if raw != out["behavior_ok"]:
        out["behavior_ok_judge_only"] = raw
    if facts:
        out["coverage"] = round(sum(out["covered"]) / len(facts), 3)
    if behav:
        out["behavior_pass"] = all(out["behavior_ok"])
    return out


# ----------------------------------------------------------------------------- scoring
def score_row(q: dict, res: dict, canary: str | None) -> dict:
    body = res.get("body")
    ok, why = schema_check(res["status"], body)
    contract = contract_check(res["status"], body, res.get("error"))
    answer = body.get("answer") if ok else None
    sources = body.get("sources") if ok else None
    hdr = res.get("headers") or {}
    abst, kind, phrase = abstain_info(body, q["type"], hdr.get("reason")) if ok else (None, None, None)
    degraded = bool(kind and kind.startswith("degraded:"))
    text = body.get("answer") if isinstance(body, dict) and isinstance(body.get("answer"), str) else None
    leaked = canary_leaked(text, canary)
    row = {
        "id": q["id"], "category": q["category"], "type": q["type"], "must_abstain": q["must_abstain"],
        "status": res["status"], "ms": res["ms"], "error": res.get("error"),
        "schema_ok": ok, "schema_error": why, "contract_error": contract,
        "abstained": abst, "abstain_kind": kind, "idk_phrase": phrase, "degraded": degraded,
        # a degraded answer lists pages without answering: never a source hit, never the expected behaviour
        "source_hit": (False if degraded else source_hit(q, sources)) if q["expected_norm"] else None,
        "behaviour_correct": behaviour_correct(q, ok, abst) and not leaked and not degraded,
        "canary_leak": leaked,
        "reason": hdr.get("reason"), "gate_score": to_float(hdr.get("gate_score")), "cache": hdr.get("cache"),
        "server_timing": hdr.get("server_timing"),
        "answer": answer, "sources": sources,
    }
    row["script"] = script_checks(q, sources) if ok else []
    if not ok and res.get("raw"):
        row["raw"] = res["raw"]
    return row


def rate_block(rows: list[dict], flag: str = "abstained", count_degraded: bool = True) -> dict:
    """Rows whose flag is set, with the abstain_kind breakdown. count_degraded=False (abstain recall) does not credit
    a degraded answer as a decline: the server failed, it did not decline."""
    hits = [r for r in rows if r.get(flag) and (count_degraded or not r.get("degraded"))]
    kinds = Counter(r.get("abstain_kind") or "none" for r in hits)
    out = {"n": len(rows), "count": len(hits), "rate": round(len(hits) / len(rows), 3) if rows else None,
           "kinds": dict(kinds), "ids": [r["id"] for r in hits]}
    if not count_degraded:
        out["degraded_not_counted"] = [r["id"] for r in rows if r.get("degraded")]
    return out


def gate_calibration(rows: list[dict]) -> dict:
    """The lowest gate score among must-answer rows minus 0.02 (the next ABSTAIN_THRESHOLD), and how many
    must-abstain rows score below it."""
    ans = [r["gate_score"] for r in rows if not r["must_abstain"] and r.get("gate_score") is not None]
    abst = [(r["id"], r["gate_score"]) for r in rows if r["must_abstain"] and r.get("gate_score") is not None]
    if not ans:
        return {"available": False, "line": "gate calibration: no gate scores (GATE_SIGNAL=off, or no X-Ask-Gate-Score)"}
    low = min(ans)
    lowest_id = next(r["id"] for r in rows if not r["must_abstain"] and r.get("gate_score") == low)
    thr = round(low - GATE_MARGIN, 4)
    below = sorted(i for i, s in abst if s < thr)
    return {"available": True, "lowest_must_answer": round(low, 4), "lowest_must_answer_id": lowest_id,
            "threshold": thr, "must_abstain_scored": len(abst), "must_abstain_below": len(below), "below_ids": below,
            "line": f"gate calibration: lowest must-answer gate score {low:.4f} ({lowest_id}) - {GATE_MARGIN} = "
                    f"ABSTAIN_THRESHOLD {thr:.4f}; must-abstain rows below it: {len(below)}/{len(abst)}"}


def summarize(rows: list[dict]) -> dict:
    cov = [r["judge"]["coverage"] for r in rows if "coverage" in (r.get("judge") or {})]
    bp = [r["judge"]["behavior_pass"] for r in rows if "behavior_pass" in (r.get("judge") or {})]
    return {
        "n": len(rows),
        "schema_valid": frac([r["schema_ok"] for r in rows]),
        "behaviour_correct": frac([r["behaviour_correct"] for r in rows]),
        "source_hit_rate": frac([r["source_hit"] for r in rows]),
        "fact_coverage_mean": round(sum(cov) / len(cov), 3) if cov else None,
        "behavior_pass_rate": frac(bp),
        "contradictions": sum(1 for r in rows if (r.get("judge") or {}).get("contradiction")),
    }


def summary_of(rows: list[dict], ask_wall: float, judge_wall: float) -> dict:
    s = summarize(rows)
    lat = [r["ms"] for r in rows if r["status"] == 200]
    must_abstain_rows = [r for r in rows if r["type"] in ("unanswerable", "out-of-scope")]
    answerable = [r for r in rows if r["type"] == "answerable"]
    must_answer = [r for r in rows if not r["must_abstain"]]
    s.update({
        "contract_failures": sum(1 for r in rows if r["contract_error"]),
        "contract_failure_ids": [f"{r['id']}: {r['contract_error']}" for r in rows if r["contract_error"]],
        "canary_leaks": [r["id"] for r in rows if r["canary_leak"]],
        "http_status": dict(Counter(str(r["status"]) for r in rows)),
        "degraded": {"count": sum(1 for r in rows if r.get("degraded")),
                     "by_reason": dict(Counter(r["abstain_kind"].split(":", 1)[1] for r in rows if r.get("degraded"))),
                     "ids": [r["id"] for r in rows if r.get("degraded")]},
        "abstain_recall": rate_block(must_abstain_rows, count_degraded=False),
        "false_abstain_answerable": rate_block(answerable),
        "false_abstain_must_answer": rate_block(must_answer),
        "server_reasons": dict(Counter(r.get("reason") or "(none)" for r in rows)),
        "cache_hits": sum(1 for r in rows if r.get("cache") == "hit"),
        "latency_ms": latency_block(lat),
        "ask_wall_s": round(ask_wall, 1), "judge_wall_s": round(judge_wall, 1),
        "total_wall_s": round(ask_wall + judge_wall, 1),
        "gate_calibration": gate_calibration(rows),
    })
    return s


# ----------------------------------------------------------------------------- full run
async def run_full(args, qs: list[dict]) -> dict:
    base = base_url(args.base_url)
    canary = os.environ.get("CANARY") or None
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        health = await get_json(client, f"{base}/healthz")
        t0 = time.perf_counter()
        results = await asyncio.gather(*(ask_one(client, base, q, sem) for q in qs))
        ask_wall = time.perf_counter() - t0
    rows = [score_row(q, res, canary) for q, res in zip(qs, results)]

    judge_wall, judge_info = 0.0, None
    if args.judge:
        from openai import AsyncOpenAI
        js = judge_settings()
        generator = args.generator_model or os.environ.get("LLM_MODEL") or ""
        judge_info = {"model": js["model"], "base_url_host": urlsplit(js["base_url"]).netloc,
                      "reasoning_effort": js["reasoning_effort"], "generator_model": generator or None}
        if generator and generator.lower() == js["model"].lower():
            judge_info["caveat"] = ("the judge is the same model as the generator: LLM judges favour their own "
                                    "outputs (self-preference), so treat fact coverage and BEHAVIOR passes as optimistic")
        client = AsyncOpenAI(base_url=js["base_url"], api_key=js["api_key"], timeout=args.judge_timeout, max_retries=0)
        jsem = asyncio.Semaphore(args.judge_concurrency)
        todo = [(q, r) for q, r in zip(qs, rows) if r["schema_ok"] and (q["must_mention"] or q.get("behavior"))]
        t1 = time.perf_counter()
        verdicts = await asyncio.gather(*(judge_one(client, js, q, r, jsem) for q, r in todo))
        judge_wall = time.perf_counter() - t1
        for (_, r), v in zip(todo, verdicts):
            r["judge"] = v
        judge_info["errors"] = sum(1 for v in verdicts if "error" in v)

    summary = summary_of(rows, ask_wall, judge_wall)
    return {
        "mode": "full", "label": args.label, "base_url": base,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": {"file": "eval/questions.md", "n": len(qs)},
        "flags": run_flags(args), "healthz": health, "judge": judge_info, "canary_checked": bool(canary),
        "summary": summary,
        "by_type": {t: summarize([r for r in rows if r["type"] == t]) for t in TYPES if any(r["type"] == t for r in rows)},
        "by_category": {c: summarize([r for r in rows if r["category"] == c]) for c in sorted({r["category"] for r in rows})},
        "rows": rows,
    }


# ----------------------------------------------------------------------------- retrieval-only
async def retrieve_one(client: httpx.AsyncClient, base: str, q: dict, sem: asyncio.Semaphore, k: int) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(f"{base}/debug/retrieve", json={"question": q["question"], "k": k},
                                  headers={"X-Request-ID": f"eval-retrieve-{q['id']}"})
            body = r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            return {"status": None, "error": f"{type(e).__name__}: {e}"[:300], "ms": None}
        return {"status": r.status_code, "body": body, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def hit_urls(h: dict) -> list[str]:
    """Every URL /ask could cite for one hit: source_urls (a fact card's chosen cite_urls), source_url, doc_url."""
    urls = list(h.get("source_urls") or [])
    urls += [u for u in (h.get("source_url"), h.get("doc_url")) if u]
    return list(dict.fromkeys(urls))


def first_hit_rank(q: dict, results: list[dict], k: int = 10) -> int | None:
    exp = set(q["expected_norm"])
    for i, h in enumerate(results[:k], start=1):
        if any(normalize_url(u) in exp for u in hit_urls(h)):
            return i
    return None


def retrieval_metrics(rows: list[dict]) -> dict:
    ranked = [r for r in rows if r["expected"]]
    n = len(ranked)

    def hit(k):
        return round(sum(1 for r in ranked if r["first_hit_rank"] and r["first_hit_rank"] <= k) / n, 3) if n else None
    mrr = round(sum(1 / r["first_hit_rank"] for r in ranked if r["first_hit_rank"]) / n, 3) if n else None
    return {"n": n, "hit@1": hit(1), "hit@3": hit(3), "hit@5": hit(5), "hit@10": hit(10), "mrr@10": mrr}


async def run_retrieval(args, qs: list[dict]) -> dict:
    base = base_url(args.base_url)
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        health = await get_json(client, f"{base}/healthz")
        t0 = time.perf_counter()
        results = await asyncio.gather(*(retrieve_one(client, base, q, sem, 10) for q in qs))
        wall = time.perf_counter() - t0
    rows, errors = [], []
    for q, res in zip(qs, results):
        body = res.get("body") if res.get("status") == 200 else None
        if body is None:
            errors.append(f"{q['id']}: {res.get('error') or res.get('status')} {str(res.get('body'))[:120]}")
        hits = (body or {}).get("results") or []
        rows.append({
            "id": q["id"], "category": q["category"], "type": q["type"], "must_abstain": q["must_abstain"],
            "expected": q["expected_sources"], "first_hit_rank": first_hit_rank(q, hits) if q["expected_norm"] else None,
            "gate_score": to_float((body or {}).get("gate_score")), "ms": res.get("ms"),
            "top10": [h.get("source_url") or h.get("doc_url") for h in hits[:10]],
            "top10_urls": [hit_urls(h) for h in hits[:10]],
            "top10_types": [h.get("source_type") for h in hits[:10]],
        })
    cats = sorted({r["category"] for r in rows if r["expected"]})
    by_cat = {c: retrieval_metrics([r for r in rows if r["category"] == c]) for c in cats}
    return {
        "mode": "retrieval", "label": args.label, "base_url": base,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions": {"file": "eval/questions.md", "n": len(qs)}, "flags": run_flags(args), "healthz": health,
        "summary": {**retrieval_metrics(rows), "errors": errors, "wall_s": round(wall, 1),
                    "latency_ms": latency_block([r["ms"] for r in rows]),  # client round trip of /debug/retrieve
                    "gate_calibration": gate_calibration(rows),
                    "must_abstain_gate_scores": {r["id"]: r["gate_score"] for r in rows if r["must_abstain"]},
                    "top10_outside_share": round(sum(t == "outside" for r in rows for t in r["top10_types"]) /
                                                 max(1, sum(len(r["top10_types"]) for r in rows)), 3)},
        "by_category": by_cat, "rows": rows,
    }


# ----------------------------------------------------------------------------- compare
def compare(new: dict, old: dict) -> list[str]:
    if new.get("mode") != old.get("mode"):
        return [f"cannot compare a {new.get('mode')} run with a {old.get('mode')} run"]
    o = {r["id"]: r for r in old["rows"]}
    lines = []
    if new["mode"] == "retrieval":
        sn, so = new["summary"], old["summary"]
        lines.append("metric        old -> new")
        for k in ("hit@1", "hit@3", "hit@5", "hit@10", "mrr@10"):
            lines.append(f"  {k:<10}  {so.get(k)} -> {sn.get(k)}  ({_delta(sn.get(k), so.get(k))})")
        enter, leave, moved = [], [], []
        for r in new["rows"]:
            p = o.get(r["id"])
            if not p or not r["expected"]:
                continue
            a, b = p["first_hit_rank"], r["first_hit_rank"]
            if a is None and b is not None:
                enter.append(f"{r['id']} (rank {b})")
            elif a is not None and b is None:
                leave.append(f"{r['id']} (was rank {a})")
            elif a != b:
                moved.append(f"{r['id']} {a}->{b}")
        lines.append(f"enter the top 10 ({len(enter)}): {', '.join(enter) or '-'}")
        lines.append(f"leave the top 10 ({len(leave)}): {', '.join(leave) or '-'}")
        lines.append(f"rank changes inside the top 10 ({len(moved)}): {', '.join(moved) or '-'}")
        gl = []
        for r in new["rows"]:
            p = o.get(r["id"])
            if p and r["must_abstain"]:
                gl.append(f"{r['id']} {_fmt(p.get('gate_score'))}->{_fmt(r.get('gate_score'))}")
        lines.append(f"must-abstain gate scores old->new: {', '.join(gl) or '-'}")
        lines.append(f"gate calibration old: {so.get('gate_calibration', {}).get('line')}")
        lines.append(f"gate calibration new: {sn.get('gate_calibration', {}).get('line')}")
        return lines
    for field in ("behaviour_correct", "source_hit", "abstained"):
        changes = []
        for r in new["rows"]:
            p = o.get(r["id"])
            if p and p.get(field) != r.get(field):
                extra = f" [{r.get('abstain_kind')}]" if field == "abstained" and r.get("abstained") else ""
                changes.append(f"{r['id']} {p.get(field)}->{r.get(field)}{extra}")
        lines.append(f"{field} changed ({len(changes)}): {', '.join(changes) or '-'}")
    sn, so = new["summary"], old["summary"]
    for k in ("schema_valid", "behaviour_correct", "source_hit_rate", "fact_coverage_mean", "behavior_pass_rate"):
        lines.append(f"  {k}: {so.get(k)} -> {sn.get(k)}")
    return lines


def _delta(a, b) -> str:
    return "n/a" if a is None or b is None else f"{a - b:+.3f}"


def _fmt(v) -> str:
    return "None" if v is None else f"{v:.4f}"


# ----------------------------------------------------------------------------- rescore
def scorer_version() -> str | None:
    """This scorer's commit for --rescore provenance: the short SHA, "-dirty" if the scorer has uncommitted edits."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "eval/run.py", "eval/questions.py",
                                "eval/questions.md"], cwd=REPO_ROOT, capture_output=True, timeout=10).returncode == 1
    except (OSError, subprocess.SubprocessError):
        return None
    return (sha + ("-dirty" if dirty else "")) if sha else None


def rescore(path: Path, canary: str | None = None) -> dict:
    """Re-apply the deterministic checks to a saved full run (no requests; judge verdicts are kept)."""
    old = json.loads(path.read_text(encoding="utf-8"))
    if old.get("mode") != "full":
        raise SystemExit("--rescore needs a full-run results file")
    qfile = (old.get("flags") or {}).get("questions")
    qs = {q["id"]: q for q in load_questions(REPO_ROOT / qfile if qfile else QUESTIONS_FILE)}
    rows = []
    for r in old["rows"]:
        body = {"answer": r["answer"], "sources": r["sources"]} if r["schema_ok"] else None
        res = {"status": r["status"], "ms": r["ms"], "body": body, "error": r.get("error"), "raw": r.get("raw"),
               "headers": {"reason": r.get("reason"), "gate_score": r.get("gate_score"), "cache": r.get("cache"),
                           "server_timing": r.get("server_timing")}}
        new = score_row(qs[r["id"]], res, canary)
        if not r["schema_ok"]:  # the original body is not stored: keep the original schema and contract verdicts
            new.update(schema_error=r["schema_error"], contract_error=r["contract_error"])
        if r.get("judge"):
            new["judge"] = r["judge"]
        rows.append(new)
    s = old["summary"]
    out = dict(old, rows=rows, rescored_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               rescored_with=scorer_version())
    out["summary"] = summary_of(rows, s.get("ask_wall_s", 0.0), s.get("judge_wall_s", 0.0))
    out["by_type"] = {t: summarize([r for r in rows if r["type"] == t]) for t in TYPES if any(r["type"] == t for r in rows)}
    out["by_category"] = {c: summarize([r for r in rows if r["category"] == c])
                          for c in sorted({r["category"] for r in rows})}
    return out


# ----------------------------------------------------------------------------- CLI
REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_rel(path: str) -> str:
    """A path as recorded in results files: repo-relative when inside the repo, else the bare file name (results
    files are committed, so they must never hold an absolute personal path)."""
    if not path:
        return path
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.name


def run_flags(args) -> dict:
    flags = {k: v for k, v in vars(args).items() if k not in ("base_url",)}
    for k in ("questions", "out", "compare", "rescore"):
        if flags.get(k):
            flags[k] = repo_rel(flags[k])
    return flags


def select(qs: list[dict], args) -> list[dict]:
    if args.ids:
        keep = [x.strip() for x in args.ids.split(",") if x.strip()]
        unknown = set(keep) - {q["id"] for q in qs}
        if unknown:
            raise SystemExit(f"unknown ids: {', '.join(sorted(unknown))}")
        qs = [q for q in qs if q["id"] in set(keep)]
    if args.types:
        types = {t.strip() for t in args.types.split(",") if t.strip()}
        bad = types - set(TYPES)
        if bad:
            raise SystemExit(f"unknown types: {', '.join(sorted(bad))} (known: {', '.join(TYPES)})")
        qs = [q for q in qs if q["type"] in types]
    if args.limit:
        qs = qs[: args.limit]
    return qs


def default_out(args) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", args.label).strip("-") if args.label else stamp
    return RESULTS_DIR / f"{'retrieval-' if args.retrieval_only else ''}{name}.json"


def print_full(report: dict) -> None:
    s = report["summary"]
    n = (report.get("questions") or {}).get("n", len(report.get("rows") or []))
    print(f"{n} rows against {report.get('base_url', '?')}  (index {index_version(report)})")
    print(f"schema_valid {s['schema_valid']}  contract_failures {s['contract_failures']}  behaviour_correct "
          f"{s['behaviour_correct']}  source_hit_rate {s['source_hit_rate']}  fact_coverage {s['fact_coverage_mean']}  "
          f"BEHAVIOR pass {s['behavior_pass_rate']}  contradictions {s['contradictions']}")
    a, fa, fm = s["abstain_recall"], s["false_abstain_answerable"], s["false_abstain_must_answer"]
    d = s["degraded"]
    print(f"degraded answers {d['count']} {d['by_reason']} {d['ids']}")
    print(f"abstain recall {a['count']}/{a['n']} ({a['rate']}) {a['kinds']}")
    print(f"false abstain answerable {fa['count']}/{fa['n']} ({fa['rate']}) {fa['kinds']} {fa['ids']}")
    print(f"false abstain must-answer {fm['count']}/{fm['n']} ({fm['rate']}) {fm['kinds']} {fm['ids']}")
    print(f"latency ms p50 {s['latency_ms']['p50']} p95 {s['latency_ms']['p95']} max {s['latency_ms']['max']}; "
          f"wall ask {s['ask_wall_s']} s, judge {s['judge_wall_s']} s, total {s['total_wall_s']} s")
    print(f"server reasons {s['server_reasons']}  http {s['http_status']}")
    print(s["gate_calibration"]["line"])
    print(f"{'type':<14} {'n':>3} {'schema':>6} {'behav':>6} {'src':>6} {'facts':>6} {'BEHAV':>6}")
    for t, v in report["by_type"].items():
        print(f"{t:<14} {v['n']:>3} {_n(v['schema_valid'])} {_n(v['behaviour_correct'])} {_n(v['source_hit_rate'])} "
              f"{_n(v['fact_coverage_mean'])} {_n(v['behavior_pass_rate'])}")
    for cat, v in report["by_category"].items():
        print(f"  {cat:<18} {v['n']:>3} behav {v['behaviour_correct']} src {v['source_hit_rate']}")
    if report.get("judge", {}) and report["judge"].get("caveat"):
        print(f"judge {report['judge']['model']}: {report['judge']['caveat']}")
    judge_errors = [f"{r['id']}: {r['judge']['error']}" for r in report["rows"] if "error" in (r.get("judge") or {})]
    if report.get("judge") is not None:
        print(f"judge errors: {len(judge_errors)}")
    for e in judge_errors:
        print(f"JUDGE ERROR {e}")
    for f in s["contract_failure_ids"]:
        print(f"CONTRACT FAILURE {f}")
    for i in s["canary_leaks"]:
        print(f"CANARY LEAK {i}")


def index_version(report: dict) -> str:
    idx = (report.get("healthz") or {}).get("index")
    return str(idx.get("version")) if isinstance(idx, dict) else "?"


def _n(v) -> str:
    return f"{v:>6}" if v is not None else f"{'-':>6}"


def print_retrieval(report: dict) -> None:
    s = report["summary"]
    print(f"retrieval-only, {s['n']} rows with sources against {report['base_url']} (index {index_version(report)}, "
          f"{s['wall_s']} s)")
    print(f"hit@1 {s['hit@1']}  hit@3 {s['hit@3']}  hit@5 {s['hit@5']}  hit@10 {s['hit@10']}  MRR@10 {s['mrr@10']}  "
          f"outside share of top-10 slots {s['top10_outside_share']}")
    lat = s.get("latency_ms") or {}
    if lat:
        print(f"latency ms p50 {lat.get('p50')} p95 {lat.get('p95')} max {lat.get('max')} (client round trip)")
    for c, v in report["by_category"].items():
        print(f"  {c:<18} n={v['n']:<3} hit@1 {v['hit@1']}  hit@10 {v['hit@10']}  MRR@10 {v['mrr@10']}")
    print(s["gate_calibration"]["line"])
    print("must-abstain gate scores: " + ", ".join(f"{k} {_fmt(v)}" for k, v in s["must_abstain_gate_scores"].items()))
    misses = [r["id"] for r in report["rows"] if r["expected"] and r["first_hit_rank"] is None]
    print(f"no expected source in the top 10 ({len(misses)}): {', '.join(misses) or '-'}")
    for e in s["errors"]:
        print(f"ERROR {e}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Ask OLake eval runner (eval/questions.md, plan §4.5 D2)")
    ap.add_argument("--base-url", default="", help="the deployment root, e.g. http://127.0.0.1:8000")
    ap.add_argument("--rescore", default="", help="re-apply the deterministic checks to a saved full run (no requests)")
    ap.add_argument("--questions", default=str(QUESTIONS_FILE))
    ap.add_argument("--ids", default="", help="comma-separated question ids")
    ap.add_argument("--types", default="", help="comma-separated types")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=60.0, help="per request, seconds (above the server's bound)")
    ap.add_argument("--judge", action="store_true", help="run the LLM judge (JUDGE_* env)")
    ap.add_argument("--judge-concurrency", type=int, default=1)
    ap.add_argument("--judge-timeout", type=float, default=300.0)
    ap.add_argument("--generator-model", default="", help="the server's answer model, for the self-preference flag")
    ap.add_argument("--retrieval-only", action="store_true", help="POST /debug/retrieve (server with DEBUG=1); no LLM")
    ap.add_argument("--compare", default="", help="an earlier results file of the same mode")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    if args.rescore:
        report = rescore(Path(args.rescore), os.environ.get("CANARY") or None)
        print_full(report)
        src = Path(args.rescore)  # never overwrite the input unless --out names it
        out = Path(args.out) if args.out else src.with_name(f"{src.stem}.rescored{src.suffix}")
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {out}")
        sys.exit(1 if report["summary"]["contract_failures"] or report["summary"]["canary_leaks"] else 0)
    if not args.base_url:
        raise SystemExit("--base-url is required (or --rescore FILE)")
    qs = select(load_questions(args.questions), args)
    if not qs:
        raise SystemExit("no questions selected")
    if args.retrieval_only:
        report = asyncio.run(run_retrieval(args, qs))
        print_retrieval(report)
    else:
        report = asyncio.run(run_full(args, qs))
        print_full(report)
    out = Path(args.out) if args.out else default_out(args)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    if args.compare:
        print(f"--- compare with {args.compare}")
        for line in compare(report, json.loads(Path(args.compare).read_text(encoding="utf-8"))):
            print(line)
    if report["mode"] == "full" and (report["summary"]["contract_failures"] or report["summary"]["canary_leaks"]):
        sys.exit(1)
    if report["mode"] == "retrieval" and report["summary"]["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
