"""Corpus statistics -> poc/results/corpus.json

    uv run python -I -m ingest.stats
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

import tiktoken

from common.config import CORPUS_DIR, RESULTS_DIR, read_jsonl, write_json

ENC = tiktoken.get_encoding("o200k_base")


def ntok(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


def md_counts(md: str) -> dict:
    fences = re.findall(r"^(```+|~~~+)", md, flags=re.M)
    tables = re.findall(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$|^\|---\|", md, flags=re.M)
    return {"code_blocks": len(fences) // 2, "tables": len(tables)}


def summarize_pages(rows: list[dict], key) -> dict:
    groups = defaultdict(lambda: {"pages": 0, "md_bytes": 0, "tokens": 0, "code_blocks": 0, "tables": 0})
    total = {"pages": 0, "html_bytes": 0, "md_bytes": 0, "tokens": 0, "code_blocks": 0, "tables": 0,
             "tabs": 0, "admonitions": 0, "headings": 0}
    largest = []
    for r in rows:
        md = r["markdown"]
        t = ntok(md)
        b = len(md.encode())
        st = r["extract_stats"]
        g = groups[key(r)]
        g["pages"] += 1
        g["md_bytes"] += b
        g["tokens"] += t
        g["code_blocks"] += st["code_blocks"]
        g["tables"] += st["tables"]
        total["pages"] += 1
        total["html_bytes"] += r.get("bytes_html", 0)
        total["md_bytes"] += b
        total["tokens"] += t
        for k in ("code_blocks", "tables", "tabs", "admonitions", "headings"):
            total[k] += st[k]
        largest.append({"url": r["url"], "tokens": t, "md_bytes": b})
    largest.sort(key=lambda x: -x["tokens"])
    toks = sorted(x["tokens"] for x in largest)
    total["tokens_per_page_p50"] = toks[len(toks) // 2] if toks else 0
    total["tokens_per_page_max"] = toks[-1] if toks else 0
    total["pages_under_100_tokens"] = [x["url"] for x in largest if x["tokens"] < 100]
    return {
        "total": total,
        "by_section": dict(sorted(groups.items(), key=lambda kv: -kv[1]["tokens"])),
        "largest": largest[:10],
    }


def docs_section(r: dict) -> str:
    parts = r["url"].split("/docs/", 1)[1].strip("/").split("/")
    if parts[0] == "fusion":
        return "fusion/" + (parts[1] if len(parts) > 1 else "")
    return parts[0] or "(index)"


def main() -> None:
    out: dict = {"tokenizer": "tiktoken o200k_base"}
    fetch = json.loads((CORPUS_DIR / "fetch_docs.json").read_text())
    out["docs_fetch"] = fetch
    docs = read_jsonl(CORPUS_DIR / "docs.jsonl")
    out["docs"] = summarize_pages(docs, docs_section)
    blog_path = CORPUS_DIR / "blog.jsonl"
    if blog_path.exists():
        blog = read_jsonl(blog_path)
        out["blog"] = summarize_pages(blog, lambda r: "blog")
        del out["blog"]["by_section"]

    # Fusion coverage: which /docs/fusion pages carry real content
    fus = sorted(({"url": r["url"], "tokens": ntok(r["markdown"])} for r in docs if "/docs/fusion/" in r["url"]),
                 key=lambda x: -x["tokens"])
    for f in fus:
        f["stub"] = f["tokens"] < 100
    out["fusion_pages"] = {"pages": len(fus), "stubs": sum(f["stub"] for f in fus),
                           "content_tokens": sum(f["tokens"] for f in fus), "per_page": fus}

    rel_path = CORPUS_DIR / "releases.jsonl"
    if rel_path.exists():
        rels = read_jsonl(rel_path)
        per = defaultdict(lambda: {"releases": 0, "tokens": 0, "newest": None})
        for r in rels:
            p_ = per[r["repo"]]
            p_["releases"] += 1
            p_["tokens"] += ntok(r["markdown"])
            p_["newest"] = p_["newest"] or r["tag"]
        out["releases"] = {"total": {"releases": len(rels), "tokens": sum(v["tokens"] for v in per.values())},
                           "per_repo": dict(per)}

    repos = read_jsonl(CORPUS_DIR / "repos.jsonl")
    rfetch = json.loads((CORPUS_DIR / "fetch_repos.json").read_text())
    per_repo = {}
    for c in rfetch["repos"]:
        per_repo[c["repo"]] = {"sha": c["sha"], "branch": c["branch"], "commit_date": c["commit_date"],
                               "clone_s": c["clone_s"], "tracked_files": c["tracked_files"],
                               "files": 0, "bytes": 0, "tokens": 0, "by_kind": defaultdict(lambda: [0, 0])}
    largest = []
    code_blocks = tables = 0
    for r in repos:
        t = ntok(r["text"])
        pr = per_repo[r["repo"]]
        pr["files"] += 1
        pr["bytes"] += r["bytes"]
        pr["tokens"] += t
        pr["by_kind"][r["kind"]][0] += 1
        pr["by_kind"][r["kind"]][1] += t
        if r["kind"] == "markdown":
            c = md_counts(r["text"])
            code_blocks += c["code_blocks"]
            tables += c["tables"]
        largest.append({"file": f"{r['repo']}/{r['path']}", "tokens": t, "bytes": r["bytes"]})
    for pr in per_repo.values():
        pr["by_kind"] = {k: {"files": v[0], "tokens": v[1]} for k, v in pr["by_kind"].items()}
    largest.sort(key=lambda x: -x["tokens"])
    out["repos"] = {
        "allowlist_version": rfetch.get("allowlist_version", "v1"),
        "clone_wall_s": rfetch["clone_wall_s"],
        "total": {"files": len(repos), "bytes": sum(r["bytes"] for r in repos),
                  "tokens": sum(p["tokens"] for p in per_repo.values()),
                  "markdown_code_blocks": code_blocks, "markdown_tables": tables},
        "per_repo": per_repo,
        "largest": largest[:10],
    }
    rel_tok = out.get("releases", {}).get("total", {}).get("tokens", 0)
    out["combined_core_index"] = {
        "what": "docs + repo allowlist + release notes (blog is a separate tier)",
        "documents": out["docs"]["total"]["pages"] + len(repos) + out.get("releases", {}).get("total", {}).get("releases", 0),
        "tokens": out["docs"]["total"]["tokens"] + out["repos"]["total"]["tokens"] + rel_tok,
        "fetch_wall_s": round(fetch["total_wall_s"] + rfetch["total_wall_s"], 2),
    }
    write_json(RESULTS_DIR / "corpus.json", out)
    print(json.dumps({k: (v["total"] if isinstance(v, dict) and "total" in v else v)
                      for k, v in out.items() if k not in ("docs_fetch", "fusion_pages")}, indent=1))
    print("fusion pages:", {k: v for k, v in out["fusion_pages"].items() if k != "per_page"})


if __name__ == "__main__":
    main()
