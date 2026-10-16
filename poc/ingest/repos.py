"""Shallow-clone the four OLake repos and keep an allowlisted subset of files.

    uv run python -I -m ingest.repos [--allowlist v2|v1]

Writes under $ASK_OLAKE_CACHE:
    repos/<name>/            shallow clones (untrusted data; never executed)
    corpus/repos.jsonl       one record per allowlisted file
    corpus/fetch_repos.json  HEAD SHAs + timings

The allowlist was chosen by inspecting each repo (see poc/README.md):
user-facing docs (READMEs and other *.md), deployment config (helm values.yaml
+ Chart.yaml, docker-compose files, app config YAML), connector specs
(resources/spec.json) and the Go files that define CLI flags and driver /
destination config structs. Tests, CI, vendored code, lockfiles, generated
files, images and upstream (Apache Amoro) docs in olake-fusion are skipped.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from common.config import CORPUS_DIR, GITHUB_ORG, REPO_DIR, REPOS, ensure_dirs, write_json, write_jsonl
from ingest.spec2md import spec_to_markdown

ALLOW: dict[str, list[str]] = {
    "olake": [
        "README.md", "CONTRIBUTING.md",
        "drivers/*/README.md", "destination/**/README.md", "examples/**/README.md",
        "docker-compose.yml", "drivers/*/docker-compose*.yml", "examples/**/docker-compose.yml",
        "destination/iceberg/local-test/docker-compose.yml",
        "drivers/*/resources/spec.json", "destination/*/resources/spec.json",
        "protocol/*.go",                       # cobra commands + CLI flags (root.go)
        "drivers/*/internal/config.go",        # source config structs
        "destination/*/config.go",             # writer config structs
        "utils/ssh.go", "utils/ssl.go", "constants/*.go",
    ],
    "olake-ui": [
        "README.md", "CONTRIBUTING.md", "api-contract.md",
        "server/README.md", "ui/README.md", "ui/CONTRIBUTING.md",
        "docker-compose.yml", "docker-compose-v1.yml", "server/docker-compose.yml",
        "server/conf/app.yaml", "server/internal/appconfig/*.go",
    ],
    "olake-helm": [
        "README.md", "helm/olake/README.md", "helm/olake/UNINSTALL_GUIDE.md",
        "helm/olake/Chart.yaml", "helm/olake/values.yaml", "worker/README.md",
    ],
    "olake-fusion": [
        "README.md", "CONTRIBUTING.md", "docker/README.md",
        "charts/amoro/Chart.yaml", "charts/amoro/values.yaml", "charts/amoro/README.md",
        "dist/src/main/amoro-bin/conf/config.yaml",
        "local-test/docker-compose.yml", "local-test/config.yaml",
    ],
}
# v2 = the research "Tier A" set (about 94K tokens): user-facing READMEs, CLI flags, the connector
# specs behind the UI forms (converted to Markdown field tables), deployment values, Fusion's own
# README + CLAUDE.md sections 1-4 (defaults that differ from upstream Amoro) and the only two
# upstream-Amoro docs that carry "Modified by Datazip" headers. The stale root docker-compose.yml
# of olake is dropped.
ALLOW_V2: dict[str, list[str]] = {
    "olake": [
        "README.md", "drivers/*/README.md", "destination/**/README.md", "examples/**/README.md",
        "protocol/root.go",
        "drivers/*/resources/spec.json", "destination/iceberg/resources/spec.json",
        "destination/parquet/resources/spec.json",
    ],
    "olake-ui": ["README.md", "docker-compose-v1.yml", "server/conf/app.yaml"],
    "olake-helm": [
        "README.md", "helm/olake/README.md", "helm/olake/UNINSTALL_GUIDE.md", "helm/olake/values.yaml",
        "helm/olake/Chart.yaml", "helm/olake/templates/NOTES.txt",
    ],
    "olake-fusion": [
        "README.md", "CLAUDE.md", "docs/user-guides/configurations.md", "docs/admin-guides/deployment.md",
    ],
}
ALLOWLISTS = {"v1": ALLOW, "v2": ALLOW_V2}

DENY = [
    ".github/*", "*/test/*", "*/tests/*", "*/testdata/*", "*_test.go", "*/vendor/*", "*/node_modules/*",
    "*.lock", "*-lock.json", "*-lock.yaml", "go.sum", "*.pb.go", "*.png", "*.svg", "*.jpg",
]


def run_git(args: list[str], cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def clone(name: str) -> dict:
    dest = REPO_DIR / name
    if dest.exists():
        subprocess.run(["rm", "-rf", str(dest)], check=True)
    t0 = time.perf_counter()
    run_git(["clone", "--quiet", "--depth", "1", "--single-branch",
             f"https://github.com/{GITHUB_ORG}/{name}.git", str(dest)])
    elapsed = time.perf_counter() - t0
    sha = run_git(["rev-parse", "HEAD"], cwd=dest)
    branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
    commit_date = run_git(["log", "-1", "--format=%cI"], cwd=dest)
    files = run_git(["ls-files"], cwd=dest).splitlines()
    return {"repo": name, "sha": sha, "branch": branch, "commit_date": commit_date,
            "clone_s": round(elapsed, 2), "tracked_files": len(files), "_files": files}


def allowed(repo: str, path: str, allow: dict[str, list[str]]) -> bool:
    if any(fnmatch.fnmatch(path, d) or fnmatch.fnmatch("/" + path, d) for d in DENY):
        return False
    return any(fnmatch.fnmatch(path, pat) for pat in allow[repo])


def kind_of(path: str) -> str:
    p = path.lower()
    if p.endswith("resources/spec.json"):
        return "spec"
    if p.endswith(".md"):
        return "markdown"
    if p.endswith((".yaml", ".yml")):
        return "yaml"
    if p.endswith(".json"):
        return "json"
    if p.endswith(".go"):
        return "go"
    return "text"


def keep_sections(text: str, first: int, last: int) -> str:
    """Keep only '## <n>.' sections first..last of a Markdown file; other lines are blanked so
    line numbers (and GitHub #L anchors) stay valid."""
    lines = text.split("\n")
    keep, out = False, []
    for ln in lines:
        m = re.match(r"^## (\d+)\.", ln)
        if m:
            keep = first <= int(m.group(1)) <= last
        out.append(ln if keep else "")
    return "\n".join(out)


def prepare_text(repo: str, path: str, text: str) -> tuple[str, str]:
    """Return (kind, text) after the per-file treatment used by allowlist v2."""
    kind = kind_of(path)
    if kind == "spec":
        what = path.split("/")[1]
        side = "source connector" if path.startswith("drivers/") else "destination (writer)"
        title = f"OLake {what} {side}: configuration fields from {path}"
        return "spec", spec_to_markdown(text, title)
    if repo == "olake-fusion" and path == "CLAUDE.md":
        return "markdown", keep_sections(text, 1, 4)
    if path.endswith("NOTES.txt"):  # drop the ASCII-art banner, keep line numbers
        return "text", "\n".join("" if re.fullmatch(r"[\s&*#=_-]*", ln) else ln for ln in text.split("\n"))
    return kind, text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowlist", choices=sorted(ALLOWLISTS), default="v2")
    args = ap.parse_args()
    allow = ALLOWLISTS[args.allowlist]
    ensure_dirs()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        clones = list(pool.map(clone, REPOS))
    clone_wall = time.perf_counter() - t0

    rows = []
    for c in clones:
        repo = c["repo"]
        kept = [f for f in c.pop("_files") if allowed(repo, f, allow)]
        c["allowlisted_files"] = len(kept)
        for path in kept:
            raw = (REPO_DIR / repo / path).read_bytes()
            kind, text = prepare_text(repo, path, raw.decode("utf-8", errors="replace"))
            rows.append({
                "repo": repo,
                "path": path,
                "sha": c["sha"],
                "kind": kind,
                "url": f"https://github.com/{GITHUB_ORG}/{repo}/blob/{c['sha']}/{path}",
                "bytes": len(raw),
                "lines": text.count("\n") + 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "text": text,
            })
    write_jsonl(CORPUS_DIR / "repos.jsonl", rows)
    summary = {
        "clone_wall_s": round(clone_wall, 2),
        "total_wall_s": round(time.perf_counter() - t0, 2),
        "repos": clones,
        "allowlist_version": args.allowlist,
        "allowlist": allow,
        "deny": DENY,
        "files": len(rows),
    }
    write_json(CORPUS_DIR / "fetch_repos.json", summary)
    for c in clones:
        print(c)
    print("files kept:", len(rows), "wall:", summary["total_wall_s"], "s")


if __name__ == "__main__":
    main()
