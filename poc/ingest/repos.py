"""Shallow-clone the four OLake repos and keep an allowlisted subset of files.

    uv run python -I -m ingest.repos

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

import fnmatch
import hashlib
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from common.config import CORPUS_DIR, GITHUB_ORG, REPO_DIR, REPOS, ensure_dirs, write_json, write_jsonl

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


def allowed(repo: str, path: str) -> bool:
    if any(fnmatch.fnmatch(path, d) or fnmatch.fnmatch("/" + path, d) for d in DENY):
        return False
    return any(fnmatch.fnmatch(path, pat) for pat in ALLOW[repo])


def kind_of(path: str) -> str:
    p = path.lower()
    if p.endswith(".md"):
        return "markdown"
    if p.endswith((".yaml", ".yml")):
        return "yaml"
    if p.endswith(".json"):
        return "json"
    if p.endswith(".go"):
        return "go"
    return "text"


def main() -> None:
    ensure_dirs()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        clones = list(pool.map(clone, REPOS))
    clone_wall = time.perf_counter() - t0

    rows = []
    for c in clones:
        repo = c["repo"]
        kept = [f for f in c.pop("_files") if allowed(repo, f)]
        c["allowlisted_files"] = len(kept)
        for path in kept:
            raw = (REPO_DIR / repo / path).read_bytes()
            text = raw.decode("utf-8", errors="replace")
            rows.append({
                "repo": repo,
                "path": path,
                "sha": c["sha"],
                "kind": kind_of(path),
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
        "allowlist": ALLOW,
        "deny": DENY,
        "files": len(rows),
    }
    write_json(CORPUS_DIR / "fetch_repos.json", summary)
    for c in clones:
        print(c)
    print("files kept:", len(rows), "wall:", summary["total_wall_s"], "s")


if __name__ == "__main__":
    main()
