"""Gate calibration: what the dense off-topic gate declines before and after the product-intro override
(app/product_intro.py). In process on the active index: no server, no LLM, no network beyond the fastembed model cache.

    uv run python -m eval.gate [--options] [--out eval/results/gate-calibration.json]

Every question goes through a real AskService (data/index/CURRENT, the real query embedder, ABSTAIN_THRESHOLD, no
cache, limits that never bite) whose LLM is a stub answering NO_ANSWER, and gets one decision:
  smalltalk       the canned intro (app/smalltalk.py), ahead of retrieval
  retrieval_gate  the off-topic decline, no LLM call
  llm             the stub was reached: the question passed the gate
"Before" is the rule without the override: smalltalk, else retrieval_gate below the threshold, else llm.

Inputs: the 94 rows of eval/questions.md, and INTRO_PROBES, OFF_TOPIC_PROBES and GUARD_PROBES from eval/gate_probes.py.
Criteria (exit 1 if any fails):
  1  the eval rows declined after the change are final.json's retrieval_gate rows (UNK-06, OOS-01, -02, -04, -06)
  2  every intro probe reaches the LLM
  3  every off-topic probe gets retrieval_gate
  4  no guard probe is a product intro, and each keeps its decision
--options adds the alternatives, recomputed on the same questions: (a) a lower threshold, 0.69 down to 0.62; (b) the
override; (c) an overview chunk in the index (two candidate texts, passage-embedded, max with the index's dense
scores); (d) a normalized gate query (filler words dropped, the product name expanded, no query prefix, casefolded).
Per option: the eval rows declined and whether that set is unchanged, the intro probes that reach the LLM, the
off-topic probes declined, and UNK-06's gate score.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app import product_intro, smalltalk
from app.config import Settings
from app.embedder import FastEmbedQueryEmbedder
from app.index_store import IndexHolder, IndexSnapshot, load_snapshot
from app.limits import DailyTokenBudget, TokenBucket
from app.llm import LLMResult
from app.pipeline import SMALLTALK_REASON, AskRequest, AskService
from eval.gate_probes import GUARD_PROBES, INTRO_PROBES, OFF_TOPIC_PROBES
from eval.questions import load_questions

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "eval" / "results"
FINAL_RESULTS = RESULTS_DIR / "final.json"
EXPECTED_DECLINES = ("OOS-01", "OOS-02", "OOS-04", "OOS-06", "UNK-06")
THRESHOLDS = (0.69, 0.68, 0.67, 0.66, 0.65, 0.64, 0.63, 0.62)

# (c) two candidate overview chunks, each with a context header like the index's fact cards
OVERVIEWS = {
    "short overview": (
        "What is OLake | OLake fact card\n\n# OLake overview\n\nOLake is an open-source tool by Datazip that "
        "replicates data from databases (PostgreSQL, MySQL, MongoDB, Oracle, DB2, MSSQL) and Kafka into Apache Iceberg "
        "tables or Parquet files, with full refresh, incremental and CDC sync modes. OLake Fusion is OLake's "
        "open-source Iceberg table maintenance service (compaction). Ask OLake is the documentation assistant that "
        "answers questions about OLake and OLake Fusion from the OLake docs."),
    "Q&A-phrased overview": (
        "About OLake | OLake fact card\n\n# What is OLake? Who is OLake? What can OLake do?\n\nOLake is an open-source "
        "data ingestion tool from Datazip: it moves data from databases and streams into Apache Iceberg. OLake Fusion "
        "maintains Iceberg tables. Ask OLake is this documentation assistant."),
}
# (d) the gate query rewritten before it is embedded
FILLER = re.compile(r"\b(?:can you|could you|please|tell me about|tell me|i want to know about|i want to know|for me|"
                    r"give me)\b", re.I)
PRODUCT_EXPANSION = "OLake (open-source database replication into Apache Iceberg)"


class NoAnswerLLM:
    """The provider chain's stand-in: no network; every call is counted and answers NO_ANSWER."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages, *, deadline: float, on_delta=None) -> LLMResult:
        self.calls += 1
        return LLMResult(text="NO_ANSWER", finish_reason="stop", prompt_tokens=0, completion_tokens=0,
                         provider="stub", model="no-answer", ttft_ms=0.0)


# ----------------------------------------------------------------------------- decisions
async def decide_all(svc: AskService, llm: NoAnswerLLM, questions: list[str]) -> list[dict]:
    """Each question through the pipeline, one at a time: its gate score, the decision the pipeline took (after the
    change) and the one the rule without the override takes (before it)."""
    thr = svc.s.abstain_threshold
    out = []
    for q in questions:
        calls = llm.calls
        res = await svc.answer(AskRequest(question=q, request_id="eval-gate", no_cache=True))
        if res.reason == SMALLTALK_REASON:
            after = "smalltalk"
        elif llm.calls > calls:
            after = "llm"
        else:  # retrieval_gate, or a degraded reason that fails every criterion looking at it
            after = res.reason
        kind = smalltalk.detect(q)
        gate = res.gate_score
        before = "smalltalk" if kind else "retrieval_gate" if gate is not None and gate < thr else "llm"
        out.append({"question": q, "gate_score": None if gate is None else round(gate, 4), "smalltalk": kind,
                    "product_intro": product_intro.is_product_intro(q), "before": before, "after": after})
    return out


def eval_rows(qs: list[dict], decided: list[dict], final_reasons: dict[str, str | None]) -> list[dict]:
    rows = []
    for q, d in zip(qs, decided, strict=True):
        before, after = d["before"] == "retrieval_gate", d["after"] == "retrieval_gate"
        rows.append({"id": q["id"], "final_reason": final_reasons.get(q["id"]), "gate_score": d["gate_score"],
                     "declined_before": before, "declined_after": after, "changed": before != after})
    return rows


def criteria(rows: list[dict], final_declines: list[str], probes: dict[str, list[dict]]) -> list[dict]:
    after = sorted(r["id"] for r in rows if r["declined_after"])
    expected = sorted(EXPECTED_DECLINES)
    intro, off, guard = probes["intro"], probes["off_topic"], probes["guard"]
    intro_missed = [p["question"] for p in intro if p["after"] != "llm"]
    off_missed = [p["question"] for p in off if p["after"] != "retrieval_gate"]
    guard_bad = [p["question"] for p in guard if p["product_intro"] or p["before"] != p["after"]]
    return [
        _criterion(1, after == final_declines == expected,
                   f"eval rows the gate declines after the change: {_ids(after)}; in final.json: "
                   f"{_ids(final_declines)}; expected: {_ids(expected)}", []),
        _criterion(2, not intro_missed, f"intro probes that reach the LLM: {len(intro) - len(intro_missed)}/"
                                        f"{len(intro)}", intro_missed),
        _criterion(3, not off_missed, f"off-topic probes the gate declines: {len(off) - len(off_missed)}/{len(off)}",
                   off_missed),
        _criterion(4, not guard_bad, f"guard probes that are no product intro and keep their decision: "
                                     f"{len(guard) - len(guard_bad)}/{len(guard)}", guard_bad),
    ]


def _criterion(n: int, passed: bool, line: str, failures: list[str]) -> dict:
    return {"criterion": n, "passed": passed, "line": line, "failures": failures}


def _ids(ids: list[str]) -> str:
    return ", ".join(ids) or "-"


# ----------------------------------------------------------------------------- options
def query_vector(snap: IndexSnapshot, emb: FastEmbedQueryEmbedder, text: str, prefix: bool = True) -> np.ndarray:
    """The query vector as app.retrieval builds it: the index's query prefix, embedded, L2-normalised."""
    q = np.asarray(emb.embed_query((snap.query_prefix if prefix else "") + text), dtype=np.float32)
    norm = float(np.linalg.norm(q))
    return q / norm if norm else q


def index_gate(snap: IndexSnapshot, q: np.ndarray) -> float:
    """The gate score as app.retrieval computes it: the highest dense cosine over the eligible chunks."""
    return float(np.where(snap.ranking.eligible, snap.embeddings @ q, -np.inf).max())


def passage_vector(emb: FastEmbedQueryEmbedder, text: str) -> np.ndarray:
    """A chunk vector as index/embed.py builds it: passage_embed, L2-normalised."""
    v = np.asarray(next(iter(emb.model.passage_embed([text]))), dtype=np.float32)
    return v / float(np.linalg.norm(v))


def drop_filler(q: str) -> str:
    return re.sub(r"\s+", " ", FILLER.sub(" ", q)).strip() or q


def expand_product(q: str) -> str:
    return re.sub(r"\bolake\b", PRODUCT_EXPANSION, q, flags=re.I)


def compare_options(snap: IndexSnapshot, emb: FastEmbedQueryEmbedder, thr: float,
                    groups: dict[str, list[dict]]) -> list[dict]:
    """(a)-(d) on the eval rows and the intro and off-topic probes. Small talk still runs first under every option."""
    every = [d for g in groups.values() for d in g]
    unk06 = next(d["question"] for d in groups["eval"] if d["id"] == "UNK-06")
    vec = {d["question"]: query_vector(snap, emb, d["question"]) for d in every}
    base = {q: index_gate(snap, v) for q, v in vec.items()}
    before = sorted(d["id"] for d in groups["eval"] if _by_gate(d, base, thr) == "retrieval_gate")

    def row(name: str, decide: Callable[[dict], str], unk06_gate: float) -> dict:
        declined = sorted(d["id"] for d in groups["eval"] if decide(d) == "retrieval_gate")
        return {"option": name, "eval_declined": declined, "eval_unchanged": declined == before,
                "intro_reach_llm": sum(decide(d) == "llm" for d in groups["intro"]), "intro_n": len(groups["intro"]),
                "off_topic_declined": sum(decide(d) == "retrieval_gate" for d in groups["off_topic"]),
                "off_topic_n": len(groups["off_topic"]), "unk06_gate": round(unk06_gate, 4)}

    out = [row(f"(a) threshold {t:.2f}", lambda d, t=t: _by_gate(d, base, t), base[unk06]) for t in THRESHOLDS]
    out.append(row("(b) intro-frame override", lambda d: d["after"], base[unk06]))
    for name, text in OVERVIEWS.items():
        ov = passage_vector(emb, text)
        gates = {q: max(base[q], float(ov @ v)) for q, v in vec.items()}
        out.append(row(f"(c) {name} chunk", lambda d, g=gates: _by_gate(d, g, thr), gates[unk06]))
    for name, gate_of in (
            ("(d) drop filler words", lambda q: index_gate(snap, query_vector(snap, emb, drop_filler(q)))),
            ("(d) expand the product name", lambda q: index_gate(snap, query_vector(snap, emb, expand_product(q)))),
            ("(d) no query prefix", lambda q: index_gate(snap, query_vector(snap, emb, q, prefix=False))),
            ("(d) casefold", lambda q: index_gate(snap, query_vector(snap, emb, q.casefold())))):
        gates = {d["question"]: gate_of(d["question"]) for d in every}
        out.append(row(name, lambda d, g=gates: _by_gate(d, g, thr), gates[unk06]))
    return out


def _by_gate(d: dict, gates: dict[str, float], t: float) -> str:
    return "smalltalk" if d["smalltalk"] else "retrieval_gate" if gates[d["question"]] < t else "llm"


def options_markdown(opts: list[dict]) -> list[str]:
    lines = ["| Option | Eval rows declined | Unchanged | Intro probes reach the LLM | Off-topic probes declined "
             "| UNK-06 gate |", "|---|---|---|---|---|---|"]
    for o in opts:
        lines.append(f"| {o['option']} | {_ids(o['eval_declined'])} | {'yes' if o['eval_unchanged'] else 'no'} | "
                     f"{o['intro_reach_llm']}/{o['intro_n']} | {o['off_topic_declined']}/{o['off_topic_n']} | "
                     f"{o['unk06_gate']:.4f} |")
    return lines


# ----------------------------------------------------------------------------- run
async def run(with_options: bool) -> dict:
    s = Settings.from_env()
    if s.gate_signal != "dense" or s.retrieval_mode != "hybrid":
        raise SystemExit("eval.gate measures the dense gate: unset GATE_SIGNAL and RETRIEVAL_MODE")
    snap = load_snapshot(REPO_ROOT / s.index_dir, blog=s.blog)
    emb = FastEmbedQueryEmbedder(snap.embed_model, threads=s.onnx_threads, cache_dir=REPO_ROOT / s.model_cache_dir)
    llm = NoAnswerLLM()
    svc = AskService(s, IndexHolder(snap), llm, embedder=emb, bucket=TokenBucket(0.0, 10**9),
                     budget=DailyTokenBudget(0))

    qs = load_questions()
    final_reasons = {r["id"]: r.get("reason")
                     for r in json.loads(FINAL_RESULTS.read_text(encoding="utf-8"))["rows"]}
    final_declines = sorted(i for i, reason in final_reasons.items() if reason == "retrieval_gate")
    decided = await decide_all(svc, llm, [q["question"] for q in qs])
    probes = {name: await decide_all(svc, llm, list(qlist))
              for name, qlist in (("intro", INTRO_PROBES), ("off_topic", OFF_TOPIC_PROBES), ("guard", GUARD_PROBES))}
    rows = eval_rows(qs, decided, final_reasons)
    crit = criteria(rows, final_declines, probes)
    opts = None
    if with_options:
        groups = {"eval": [dict(d, id=q["id"]) for q, d in zip(qs, decided, strict=True)],
                  "intro": probes["intro"], "off_topic": probes["off_topic"]}
        opts = compare_options(snap, emb, s.abstain_threshold, groups)
    return {
        "tool": "eval.gate", "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(), "index_version": snap.version, "embed_model": snap.embed_model,
        "threshold": s.abstain_threshold, "questions": {"file": "eval/questions.md", "n": len(qs)},
        "final_results": "eval/results/final.json", "passed": all(c["passed"] for c in crit),
        "criteria": crit, "rows": rows, "probes": probes, "options": opts,
    }


def git_sha() -> str | None:
    """HEAD's short SHA, "-dirty" when the measured code or questions have uncommitted edits."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "app", "eval/gate.py", "eval/gate_probes.py",
                                "eval/questions.md"], cwd=REPO_ROOT, capture_output=True, timeout=10).returncode == 1
    except (OSError, subprocess.SubprocessError):
        return None
    return (sha + ("-dirty" if dirty else "")) if sha else None


# ----------------------------------------------------------------------------- CLI
def _score(v: float | None) -> str:
    return "-" if v is None else f"{v:.4f}"


def _shown(text: str) -> str:
    """A message as printed: escaped when it holds invisible characters (the tag-character guard probe)."""
    return text if text.isprintable() else ascii(text)


def print_report(report: dict) -> None:
    print(f"gate calibration on index {report['index_version']} ({report['embed_model']}), ABSTAIN_THRESHOLD "
          f"{report['threshold']}, git {report['git_sha']}")
    rows = report["rows"]
    print(f"{len(rows)} eval rows: final.json reason, gate score, declined before -> after")
    for r in rows:
        print(f"  {r['id']:<8} {r['final_reason'] or '-':<17} {_score(r['gate_score'])}  "
              f"{'yes' if r['declined_before'] else 'no'} -> {'yes' if r['declined_after'] else 'no'}"
              + ("  CHANGED" if r["changed"] else ""))
    for name, probes in report["probes"].items():
        print(f"{name} probes ({len(probes)}): decision before -> after, gate score, product intro")
        for p in probes:
            print(f"  {p['before']:<14} -> {p['after']:<14} {_score(p['gate_score'])}  "
                  f"{'intro' if p['product_intro'] else '-    '}  {_shown(p['question'])}")
    for c in report["criteria"]:
        print(f"{'PASS' if c['passed'] else 'FAIL'}  ({c['criterion']}) {c['line']}")
        for f in c["failures"]:
            print(f"      {_shown(f)}")
    if report["options"] is not None:
        print("options, recomputed on the same questions:")
        for line in options_markdown(report["options"]):
            print(line)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Gate calibration: the dense off-topic gate before and after the "
                                             "product-intro override (in process, no server, no LLM)")
    ap.add_argument("--options", action="store_true",
                    help="also recompute the alternatives: threshold, overview chunk, gate-query normalization")
    ap.add_argument("--out", default=str(RESULTS_DIR / "gate-calibration.json"))
    args = ap.parse_args(argv)
    report = asyncio.run(run(args.options))
    print_report(report)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # ASCII-escaped, so the guard probes' invisible payload characters never sit raw in a committed file
    out.write_text(json.dumps(report, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
