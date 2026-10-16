"""Test doubles: a deterministic hashing embedder, a tiny index builder and a scripted LLM (no network)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.llm import LLMResult, LLMUnavailable

FIXTURE_SRC = Path(__file__).parent / "fixtures" / "index_src"
VERSION = "20261017T0000Z"
DIM = 512
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be", "with", "do", "does",
         "how", "i", "my", "can", "it", "what", "which", "this", "that", "from", "by", "as", "at", "then"}


def hash_embed(text: str, dim: int = DIM) -> np.ndarray:
    """Signed feature hashing of lowercase word tokens, L2-normalised: shared words raise the cosine."""
    v = np.zeros(dim, dtype=np.float32)
    for tok in re.findall(r"[a-z0-9_]+", text.lower()):
        if len(tok) < 2 or tok in _STOP:
            continue
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 20) & 1 else -1.0
    n = float(np.linalg.norm(v))
    return v / n if n else v


class HashEmbedder:
    def __init__(self, dim: int = DIM):
        self.dim = dim
        self.calls = 0

    def embed_query(self, text: str) -> np.ndarray:
        self.calls += 1
        return hash_embed(text, self.dim)


def build_fixture_index(dest: Path, version: str = VERSION, with_embeddings: bool = True) -> Path:
    """Copy the fixture chunks + manifest to dest/<version>/, embed them with hash_embed, write dest/CURRENT."""
    vdir = dest / version
    vdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURE_SRC / "chunks.jsonl", vdir / "chunks.jsonl")
    manifest = json.loads((FIXTURE_SRC / "manifest.json").read_text())
    manifest["version"] = version
    (vdir / "manifest.json").write_text(json.dumps(manifest))
    if with_embeddings:
        texts = [json.loads(line)["text"] for line in (vdir / "chunks.jsonl").read_text().splitlines() if line]
        np.save(vdir / "embeddings.npy", np.stack([hash_embed(t) for t in texts]).astype(np.float32))
    (dest / "CURRENT").write_text(version + "\n")
    return dest


class FakeLLM:
    """Scripted stand-in for app.llm.ProviderChain.

    script(user_message) returns the answer text, or (text, finish_reason), or raises LLMUnavailable.
    Text is streamed through on_delta in small pieces. `gate` (an asyncio.Event) blocks calls until set.
    """

    def __init__(self, script: Callable[[str], object] | str = "OLake answer [1].", chunk: int = 7,
                 prompt_tokens: int = 1000, completion_tokens: int = 50, delay_s: float = 0.0):
        self.script = script if callable(script) else (lambda _u, s=script: s)
        self.chunk = chunk
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.delay_s = delay_s
        self.calls: list[list[dict]] = []
        self.gate: asyncio.Event | None = None
        self.providers = ("fake",)

    @property
    def configured(self) -> bool:
        return True

    async def complete(self, messages, *, deadline: float, on_delta=None) -> LLMResult:
        self.calls.append(messages)
        if self.gate is not None:
            await self.gate.wait()
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        out = self.script(messages[-1]["content"])
        if isinstance(out, BaseException):
            raise out
        text, finish = (out if isinstance(out, tuple) else (out, "stop"))
        for i in range(0, len(text), self.chunk):
            if on_delta is not None:
                on_delta(text[i:i + self.chunk])
            await asyncio.sleep(0)
        return LLMResult(text=text, finish_reason=finish, prompt_tokens=self.prompt_tokens,
                         completion_tokens=self.completion_tokens, provider="fake", model="fake-model",
                         ttft_ms=1.0, failovers=[])


def unavailable(_user: str):
    return LLMUnavailable(["primary: APIConnectionError"])
