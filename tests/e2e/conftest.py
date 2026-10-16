"""e2e harness: holds the team's ollama lock, starts uvicorn on a free port against the real index and a local
ollama, waits for /readyz, and stops it afterwards.

Needs data/index/CURRENT and the LLM in tests/e2e/local-ollama.env (or E2E_ENV_FILE). Missing prerequisites skip
the tests, or fail them when E2E_REQUIRED=1 (scripts/verify.sh sets it). OLLAMA_LOCK_HELD=1 means the caller
already holds .cache/ollama.lock (verify.sh takes it around this step).
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
LOCK = REPO / ".cache" / "ollama.lock"


def _missing(reason: str):
    if os.environ.get("E2E_REQUIRED") == "1":
        pytest.fail(reason, pytrace=False)
    pytest.skip(reason)


def _read_env_file(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@pytest.fixture(scope="session")
def e2e_env() -> dict[str, str]:
    path = Path(os.environ.get("E2E_ENV_FILE") or Path(__file__).with_name("local-ollama.env"))
    env = _read_env_file(path)
    env.update({k: v for k, v in os.environ.items() if k in env and v})  # explicit env wins
    env["CANARY"] = secrets.token_hex(8)
    env["DEBUG"] = "1"
    if not (REPO / env.get("INDEX_DIR", "data/index") / "CURRENT").is_file():
        _missing(f"no index: build one first (uv run python -m index.build); looked in {env.get('INDEX_DIR')}")
    base = env.get("LLM_BASE_URL", "").rstrip("/")
    try:
        models = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {env.get('LLM_API_KEY', '')}"},
                           timeout=5).json()
        ids = {m.get("id") for m in models.get("data", [])}
    except Exception as e:  # noqa: BLE001
        _missing(f"LLM endpoint {base} unreachable: {type(e).__name__}")
    if env.get("LLM_MODEL") not in ids:
        _missing(f"model {env.get('LLM_MODEL')} not served by {base}")
    return env


@pytest.fixture(scope="session")
def ollama_lock():
    if os.environ.get("OLLAMA_LOCK_HELD") == "1":
        yield
        return
    LOCK.parent.mkdir(exist_ok=True)
    deadline = time.time() + float(os.environ.get("E2E_LOCK_WAIT_S", "600"))
    while True:
        try:
            LOCK.mkdir()
            break
        except FileExistsError:
            if time.time() > deadline:
                owner = (LOCK / "owner").read_text().strip() if (LOCK / "owner").exists() else "unknown"
                _missing(f"ollama lock still held by: {owner}")
            time.sleep(5)
    (LOCK / "owner").write_text(f"api: pytest e2e (pid {os.getpid()})\n")
    try:
        yield
    finally:
        shutil.rmtree(LOCK, ignore_errors=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server(e2e_env, ollama_lock, tmp_path_factory):
    port = _free_port()
    log_path = tmp_path_factory.mktemp("e2e") / "server.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "CANARY"))}
    env.update(e2e_env)
    with open(log_path, "w") as log:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                 "--port", str(port)], cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.time() + 120
            while True:
                if proc.poll() is not None:
                    pytest.fail(f"server exited early:\n{log_path.read_text()[-3000:]}", pytrace=False)
                try:
                    if httpx.get(f"{base}/readyz", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.time() > deadline:
                    pytest.fail(f"server not ready after 120 s:\n{log_path.read_text()[-3000:]}", pytrace=False)
                time.sleep(0.25)
            yield {"base": base, "canary": e2e_env["CANARY"], "log": log_path}
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
