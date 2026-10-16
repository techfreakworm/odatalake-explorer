"""Query-side models: the fastembed query embedder and the optional FlashRank TinyBERT reranker (RERANK=tinybert).

Both are CPU-bound: callers run them in the threadpool, never on the event loop. A lock serialises calls into each
model (a few ms each), which keeps the tokenizer and the ONNX session single-threaded per call.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

TINYBERT_MODEL = "ms-marco-TinyBERT-L-2-v2"


class FastEmbedQueryEmbedder:
    def __init__(self, model_name: str, *, threads: int, cache_dir: Path):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self.model = TextEmbedding(model_name, cache_dir=str(cache_dir), threads=threads)
        self._lock = threading.Lock()

    def embed_query(self, text: str) -> np.ndarray:
        with self._lock:
            v = np.asarray(next(iter(self.model.query_embed(text))), dtype=np.float32)
        n = float(np.linalg.norm(v))
        return v / n if n else v


class TinyBertReranker:
    """FlashRank ms-marco-TinyBERT-L-2-v2 (max_length 512, as measured in the POC). Imported lazily: with RERANK=off
    the app never imports flashrank."""

    def __init__(self, cache_dir: Path, max_length: int = 512):
        from flashrank import Ranker

        self.ranker = Ranker(model_name=TINYBERT_MODEL, cache_dir=str(cache_dir / "flashrank"),
                             max_length=max_length, log_level="WARNING")
        self._lock = threading.Lock()

    def rerank(self, query: str, chunks: Sequence[Mapping[str, Any]]) -> list[float]:
        from flashrank import RerankRequest

        passages = [{"id": i, "text": str(c.get("text") or "")} for i, c in enumerate(chunks)]
        with self._lock:
            res = self.ranker.rerank(RerankRequest(query=query, passages=passages))
        by_id = {r["id"]: float(r["score"]) for r in res}
        return [by_id.get(i, 0.0) for i in range(len(chunks))]
