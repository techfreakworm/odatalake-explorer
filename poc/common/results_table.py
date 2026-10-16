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
        add(("Docs fetch wall time (4 concurrent)", f"{f['fetch_wall_s_by_section']['docs']} s fetch + extraction "
             f"(all {f['requested']} pages incl. blog: {f['total_wall_s']} s)", cmd))
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
    rt = load("retrieval.json")
    if rt:
        cmd = "`retrieval.bench` (see Steps)"
        for target, tr in rt["per_target"].items():
            add((f"BM25 index build @ {target}", f"{tr['bm25_build_s']} s for {tr['chunks']} chunks", cmd))
            for m, e in tr["embedding"].items():
                if "embed_full_corpus_s" in e:
                    add((f"Embed {m.split('/')[-1]} @ {target}",
                         f"50 chunks {e['embed_50_chunks_s']} s; full {e['embed_full_corpus_s']} s "
                         f"({e['chunks_per_s']} chunks/s); {e['wordpiece_over_512']} chunks > 512 WordPiece tokens",
                         cmd))
            for name, cfg in tr["configs"].items():
                lat = cfg["latency_ms"].get("total_ms", {})
                add((f"@{target} {name}",
                     f"hit@1 {cfg['hit@1']}, hit@5 {cfg['hit@5']}, hit@10 {cfg['hit@10']}, MRR {cfg['mrr@10']}; "
                     f"latency p50 {lat.get('p50')} ms / p95 {lat.get('p95')} ms", cmd))
        add(("Retrieval process RSS (all models loaded)", f"{rt['rss_mb']['end']} MB", cmd))
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
    e = load("eval_run.json")
    if e:
        s = e["summary"]
        cmd = "`eval.score`"
        add(("Scorer: schema valid / source hit / behaviour correct", f"{s['schema_valid']} / {s['source_hit_rate']} / "
             f"{s['behaviour_correct']}", cmd))
        add(("Scorer: judge fact coverage (mean)", str(s["fact_coverage_mean"]), cmd))
        add(("Scorer: /ask latency p50 / p95", f"{s['latency_ms']['p50']} / {s['latency_ms']['p95']} ms", cmd))
        add(("Scorer: full run wall time", f"{s['total_wall_s']} s ({s['ask_wall_s']} s asks + {s['judge_wall_s']} s judge)", cmd))
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
