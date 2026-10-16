"""Index parameters from the environment (contract I4) plus the fixed chunker settings.

INDEX_DIR, EMBED_MODEL, GITHUB_TOKEN and ONNX_THREADS come from env; everything else is set by
the lead in CLAUDE.md "Parameters" and changes only through the lead.
"""

from __future__ import annotations

import os

from ingest import config as ingest_config  # noqa: F401  (sets the model/tokenizer cache env defaults)
from ingest.config import repo_path

INDEX_DIR = repo_path(os.environ.get("INDEX_DIR") or "data/index")
EMBED_MODEL = os.environ.get("EMBED_MODEL") or "BAAI/bge-small-en-v1.5"
ONNX_THREADS = int(os.environ["ONNX_THREADS"]) if os.environ.get("ONNX_THREADS", "").strip().isdigit() else None


def github_token() -> str | None:
    """Optional. Read at call time and never logged or written anywhere."""
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    return tok or None


# Chunker (CLAUDE.md "Parameters"): 300-token target, 450 hard max, o200k_base tokens.
CHUNK_TARGET = 300
CHUNK_HARD_MAX = 450
TOKENIZER = "o200k_base"

# Instruction prefixes the model authors recommend for short retrieval queries (passages get none).
QUERY_PREFIX = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
}


def query_prefix(model: str) -> str:
    return QUERY_PREFIX.get(model, "")
