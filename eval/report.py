"""Markdown summary of an eval results file, for the README (every number names its file).

    uv run python -m eval.report eval/results/<name>.json [more.json ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _v(x) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def index_version(r: dict) -> str:
    idx = (r.get("healthz") or {}).get("index")
    return str(idx.get("version")) if isinstance(idx, dict) else "?"


def _degraded(s: dict) -> str:
    d = s.get("degraded") or {}
    if not d:
        return "-"
    reasons = ", ".join(f"{k} {v}" for k, v in sorted((d.get("by_reason") or {}).items()))
    return f"{d.get('count', 0)}" + (f" ({reasons})" if reasons else "")


def full_table(r: dict, name: str) -> str:
    s = r["summary"]
    a, fa, fm = s["abstain_recall"], s["false_abstain_answerable"], s["false_abstain_must_answer"]
    judge = r.get("judge") or {}
    lat = s["latency_ms"]
    rows = [
        ("Rows", f"{r['questions']['n']}"),
        ("Schema valid", _v(s["schema_valid"])),
        ("Contract failures", _v(s["contract_failures"])),
        ("Behaviour correct", _v(s["behaviour_correct"])),
        ("Degraded answers (server fell back to listing pages)", _degraded(s)),
        ("Source hit rate", _v(s["source_hit_rate"])),
        ("Fact coverage (judge)", _v(s["fact_coverage_mean"])),
        ("BEHAVIOR pass (judge)", _v(s["behavior_pass_rate"])),
        ("Contradictions (judge)", _v(s["contradictions"])),
        ("Abstain recall (unanswerable + out-of-scope)", f"{a['count']}/{a['n']} ({_v(a['rate'])})"
         + (f"; degraded, counted as missed: {', '.join(a['degraded_counted_as_missed'])}"
            if a.get("degraded_counted_as_missed") else "")),
        ("False abstain, answerable", f"{fa['count']}/{fa['n']} ({_v(fa['rate'])})"),
        ("False abstain, all must-answer", f"{fm['count']}/{fm['n']} ({_v(fm['rate'])})"),
        ("Latency p50 / p95 / max (ms)", f"{_v(lat['p50'])} / {_v(lat['p95'])} / {_v(lat['max'])}"),
        ("Wall time ask / judge / total (s)", f"{s['ask_wall_s']} / {s['judge_wall_s']} / {s['total_wall_s']}"),
    ]
    out = [f"Results: `{name}` (index {index_version(r)}, concurrency {r['flags'].get('concurrency')}"
           + (f", judge {judge.get('model')}" if judge else ", no judge") + ")", "",
           "| Metric | Value |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in rows]
    if judge.get("caveat"):
        out += ["", f"Judge caveat: {judge['caveat']}."]
    out += ["", "| Type | n | Schema | Behaviour | Source hit | Facts | BEHAVIOR |", "|---|---|---|---|---|---|---|"]
    for t, v in r["by_type"].items():
        out.append(f"| {t} | {v['n']} | {_v(v['schema_valid'])} | {_v(v['behaviour_correct'])} | "
                   f"{_v(v['source_hit_rate'])} | {_v(v['fact_coverage_mean'])} | {_v(v['behavior_pass_rate'])} |")
    return "\n".join(out)


def retrieval_table(r: dict, name: str) -> str:
    s = r["summary"]
    out = [f"Results: `{name}` (retrieval only, index {index_version(r)}"
           + (f", {r['label']}" if r.get("label") else "") + ")", "",
           "| Rows | hit@1 | hit@3 | hit@5 | hit@10 | MRR@10 |", "|---|---|---|---|---|---|",
           f"| {s['n']} | {_v(s['hit@1'])} | {_v(s['hit@3'])} | {_v(s['hit@5'])} | {_v(s['hit@10'])} | "
           f"{_v(s['mrr@10'])} |", "", "| Category | n | hit@1 | hit@10 | MRR@10 |", "|---|---|---|---|---|"]
    for c, v in r["by_category"].items():
        out.append(f"| {c} | {v['n']} | {_v(v['hit@1'])} | {_v(v['hit@10'])} | {_v(v['mrr@10'])} |")
    gc = s.get("gate_calibration") or {}
    if gc.get("available"):
        out += ["", f"Gate calibration: lowest must-answer gate score {gc['lowest_must_answer']} ({gc['lowest_must_answer_id']}) "
                    f"minus 0.02 gives {gc['threshold']}; {gc['must_abstain_below']} of {gc['must_abstain_scored']} "
                    f"must-abstain rows score below it."]
    return "\n".join(out)


def report(path: Path) -> str:
    r = json.loads(path.read_text(encoding="utf-8"))
    name = _rel(path)
    return retrieval_table(r, name) if r.get("mode") == "retrieval" else full_table(r, name)


def main(argv: list[str] | None = None) -> None:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        raise SystemExit("usage: python -m eval.report <results.json> [more.json ...]")
    print("\n\n".join(report(p) for p in paths))


if __name__ == "__main__":
    main()
