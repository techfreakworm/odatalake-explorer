"""Index versions on disk (contract I1).

    data/index/<version>/{chunks.jsonl, embeddings.npy, manifest.json}
    data/index/CURRENT      the active version name (one line), swapped atomically

A version is a UTC minute such as 20261017T0412Z (a "-2" suffix if that minute is taken). A new
version is written into a hidden temp directory and renamed into place, then CURRENT is replaced
with os.replace, so a reader never sees a half-written index.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from index.config import CHUNK_HARD_MAX, CHUNK_TARGET, TOKENIZER, query_prefix

VERSION_RE = re.compile(r"^\d{8}T\d{4}Z(?:-\d+)?$")
CURRENT = "CURRENT"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_version(index_root: Path, now: datetime | None = None) -> str:
    base = (now or utc_now()).astimezone(timezone.utc).strftime("%Y%m%dT%H%MZ")
    name, n = base, 1
    while (index_root / name).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def read_current(index_root: Path) -> str | None:
    p = index_root / CURRENT
    if not p.exists():
        return None
    name = p.read_text(encoding="utf-8").strip()
    return name or None


def swap_current(index_root: Path, version: str) -> None:
    """Point CURRENT at `version`: write a temp file, then os.replace (atomic on POSIX)."""
    if not (index_root / version / "manifest.json").exists():
        raise FileNotFoundError(f"no index at {version}")
    tmp = index_root / f".{CURRENT}.{os.getpid()}.tmp"
    tmp.write_text(version + "\n", encoding="utf-8")
    os.replace(tmp, index_root / CURRENT)


def write_version(index_root: Path, version: str, chunks: list[dict], matrix: np.ndarray, manifest: dict) -> Path:
    if matrix.shape[0] != len(chunks):
        raise ValueError(f"{len(chunks)} chunks but {matrix.shape[0]} vectors")
    index_root.mkdir(parents=True, exist_ok=True)
    final = index_root / version
    tmp = index_root / f".tmp-{version}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    with (tmp / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    np.save(tmp / "embeddings.npy", np.ascontiguousarray(matrix, dtype=np.float32))
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.rename(tmp, final)
    return final


def load_version(index_root: Path, version: str | None = None) -> tuple[dict, list[dict], np.ndarray]:
    version = version or read_current(index_root)
    if not version:
        raise FileNotFoundError(f"no {CURRENT} in {index_root}")
    d = index_root / version
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    with (d / "chunks.jsonl").open(encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    matrix = np.load(d / "embeddings.npy", allow_pickle=False)
    return manifest, chunks, matrix


def list_versions(index_root: Path) -> list[str]:
    """Version directories, oldest first (by built_at, then name)."""
    out = []
    for d in index_root.iterdir() if index_root.exists() else []:
        if d.is_dir() and VERSION_RE.match(d.name) and (d / "manifest.json").exists():
            try:
                built = json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("built_at", "")
            except json.JSONDecodeError:
                built = ""
            out.append((built, d.name))
    return [name for _, name in sorted(out)]


def prune(index_root: Path) -> list[str]:
    """Keep CURRENT and the version built just before it; delete every other version."""
    current = read_current(index_root)
    versions = list_versions(index_root)
    keep = {current} if current else set()
    if current in versions:
        i = versions.index(current)
        if i > 0:
            keep.add(versions[i - 1])
    elif versions:
        keep.add(versions[-1])
    removed = []
    for v in versions:
        if v not in keep:
            shutil.rmtree(index_root / v)
            removed.append(v)
    for stale in index_root.glob(".tmp-*"):  # leftovers of an interrupted build
        shutil.rmtree(stale, ignore_errors=True)
    return removed


def counts_of(chunks: list[dict]) -> dict:
    by_type: dict[str, dict] = {}
    docs_by_type: dict[str, set] = defaultdict(set)
    n_by_type = Counter(c["source_type"] for c in chunks)
    for c in chunks:
        key = c["id"].split("#", 1)[0] if c["source_type"] == "factcard" else c["doc_url"]
        docs_by_type[c["source_type"]].add(key)
    for st in sorted(n_by_type):
        by_type[st] = {"pages": len(docs_by_type[st]), "chunks": n_by_type[st]}
    pages = sum(by_type.get(st, {}).get("pages", 0) for st in ("docs", "release"))
    return {"pages": pages, "chunks": len(chunks), "by_source_type": by_type}


def make_manifest(*, version: str, built_at: datetime, model: str, dim: int, chunks: list[dict], docs: dict,
                  repos: dict, releases: dict, denylist_skipped: list[str], sources: dict, build: dict) -> dict:
    return {
        "version": version,
        "built_at": iso(built_at),
        "embed_model": model,
        "embed_query_prefix": query_prefix(model),
        "dim": dim,
        "chunker": {"target": CHUNK_TARGET, "hard_max": CHUNK_HARD_MAX, "tokenizer": TOKENIZER},
        "counts": counts_of(chunks),
        "docs": docs,
        "repos": repos,
        "releases": releases,
        "denylist_skipped": denylist_skipped,
        "sources": sources,
        "build": build,
    }
