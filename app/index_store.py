"""Load the index artifact (contract I1) into one immutable snapshot that a refresh can hot-swap.

INDEX_DIR/CURRENT names the active version directory, which holds chunks.jsonl, embeddings.npy and manifest.json.
The corpus is never embedded here: only queries are embedded at runtime, with the manifest's embed_model and
embed_query_prefix. Requests read `IndexHolder.current` once and keep that reference, so a swap never changes the
index under an in-flight request.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.retrieval import TIER_BY_TYPE, BM25Index, RankingData, precompute

_REPO_ORDER = ("olake", "olake-ui", "olake-helm", "olake-fusion")


class IndexLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class IndexSnapshot:
    version: str
    path: Path
    manifest: Mapping[str, Any]
    chunks: tuple[Mapping[str, Any], ...]
    embeddings: np.ndarray | None  # float32 [n, dim], L2-normalised, read-only
    bm25: BM25Index
    ranking: RankingData
    facts_line: str
    embed_model: str
    query_prefix: str
    loaded_at: float = field(default_factory=time.time)


def read_current(index_dir: str | Path) -> str | None:
    p = Path(index_dir) / "CURRENT"
    try:
        return p.read_text().strip() or None
    except FileNotFoundError:
        return None


def resolve_version_dir(index_dir: str | Path) -> Path:
    d = Path(index_dir)
    name = read_current(d)
    if name:
        vdir = d / name
        if not (vdir / "chunks.jsonl").is_file():
            raise IndexLoadError(f"{d / 'CURRENT'} names {name!r}, but {vdir / 'chunks.jsonl'} does not exist")
        return vdir
    if (d / "chunks.jsonl").is_file():  # INDEX_DIR may point straight at a version directory
        return d
    raise IndexLoadError(f"no index: {d / 'CURRENT'} is missing (build one with: uv run python -m index.build)")


def load_snapshot(index_dir: str | Path, *, blog: bool, require_embeddings: bool = True) -> IndexSnapshot:
    vdir = resolve_version_dir(index_dir)
    try:
        manifest = json.loads((vdir / "manifest.json").read_text())
    except FileNotFoundError:
        raise IndexLoadError(f"{vdir / 'manifest.json'} is missing") from None
    except json.JSONDecodeError as e:
        raise IndexLoadError(f"{vdir / 'manifest.json'} is not valid JSON: {e}") from None

    chunks: list[dict[str, Any]] = []
    with open(vdir / "chunks.jsonl", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError as e:
                raise IndexLoadError(f"chunks.jsonl line {lineno} is not valid JSON: {e}") from None
            missing = [k for k in ("id", "doc_url", "text") if not c.get(k)]
            if missing:
                raise IndexLoadError(f"chunks.jsonl line {lineno} lacks {', '.join(missing)}")
            c.setdefault("source_type", "docs")
            c["tier"] = int(c.get("tier") or TIER_BY_TYPE.get(c["source_type"], 1))
            chunks.append(c)
    if not chunks:
        raise IndexLoadError(f"{vdir / 'chunks.jsonl'} has no chunks")

    embeddings = None
    emb_path = vdir / "embeddings.npy"
    if emb_path.is_file():
        embeddings = np.load(emb_path).astype(np.float32, copy=False)
        if embeddings.ndim != 2 or embeddings.shape[0] != len(chunks):
            raise IndexLoadError(f"embeddings.npy has {embeddings.shape[0] if embeddings.ndim else 0} rows "
                                 f"for {len(chunks)} chunks (rows must match chunks.jsonl lines)")
        dim = manifest.get("dim")
        if dim and embeddings.shape[1] != int(dim):
            raise IndexLoadError(f"embeddings.npy dim {embeddings.shape[1]} != manifest dim {dim}")
        embeddings = np.ascontiguousarray(embeddings)
        embeddings.setflags(write=False)
    elif require_embeddings:
        raise IndexLoadError(f"{emb_path} is missing (RETRIEVAL_MODE=bm25 works without it)")

    return IndexSnapshot(
        version=str(manifest.get("version") or vdir.name),
        path=vdir,
        manifest=manifest,
        chunks=tuple(chunks),
        embeddings=embeddings,
        bm25=BM25Index([c["text"] for c in chunks]),
        ranking=precompute(chunks, blog=blog),
        facts_line=facts_line(manifest, chunks),
        embed_model=str(manifest.get("embed_model") or ""),
        query_prefix=str(manifest.get("embed_query_prefix") or ""),
    )


def _date(value: Any) -> str:
    s = str(value or "")
    return s[:10] if len(s) >= 10 and s[4] == "-" else s


def _repo_sort_key(name: str) -> tuple[int, str]:
    return (_REPO_ORDER.index(name) if name in _REPO_ORDER else len(_REPO_ORDER), name)


def facts_line(manifest: Mapping[str, Any], chunks: list[Mapping[str, Any]]) -> str:
    """'Docs indexed <date>; latest releases: olake <tag> (<date>), ...' from the manifest, or from the release-gh
    chunks when the manifest has no releases."""
    releases: dict[str, tuple[str, str]] = {}
    for name, r in (manifest.get("releases") or {}).items():
        if isinstance(r, Mapping) and r.get("tag"):
            releases[name] = (str(r["tag"]), _date(r.get("published_at")))
    if not releases:
        from app.retrieval import release_group_version

        best: dict[str, tuple[tuple[int, int, int], str, str]] = {}
        for c in chunks:
            if c.get("source_type") != "release-gh":
                continue
            gv = release_group_version(c)
            m = re.search(r"github\.com/datazip-inc/([^/]+)/releases/tag/([^/?#]+)", str(c["doc_url"]))
            if not gv or not m:
                continue
            repo, tag = m.group(1), m.group(2)
            if repo not in best or gv[1] > best[repo][0]:
                best[repo] = (gv[1], tag, _date(c.get("lastmod")))
        releases = {k: (v[1], v[2]) for k, v in best.items()}
    line = f"Docs indexed {_date(manifest.get('built_at')) or 'unknown'}"
    if releases:
        parts = [f"{name} {tag} ({date})" if date else f"{name} {tag}"
                 for name, (tag, date) in sorted(releases.items(), key=lambda kv: _repo_sort_key(kv[0]))]
        line += "; latest releases: " + ", ".join(parts)
    return line


def index_info(snap: IndexSnapshot) -> dict[str, Any]:
    """The /healthz "index" object."""
    m = snap.manifest
    counts = m.get("counts") or {}
    pages = counts.get("pages") if isinstance(counts.get("pages"), int) else None
    if pages is None:
        pages = len({c["doc_url"] for c in snap.chunks})
    chunks = counts.get("chunks") if isinstance(counts.get("chunks"), int) else len(snap.chunks)
    repos = {name: str(r.get("commit") or "")[:7] for name, r in (m.get("repos") or {}).items()
             if isinstance(r, Mapping)}
    return {
        "version": snap.version,
        "built_at": m.get("built_at"),
        "pages": pages,
        "chunks": chunks,
        "docs_lastmod_max": (m.get("docs") or {}).get("lastmod_max"),
        "repos": repos,
    }


class IndexHolder:
    """The active snapshot. Readers take `current` once per request; `swap` replaces it atomically."""

    def __init__(self, snap: IndexSnapshot | None = None):
        self._snap = snap
        self._lock = threading.Lock()

    @property
    def current(self) -> IndexSnapshot | None:
        return self._snap

    def swap(self, snap: IndexSnapshot) -> IndexSnapshot | None:
        with self._lock:
            old, self._snap = self._snap, snap
        return old
