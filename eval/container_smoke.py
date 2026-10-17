"""Measured container and pipeline numbers for the README -> eval/results/container-smoke.json

    uv run python -m eval.container_smoke [--image ask-olake:local] [--port 8766] [--skip-build] [--amd64]
                                          [--note TEXT] [--out FILE]

No LLM and no keys (the container answers /ask with its degraded 200, so no model is called):
1. image: `docker image inspect` (size, architecture)
2. container: `docker run -d -p 127.0.0.1:PORT:8080 IMAGE`; the time from `docker run` to /readyz 200; /healthz;
   RSS from `docker stats` idle and after five /ask calls (status, exact keys and X-Ask-Reason recorded)
3. refresh: `uv run python -m index.refresh --check --json` on the host (wall time and the "changed" verdict)
4. builds from the cached pages, into .cache/index-ab/cold (data/index is not touched):
   cold `uv run python -m index.build --offline --no-reuse --out-root .cache/index-ab/cold` (every chunk embedded),
   then warm, the same without --no-reuse and with --prune (every vector reused)
5. with --amd64: `docker build --platform linux/amd64` of the same Dockerfile (exit code, time, size; the check
   image is removed afterwards). --amd64-only runs just this and merges it into an existing --out file, so the
   slow emulated build can run apart from the timed steps.
It refuses a busy port and removes only the container it started. The file records the date, the git SHA, the host
and the exact commands.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]


def sh(args: list[str], timeout: float = 900, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=timeout, check=check)


def mib(usage: str) -> float | None:
    """"208.3MiB / 7.746GiB" -> 208.3"""
    m = re.match(r"\s*([\d.]+)\s*([KMG]i?B)", usage or "")
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2)
    return round(val * {"KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit], 1)


def port_busy(port: int) -> bool:
    return sh(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], check=False).returncode == 0


def measure_container(image: str, port: int) -> dict:
    if port_busy(port):
        raise SystemExit(f"port {port} is in use: refusing to start a container there")
    inspect = json.loads(sh(["docker", "image", "inspect", image]).stdout)[0]
    name = f"ask-olake-ingest-smoke-{os.getpid()}"
    out = {"image": image, "image_id": inspect["Id"][:19], "architecture": inspect.get("Architecture"),
           "image_size_mb": round(inspect["Size"] / 1e6, 1)}
    t0 = time.perf_counter()
    sh(["docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8080", image])
    try:
        base = f"http://127.0.0.1:{port}"
        ready = None
        with httpx.Client(timeout=5) as c:
            for _ in range(600):
                try:
                    if c.get(f"{base}/readyz").status_code == 200:
                        ready = time.perf_counter() - t0
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            if ready is None:
                raise SystemExit(f"{name} never became ready: docker logs {name}")
            out["readyz_s_from_docker_run"] = round(ready, 2)
            health = c.get(f"{base}/healthz").json()
            out["healthz"] = {k: health.get(k) for k in ("status", "git_sha", "index")}
            time.sleep(2)
            out["rss_idle_mib"] = mib(sh(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", name]).stdout)
            asks = []
            for q in ("How do I install OLake?", "Does OLake support Oracle CDC?", "REST catalog configuration",
                      "What sync modes does Kafka support?", "How do I set up Glue?"):
                t1 = time.perf_counter()
                r = c.post(f"{base}/ask", json={"question": q})
                body = r.json()
                asks.append({"status": r.status_code, "ms": round((time.perf_counter() - t1) * 1000, 1),
                             "exact_keys": isinstance(body, dict) and set(body) == {"answer", "sources"},
                             "reason": r.headers.get("x-ask-reason")})
            out["asks_without_llm"] = asks
            out["rss_after_5_asks_mib"] = mib(sh(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}",
                                                  name]).stdout)
    finally:
        sh(["docker", "rm", "-f", name], check=False)
    return out


def measure_refresh() -> dict:
    t0 = time.perf_counter()
    r = sh(["uv", "run", "python", "-m", "index.refresh", "--check", "--json"], timeout=600, check=False)
    wall = time.perf_counter() - t0
    try:
        res = json.loads(r.stdout[r.stdout.find("{"):])
    except json.JSONDecodeError:
        res = {}
    return {"command": "uv run python -m index.refresh --check --json", "wall_s": round(wall, 2),
            "refresh_seconds": res.get("seconds"), "changed": res.get("changed"),
            "sitemap_status": (res.get("docs") or {}).get("sitemap_status"), "errors": res.get("errors")}


def measure_build(extra: list[str]) -> dict:
    cmd = ["uv", "run", "python", "-m", "index.build", "--offline", *extra, "--out-root", ".cache/index-ab/cold"]
    t0 = time.perf_counter()
    r = sh(cmd, timeout=1800, check=False)
    wall = time.perf_counter() - t0
    m = re.search(r"built in ([\d.]+)s: (\d+) chunks; (\d+) embedded, (\d+) vectors reused", r.stdout)
    return {"command": " ".join(cmd), "wall_s": round(wall, 1), "exit": r.returncode,
            "build_s": float(m.group(1)) if m else None, "chunks": int(m.group(2)) if m else None,
            "embedded": int(m.group(3)) if m else None, "reused": int(m.group(4)) if m else None}


def measure_amd64(git_sha: str) -> dict:
    tag = "ask-olake:amd64-check"
    cmd = ["docker", "build", "--platform", "linux/amd64", "-t", tag, "--build-arg", f"GIT_SHA={git_sha}", "."]
    t0 = time.perf_counter()
    r = sh(cmd, timeout=3600, check=False)
    out = {"command": " ".join(cmd), "exit": r.returncode, "wall_s": round(time.perf_counter() - t0, 1)}
    if r.returncode == 0:
        inspect = json.loads(sh(["docker", "image", "inspect", tag]).stdout)[0]
        out.update(architecture=inspect.get("Architecture"), image_size_mb=round(inspect["Size"] / 1e6, 1))
        sh(["docker", "image", "rm", tag], check=False)
    else:
        out["stderr_tail"] = r.stderr[-600:]
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Container and pipeline measurements for the README")
    ap.add_argument("--image", default="ask-olake:local")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--skip-build", action="store_true", help="skip the index build timings")
    ap.add_argument("--amd64", action="store_true", help="also check that the image builds for linux/amd64")
    ap.add_argument("--amd64-only", action="store_true", help="only the amd64 check, merged into the --out file")
    ap.add_argument("--out", default="eval/results/container-smoke.json")
    ap.add_argument("--note", default="", help="measurement conditions, e.g. other load on the machine")
    args = ap.parse_args(argv)
    git_sha = sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    out = REPO / args.out
    if args.amd64_only:
        report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        report["amd64_build"] = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "git_sha": git_sha, **measure_amd64(git_sha)}
        out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(report["amd64_build"], indent=1))
        sys.exit(0)
    report = {
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "host": {"platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count()},
        "note": args.note or None,
        "commands": {"container": f"docker run -d -p 127.0.0.1:{args.port}:8080 {args.image} (no keys)",
                     "rss": "docker stats --no-stream --format '{{.MemUsage}}'"},
        "container": measure_container(args.image, args.port),
        "refresh_check": measure_refresh(),
    }
    if not args.skip_build:
        report["cold_build"] = measure_build(["--no-reuse"])
        report["warm_build"] = measure_build(["--prune"])
    if args.amd64:
        report["amd64_build"] = measure_amd64(git_sha)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    sys.exit(0)


if __name__ == "__main__":
    main()
