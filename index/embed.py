"""Passage embeddings: fastembed (ONNX, CPU) with EMBED_MODEL, float32, rows L2-normalized.

Vectors are reused for every chunk whose (hash, model) is unchanged: first from the active index
(data/index/CURRENT, when it was built with the same model), then from a cache in
.cache/embeddings/, so a rebuild or a refresh only embeds new or changed chunks. The chunk text
(context header + body) is what gets embedded, and `hash` is the sha256 of that text.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import numpy as np

from index.config import EMBED_MODEL, ONNX_THREADS
from ingest import config as ingest_config

log = logging.getLogger("index.embed")

CACHE_LIMIT = 50_000


class Embedder:
    def __init__(self, model: str = EMBED_MODEL, threads: int | None = ONNX_THREADS):
        self.model_name = model
        self.threads = threads
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name, cache_dir=str(ingest_config.MODELS_DIR), threads=self.threads)
        return self._model

    def embed_passages(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        # length-sorted batches waste less compute on padding; rows go back in input order
        order = np.argsort([len(t) for t in texts], kind="stable")
        vecs = np.asarray(list(self.model.passage_embed([texts[i] for i in order], batch_size=batch_size)),
                          dtype=np.float32)
        out = np.empty_like(vecs)
        out[order] = vecs
        return normalize(out)

    @property
    def dim(self) -> int:
        return int(np.asarray(next(iter(self.model.passage_embed(["dim probe"])))).shape[-1])


def normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


def model_slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def cache_file(model: str) -> Path:
    return ingest_config.EMBED_CACHE_DIR / f"{model_slug(model)}.npz"


def load_cache(model: str) -> dict[str, np.ndarray]:
    p = cache_file(model)
    if not p.exists():
        return {}
    try:
        data = np.load(p, allow_pickle=False)
        return {str(h): v for h, v in zip(data["hashes"], data["vectors"])}
    except Exception as e:  # a corrupt cache only costs a re-embed
        log.warning("embedding cache unreadable (%s); ignoring it", e)
        return {}


def save_cache(model: str, vectors: dict[str, np.ndarray], keep_first: list[str] | None = None) -> None:
    items = list(vectors.items())
    if len(items) > CACHE_LIMIT:  # keep the current build's vectors, then the rest up to the limit
        keep = set(keep_first or [])
        items = [kv for kv in items if kv[0] in keep] + [kv for kv in items if kv[0] not in keep]
        items = items[:CACHE_LIMIT]
    if not items:
        return
    p = cache_file(model)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez(tmp, hashes=np.array([h for h, _ in items]), vectors=np.stack([v for _, v in items]).astype(np.float32))
    tmp.replace(p)


def vectors_from_index(version_dir: Path, model: str) -> dict[str, np.ndarray]:
    """{hash: vector} from an index version built with `model` ({} otherwise)."""
    try:
        manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("embed_model") != model:
            return {}
        matrix = np.load(version_dir / "embeddings.npy", allow_pickle=False)
        with (version_dir / "chunks.jsonl").open(encoding="utf-8") as f:
            hashes = [json.loads(line)["hash"] for line in f if line.strip()]
        if len(hashes) != matrix.shape[0]:
            log.warning("index %s: %d chunks but %d vectors; not reused", version_dir.name, len(hashes), matrix.shape[0])
            return {}
        return {h: matrix[i] for i, h in enumerate(hashes)}
    except FileNotFoundError:
        return {}


def embed_chunks(chunks: list[dict], *, model: str = EMBED_MODEL, reuse: dict[str, np.ndarray] | None = None,
                 embedder: Embedder | None = None, use_cache: bool = True) -> tuple[np.ndarray, dict]:
    """Matrix [n_chunks, dim] (row i = chunks[i]) plus stats {reused, embedded, seconds, dim}."""
    pool: dict[str, np.ndarray] = {}
    if use_cache:
        pool.update(load_cache(model))
    pool.update(reuse or {})
    missing = [i for i, c in enumerate(chunks) if c["hash"] not in pool]
    t0 = time.perf_counter()
    if missing:
        embedder = embedder or Embedder(model)
        texts = [chunks[i]["text"] for i in missing]
        new = embedder.embed_passages(texts)
        for i, v in zip(missing, new):
            pool[chunks[i]["hash"]] = v
    seconds = time.perf_counter() - t0
    if not chunks:
        return np.zeros((0, 0), dtype=np.float32), {"reused": 0, "embedded": 0, "seconds": 0.0, "dim": 0}
    matrix = normalize(np.stack([pool[c["hash"]] for c in chunks]))
    if use_cache and missing:
        save_cache(model, pool, keep_first=[c["hash"] for c in chunks])
    return matrix, {"reused": len(chunks) - len(missing), "embedded": len(missing), "seconds": round(seconds, 2),
                    "dim": int(matrix.shape[1])}
