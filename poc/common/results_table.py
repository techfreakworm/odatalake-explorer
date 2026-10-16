"""Render the README results table from poc/results/*.json.

    uv run python -I -m common.results_table > /tmp/table.md
"""

from __future__ import annotations

import json

from common.config import RESULTS_DIR


def load(name: str) -> dict | None:
    p = RESULTS_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    rows: list[tuple[str, str, str]] = []
    add = rows.append
    c = load("corpus.json")
    if c:
        d, r, b = c["docs"]["total"], c["repos"]["total"], c.get("blog", {}).get("total")
        f = c["docs_fetch"]
        cmd = "`ingest.docs --blog`, `ingest.repos`, `ingest.stats`"
        add(("Docs pages fetched / errors", f"{d['pages']} / {len(f['errors'])}", cmd))
        add(("Docs fetch wall time (4 concurrent)", f"{f['fetch_wall_s_by_section']['docs']} s for {d['pages']} pages; "
             f"extraction {f['extract_wall_s']} s for all {f['requested']} pages; whole run incl. blog "
             f"{f['total_wall_s']} s", cmd))
        add(("Docs HTML → Markdown", f"{d['html_bytes'] / 1e6:.1f} MB → {d['md_bytes'] / 1e6:.2f} MB", cmd))
        add(("Docs tokens (o200k)", f"{d['tokens']:,} (p50 {d['tokens_per_page_p50']:,}/page, max {d['tokens_per_page_max']:,})", cmd))
        add(("Docs code blocks / tables / tab groups / admonitions",
             f"{d['code_blocks']} / {d['tables']} / {d['tabs']} / {d['admonitions']}", cmd))
        add(("Docs stub pages (<100 tokens)", str(len(d["pages_under_100_tokens"])), cmd))
        add(("Repo files kept (allowlist) / tokens", f"{r['files']} / {r['tokens']:,}", cmd))
        add(("Repo shallow clones wall time", f"{c['repos']['clone_wall_s']} s (4 in parallel)", cmd))
        if b:
            add(("Blog posts / tokens (optional, separate)", f"{b['pages']} / {b['tokens']:,}", cmd))
    ch = load("chunks.json")
    if ch:
        for cfg in ch["configs"]:
            t = cfg["tokens"]
            add((f"Chunks @ target {cfg['target']} (hard max {cfg['hard_max']})",
                 f"{cfg['chunks']} chunks; tokens p50 {t['p50']}, p95 {t['p95']}, max {t['max']}; "
                 f"{cfg['over_hard_max']} over hard max",
                 f"`chunking.chunker --target {cfg['target']}`"))
    for fname, label in (("retrieval.json", "seed"), ("retrieval-canonical.json", "canonical")):
        rt = load(fname)
        if not rt:
            continue
        cmd = "`retrieval.bench` (see Steps)" + (" `--questions ../docs/eval-questions.md --repeat 0 --reuse-embeddings`"
                                                 if label == "canonical" else "")
        add((f"Retrieval eval set ({label})", f"{rt['questions']['n_with_sources']} questions with expected sources", cmd))
        for target, tr in rt["per_target"].items():
            add((f"BM25 index build @ {target}", f"{tr['bm25_build_s']} s for {tr['chunks']} chunks", cmd))
            for m, e in tr["embedding"].items():
                if "embed_full_corpus_s" in e and label == "seed":
                    add((f"Embed {m.split('/')[-1]} @ {target}",
                         f"50 chunks {e['embed_50_chunks_s']} s; full {e['embed_full_corpus_s']} s "
                         f"({e['chunks_per_s']} chunks/s); {e['wordpiece_over_512']} chunks > 512 WordPiece tokens",
                         cmd))
            for name, cfg in tr["configs"].items():
                lat = cfg["latency_ms"].get("total_ms", {})
                latency = f"; latency p50 {lat.get('p50')} ms / p95 {lat.get('p95')} ms" if lat else ""
                add((f"[{label}] @{target} {name}",
                     f"hit@1 {cfg['hit@1']}, hit@5 {cfg['hit@5']}, hit@10 {cfg['hit@10']}, MRR {cfg['mrr@10']}{latency}",
                     cmd))
            if label == "seed" and target == "600":
                add(("Bench process RSS (2 dense + 2 rerankers, after batch-embedding both corpora; not a serving number)",
                     f"{rt['rss_mb']['end']} MB", cmd))
    lt = load("latency_threads.json")
    if lt:
        for label, res in lt["by_threads"].items():
            keys = [k for k in res if k.endswith("_ms")]
            add((f"Query-time latency, onnx threads={label}",
                 "; ".join(f"{k.removesuffix('_ms')} p50 {res[k]['p50']}" for k in keys), "`retrieval.latency`"))
    a = load("answer.json")
    if a:
        cmd = "`answer.probe`"
        for k in ("policy_a_gate", "policy_b_model", "policy_a_or_b"):
            m = a[k]
            extra = f" (threshold {m['threshold']})" if "threshold" in m else ""
            add((f"Abstain {k}{extra}", f"precision {m['precision']}, recall {m['recall']}, "
                 f"false-abstain {m['false_abstain_rate']}", cmd))
        for k, v in a["latency_ms"].items():
            add((f"Answer latency {k}", f"p50 {v['p50']} / p95 {v['p95']} ms", cmd))
        t = a["tokens_per_answer"]
        add(("Tokens per answer (prompt / completion, mean)", f"{t['prompt_mean']} / {t['completion_mean']}", cmd))
        add(("Answered questions citing an expected source", str(a["answered_source_hit_rate"]), cmd))
    g = load("gate-canonical.json")
    if g:
        rows_g = g["per_question"]
        sa = [r for r in rows_g if r["must_abstain"]]
        ans = [r for r in rows_g if r["type"] == "answerable"]
        cmd = "`answer.probe --no-generate --questions ../docs/eval-questions.md`"
        for t in (g["policy_a_gate"]["threshold"], -0.891, -4.0):
            ab = lambda r, t=t: (r["top_score"] if r["top_score"] is not None else -99) < t  # noqa: E731
            add((f"[canonical] MiniLM gate threshold {round(t, 3)}",
                 f"abstain recall {sum(map(ab, sa)) / len(sa):.2f} (unanswerable+out-of-scope), "
                 f"false-abstain {sum(map(ab, ans)) / len(ans):.3f} (answerable)", cmd))
        add(("[canonical] expected source in top-6 passages", str(g["context_hit_rate_top_passages"]), cmd))
    ec = load("eval_run-canonical.json")
    if ec:
        s2 = ec["summary"]
        cmd = "`eval.score --questions ../docs/eval-questions.md --out results/eval_run-canonical.json`"
        add(("[canonical] /ask: schema valid / source hit / behaviour correct",
             f"{s2['schema_valid']} / {s2['source_hit']} / {s2['behaviour_correct']}", cmd))
        add(("[canonical] /ask: abstain recall / false-abstain (answerable)",
             f"{s2['abstain_recall_unanswerable_out_of_scope']} / {s2['false_abstain_rate_answerable']}", cmd))
        add(("[canonical] judge fact coverage / BEHAVIOR pass / contradictions",
             f"{s2['fact_coverage_mean']} / {s2['judged_behavior_pass']} / {s2['contradictions']}", cmd))
        add(("[canonical] /ask latency p50 / p95 (local qwen3:32b, concurrency 4)",
             f"{s2['latency_ms']['p50']} / {s2['latency_ms']['p95']} ms", cmd))
        add(("[canonical] full run wall time", f"{s2['total_wall_s']} s ({s2['ask_wall_s']} s asks + "
             f"{s2['judge_wall_s']} s judge)", cmd))
    v2 = load("eval_run-canonical-v2-subset.json")
    if v2 and ec:
        ids = {r["id"] for r in v2["per_question"]}
        v1rows = [r for r in ec["per_question"] if r["id"] in ids]
        cmd = "`ASK_PROMPT_VERSION=v2` API + `eval.score --ids <25 non-answerable + 10 answerable>`"
        for label, rows_ in (("v1", v1rows), ("v2", v2["per_question"])):
            beh = sum(bool(r["behaviour_correct"]) for r in rows_)
            cov = [r["judge"]["coverage"] for r in rows_ if "coverage" in r.get("judge", {})]
            bp = [r["judge"]["behavior_pass"] for r in rows_ if "behavior_pass" in r.get("judge", {})]
            add((f"[canonical A/B subset, {len(rows_)} rows] prompt {label}",
                 f"behaviour correct {beh}/{len(rows_)}; fact coverage {sum(cov) / len(cov):.3f}; "
                 f"BEHAVIOR pass {sum(bp)}/{len(bp)}", cmd))
    e = load("eval_run.json")
    if e:
        s = e["summary"]
        cmd = "`eval.score`"
        add(("[seed] Scorer: schema valid / source hit / behaviour correct",
             f"{s['schema_valid']} / {s.get('source_hit', s.get('source_hit_rate'))} / {s['behaviour_correct']}", cmd))
        add(("Scorer: judge fact coverage (mean)", str(s["fact_coverage_mean"]), cmd))
        add(("Scorer: /ask latency p50 / p95", f"{s['latency_ms']['p50']} / {s['latency_ms']['p95']} ms", cmd))
        add(("Scorer: full run wall time", f"{s['total_wall_s']} s ({s['ask_wall_s']} s asks + {s['judge_wall_s']} s judge)", cmd))
    ep = load("embed_probe.json")
    if ep:
        cmd = "`api.app` + `http.server` on a second origin, driven in Chrome"
        b = ep["browser_cross_origin"]
        add(("Cross-origin widget: gated answer / LLM answer", f"{b['gated_out_of_scope_question_ms']} ms / "
             f"{b['llm_answer_question_ms']} ms (preflight then POST; preflight cached afterwards)", cmd))
        add(("Strict host CSP (connect-src 'self')", "widget renders, /ask blocked: connect-src violation", cmd))
        r = ep["api_rss_mb"]
        add(("API RSS (bge-base + MiniLM + BM25)", f"{r['after_one_query']} MB after 1 query, "
             f"{r['after_scorer_run_concurrency_4']} MB after concurrency-4 run; startup {ep['api_startup_s']} s", cmd))
    fr = load("freshness.json")
    if fr:
        cmd = "`freshness.probe`"
        add(("olake.io conditional GET", f"If-None-Match → {fr['docs_page']['if_none_match']['status']} in "
             f"{fr['docs_page']['if_none_match']['ms']} ms; ETag = deploy mtime + size", cmd))
        gu, ga = fr["github_unauthenticated"], fr["github_authenticated"]
        add(("GitHub 304 counts against rate limit?", f"unauthenticated: yes ({gu['conditional_cost']} used for 3); "
             f"token: {'no' if isinstance(ga, dict) and ga['conditional_cost'] == 0 else ga}", cmd))
        ms = [v["ms"] for v in fr["git_ls_remote"].values()]
        add(("git ls-remote HEAD check", f"{min(ms):.0f}-{max(ms):.0f} ms per repo, no API quota", cmd))
    print("| Metric | Value | Command |\n|---|---|---|")
    for m, v, cmd in rows:
        print(f"| {m} | {v} | {cmd} |")


if __name__ == "__main__":
    main()
