"""Shared fixtures for the ingest/index tests: no network, no model downloads."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from ingest import config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return read


class FakeEmbedder:
    """Deterministic 16-dim vectors from the text hash; records every text it embeds."""

    calls: list[str] = []

    def __init__(self, model: str = "fake-model", threads=None):
        self.model_name = model

    def embed_passages(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        FakeEmbedder.calls.extend(texts)
        rows = []
        for t in texts:
            d = hashlib.sha256(t.encode()).digest()
            v = np.frombuffer(d[:16], dtype=np.uint8).astype(np.float32) + 1.0
            rows.append(v / np.linalg.norm(v))
        return np.stack(rows).astype(np.float32)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Cache, poll state and embedding cache under tmp_path; the fake embedder instead of fastembed."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(config, "CACHE_DIR", cache)
    monkeypatch.setattr(config, "HTML_DIR", cache / "html")
    monkeypatch.setattr(config, "GITHUB_DIR", cache / "github")
    monkeypatch.setattr(config, "REPOS_DIR", cache / "repos")
    monkeypatch.setattr(config, "EMBED_CACHE_DIR", cache / "embeddings")
    monkeypatch.setattr(config, "REFRESH_STATE", cache / "refresh_state.json")
    import index.embed
    monkeypatch.setattr(index.embed, "Embedder", FakeEmbedder)
    FakeEmbedder.calls = []
    return tmp_path
