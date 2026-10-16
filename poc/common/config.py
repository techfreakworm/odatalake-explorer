"""Shared paths and settings. Nothing machine-specific lives here: the cache
location comes from the ASK_OLAKE_CACHE environment variable."""

from __future__ import annotations

import json
import os
from pathlib import Path

POC_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = POC_DIR / "results"
EVAL_DIR = POC_DIR / "eval"

CACHE = Path(os.environ.get("ASK_OLAKE_CACHE", "~/.cache/ask-olake")).expanduser()
HTML_DIR = CACHE / "html"            # raw fetched HTML (untrusted data)
REPO_DIR = CACHE / "repos"           # shallow clones (untrusted data)
CORPUS_DIR = CACHE / "corpus"        # extracted markdown + manifests
INDEX_DIR = CACHE / "index"          # chunk files, embeddings
MODEL_DIR = Path(os.environ.get("FASTEMBED_CACHE_PATH", CACHE / "models"))

USER_AGENT = "ask-olake-research-poc/0.1 (hackathon research; polite crawler, max 4 concurrent)"
MAX_CONCURRENCY = 4

SITEMAP_URL = "https://olake.io/sitemap.xml"
GITHUB_ORG = "datazip-inc"
REPOS = ["olake", "olake-ui", "olake-helm", "olake-fusion"]

# OpenAI-compatible LLM endpoint (ollama locally; swap for the event provider).
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:32b")


def ensure_dirs() -> None:
    for d in (HTML_DIR, REPO_DIR, CORPUS_DIR, INDEX_DIR, RESULTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
