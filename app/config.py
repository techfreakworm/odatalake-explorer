"""Every setting comes from env (contract I4, plus ASK_TIMEOUT_S, DEBUG, GIT_SHA and LOG_LEVEL).

Defaults follow docs/plan.md Appendix C. The LLM provider variables have no defaults: a provider is used only
when its base URL, key and model are all set. Empty strings count as unset, so a copied .env.example works.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# (name, env prefix, the env var holding that provider's reasoning_effort)
_CHAIN = (
    ("primary", "LLM_", "LLM_REASONING_EFFORT"),
    ("fallback", "LLM_FALLBACK_", "LLM_FALLBACK_REASONING_EFFORT"),
    ("fallback2", "LLM_FALLBACK2_", "LLM_FALLBACK2_REASONING_EFFORT"),
)


class ConfigError(ValueError):
    """A setting has an invalid value; raised at startup so a bad deploy fails fast."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str = field(repr=False)
    model: str
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class Settings:
    providers: tuple[ProviderConfig, ...] = ()
    index_dir: Path = Path("data/index")
    embed_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_mode: str = "hybrid"
    rerank: str = "off"
    gate_signal: str = "dense"
    abstain_threshold: float = 0.69
    canary: str = field(default_factory=lambda: secrets.token_hex(8), repr=False)
    source_url_style: str = "branch"
    blog: bool = False
    github_token: str | None = field(default=None, repr=False)
    onnx_threads: int = 1
    max_tokens: int = 600
    llm_timeout_s: float = 25.0
    ask_timeout_s: float = 30.0
    queue_wait_s: float = 20.0
    max_concurrency: int = 8
    rate_limit_per_min: float = 120.0
    rate_limit_burst: int = 200
    daily_token_budget: int = 5_000_000
    public_base_url: str = ""
    refresh_interval_min: float = 0.0
    log_level: str = "INFO"
    debug: bool = False
    git_sha: str = "unknown"
    model_cache_dir: Path = Path(".cache/models")
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        r = _Reader(env)
        warnings: list[str] = []

        providers = []
        for name, prefix, effort_var in _CHAIN:
            vals = {k: r.text(f"{prefix}{k}") for k in ("BASE_URL", "API_KEY", "MODEL")}
            if all(vals.values()):
                providers.append(ProviderConfig(name, vals["BASE_URL"], vals["API_KEY"], vals["MODEL"],
                                                r.text(effort_var) or None))
            elif any(vals.values()):
                missing = ", ".join(f"{prefix}{k}" for k, v in vals.items() if not v)
                warnings.append(f"LLM provider '{name}' skipped: {missing} not set")

        canary = r.text("CANARY")
        if canary and len(canary) < 8:
            warnings.append("CANARY shorter than 8 characters was replaced by a random one")
            canary = ""
        elif canary and not re.fullmatch(r"[0-9a-fA-F]{16}", canary):
            # never echo the value; the stream holds back max(16, len(CANARY)) characters either way
            warnings.append("CANARY is not 16 hex characters (openssl rand -hex 8); it is used as given")

        return cls(
            providers=tuple(providers),
            index_dir=Path(r.text("INDEX_DIR") or "data/index"),
            embed_model=r.text("EMBED_MODEL") or "BAAI/bge-small-en-v1.5",
            retrieval_mode=r.choice("RETRIEVAL_MODE", ("hybrid", "bm25"), "hybrid"),
            rerank=r.choice("RERANK", ("off", "tinybert"), "off"),
            gate_signal=r.choice("GATE_SIGNAL", ("dense", "off"), "dense"),
            abstain_threshold=r.number("ABSTAIN_THRESHOLD", 0.69),
            canary=canary or secrets.token_hex(8),
            source_url_style=r.choice("SOURCE_URL_STYLE", ("branch", "sha"), "branch"),
            blog=r.choice("BLOG", ("off", "on"), "off") == "on",
            github_token=r.text("GITHUB_TOKEN") or None,
            onnx_threads=r.integer("ONNX_THREADS", 1, minimum=1),
            max_tokens=r.integer("MAX_TOKENS", 600, minimum=16),
            llm_timeout_s=r.number("LLM_TIMEOUT_S", 25.0, minimum=0.1),
            ask_timeout_s=r.number("ASK_TIMEOUT_S", 30.0, minimum=0.1),
            queue_wait_s=r.number("QUEUE_WAIT_S", 20.0, minimum=0.0),
            max_concurrency=r.integer("MAX_CONCURRENCY", 8, minimum=1),
            rate_limit_per_min=r.number("RATE_LIMIT_PER_MIN", 120.0, minimum=0.0),
            rate_limit_burst=r.integer("RATE_LIMIT_BURST", 200, minimum=1),
            daily_token_budget=r.integer("DAILY_TOKEN_BUDGET", 5_000_000, minimum=0),
            public_base_url=(r.text("PUBLIC_BASE_URL") or "").rstrip("/"),
            refresh_interval_min=r.number("REFRESH_INTERVAL_MIN", 0.0, minimum=0.0),
            log_level=(r.text("LOG_LEVEL") or "INFO").upper(),
            debug=r.flag("DEBUG"),
            git_sha=r.text("GIT_SHA") or "unknown",
            model_cache_dir=Path(r.text("FASTEMBED_CACHE_PATH") or ".cache/models"),
            warnings=tuple(warnings),
        )

    @property
    def secret_values(self) -> tuple[str, ...]:
        """Values that must never appear in a log line."""
        vals = [self.canary, *(p.api_key for p in self.providers)]
        if self.github_token:
            vals.append(self.github_token)
        return tuple(v for v in vals if v and len(v) >= 4)


class _Reader:
    def __init__(self, env: Mapping[str, str]):
        self.env = env

    def text(self, key: str) -> str:
        return (self.env.get(key) or "").strip()

    def choice(self, key: str, allowed: tuple[str, ...], default: str) -> str:
        v = self.text(key).lower() or default
        if v not in allowed:
            raise ConfigError(f"{key}={v!r} is invalid; use one of {', '.join(allowed)}")
        return v

    def flag(self, key: str) -> bool:
        v = self.text(key).lower()
        if v in ("", "0", "false", "no", "off"):
            return False
        if v in ("1", "true", "yes", "on"):
            return True
        raise ConfigError(f"{key}={v!r} is invalid; use 0 or 1")

    def integer(self, key: str, default: int, minimum: int | None = None) -> int:
        v = self.text(key)
        try:
            out = int(v) if v else default
        except ValueError:
            raise ConfigError(f"{key}={v!r} is not an integer") from None
        if minimum is not None and out < minimum:
            raise ConfigError(f"{key}={out} is below the minimum {minimum}")
        return out

    def number(self, key: str, default: float, minimum: float | None = None) -> float:
        v = self.text(key)
        try:
            out = float(v) if v else default
        except ValueError:
            raise ConfigError(f"{key}={v!r} is not a number") from None
        if minimum is not None and out < minimum:
            raise ConfigError(f"{key}={out} is below the minimum {minimum}")
        return out
