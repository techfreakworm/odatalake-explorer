"""The LLM client: the openai SDK over an ordered chain of OpenAI-compatible providers (LLM_*, LLM_FALLBACK_*,
LLM_FALLBACK2_*; each optional).

Rules (docs/research.md §5.2): timeout=LLM_TIMEOUT_S and max_retries=1 per client (the SDK defaults are 10 minutes and
2 retries); max_tokens=MAX_TOKENS and temperature 0 on every call; reasoning_effort only when configured; plain-text
streaming, never JSON mode or response_format. Fail over to the next provider on any error BEFORE the first visible
streamed byte (429, 5xx, timeout, connection error, and provider-level 4xx such as a revoked key); after the first
byte there is no failover. <think> blocks never reach the caller.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2
import openai

from app.config import ProviderConfig
from app.guard import ThinkFilter, strip_think
from app.logs import log_event

RETRY_AFTER_CAP_MS = 2000  # the last provider in the chain waits at most this long on a 429


@dataclass
class LLMResult:
    text: str  # visible text (reasoning removed)
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    provider: str
    model: str
    ttft_ms: float | None
    failovers: list[str] = field(default_factory=list)
    usage_estimated: bool = False


class LLMUnavailable(Exception):
    """No provider produced a first byte (all failed, or none configured, or no time left)."""

    def __init__(self, failovers: list[str]):
        super().__init__("; ".join(failovers) or "no LLM provider")
        self.failovers = failovers


class LLMStreamError(Exception):
    """The stream broke after the first byte; `partial` holds what arrived."""

    def __init__(self, reason: str, partial: LLMResult):
        super().__init__(reason)
        self.reason = reason
        self.partial = partial


class _FailOver(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _reason(e: BaseException) -> str:
    if isinstance(e, (TimeoutError, openai.APITimeoutError, httpx2.TimeoutException)):
        return "timeout"
    if isinstance(e, openai.APIStatusError):
        return f"HTTP {e.status_code}"
    if isinstance(e, (openai.APIConnectionError, httpx2.TransportError)):
        return "connection error"
    return type(e).__name__


class _Provider:
    def __init__(self, cfg: ProviderConfig, *, timeout_s: float, has_successor: bool,
                 transport: httpx2.AsyncBaseTransport | None):
        self.cfg = cfg
        self.has_successor = has_successor
        self.use_max_completion_tokens = False
        self.dropped: set[str] = set()
        http = openai.DefaultAsyncHttpxClient(transport=transport, event_hooks={"response": [self._on_response]})
        self.client = openai.AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=timeout_s,
                                         max_retries=1, http_client=http)

    async def _on_response(self, response: httpx2.Response) -> None:
        # A 429 with another provider behind it fails over at once instead of sleeping on Retry-After inside the
        # SDK; the last provider retries once but waits RETRY_AFTER_CAP_MS at most.
        if response.status_code == 429:
            if self.has_successor:
                response.headers["x-should-retry"] = "false"
            else:
                response.headers["retry-after-ms"] = str(RETRY_AFTER_CAP_MS)

    def params(self, messages: Sequence[dict], max_tokens: int) -> dict[str, Any]:
        p: dict[str, Any] = {"model": self.cfg.model, "messages": list(messages), "temperature": 0, "stream": True,
                             "stream_options": {"include_usage": True}}
        p["max_completion_tokens" if self.use_max_completion_tokens else "max_tokens"] = max_tokens
        if self.cfg.reasoning_effort:
            p["reasoning_effort"] = self.cfg.reasoning_effort
        for k in self.dropped:
            p.pop(k, None)
        return p

    def adapt(self, err: openai.BadRequestError) -> bool:
        """Some providers reject a parameter; drop or rename it once and retry on the same provider."""
        msg = str(err).lower()
        if "max_tokens" in msg and "max_completion_tokens" in msg and not self.use_max_completion_tokens:
            self.use_max_completion_tokens = True
            return True
        for param, words in (("stream_options", ("stream_options", "include_usage")),
                             ("temperature", ("temperature",)),
                             ("reasoning_effort", ("reasoning_effort",))):
            if param not in self.dropped and any(w in msg for w in words):
                self.dropped.add(param)
                return True
        return False


class ProviderChain:
    def __init__(self, providers: Sequence[ProviderConfig], *, timeout_s: float, max_tokens: int,
                 transport: httpx2.AsyncBaseTransport | None = None):
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self._providers = [_Provider(p, timeout_s=timeout_s, has_successor=i < len(providers) - 1,
                                     transport=transport) for i, p in enumerate(providers)]

    @property
    def configured(self) -> bool:
        return bool(self._providers)

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(f"{p.cfg.name}:{p.cfg.model}" for p in self._providers)

    async def aclose(self) -> None:
        for p in self._providers:
            await p.client.close()

    async def complete(self, messages: Sequence[dict], *, deadline: float,
                       on_delta: Callable[[str], Any] | None = None) -> LLMResult:
        """Stream one answer. `deadline` is an event-loop time; on_delta gets visible text as it arrives."""
        if not self._providers:
            raise LLMUnavailable(["no LLM provider configured"])
        loop = asyncio.get_running_loop()
        failovers: list[str] = []
        for p in self._providers:
            if deadline - loop.time() <= 0.05:
                failovers.append(f"{p.cfg.name}: no time left")
                break
            try:
                res = await self._attempt(p, messages, deadline, on_delta)
            except _FailOver as e:
                failovers.append(f"{p.cfg.name}: {e.reason}")
                log_event("llm_failover", logging.WARNING, provider=p.cfg.name, model=p.cfg.model, reason=e.reason)
                continue
            res.failovers = failovers
            return res
        raise LLMUnavailable(failovers)

    async def _attempt(self, p: _Provider, messages: Sequence[dict], deadline: float,
                       on_delta: Callable[[str], Any] | None) -> LLMResult:
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        first_deadline = min(deadline, t0 + self.timeout_s)
        st = _StreamState(on_delta)
        stream = None
        try:
            # phase 1: until the first visible byte, any failure moves on to the next provider
            try:
                async with asyncio.timeout_at(first_deadline):
                    for _ in range(4):
                        try:
                            stream = await p.client.chat.completions.create(**p.params(messages, self.max_tokens))
                            break
                        except openai.BadRequestError as e:
                            if not p.adapt(e):
                                raise
                            log_event("llm_param_adapted", logging.WARNING, provider=p.cfg.name,
                                      dropped=sorted(p.dropped), max_completion_tokens=p.use_max_completion_tokens)
                    if stream is None:
                        raise _FailOver("HTTP 400")
                    it = stream.__aiter__()
                    while not st.visible_started:
                        try:
                            ev = await it.__anext__()
                        except StopAsyncIteration:
                            st.ended = True
                            break
                        st.consume(ev)
            except (openai.APIError, httpx2.HTTPError, TimeoutError) as e:
                raise _FailOver(_reason(e)) from None
            st.ttft_ms = (loop.time() - t0) * 1000 if st.visible_started else None
            # phase 2: the rest of the stream, bounded by the overall deadline; no failover any more
            if not st.ended:
                try:
                    async with asyncio.timeout_at(deadline):
                        async for ev in it:
                            st.consume(ev)
                except (openai.APIError, httpx2.HTTPError, TimeoutError) as e:
                    st.finish()
                    raise LLMStreamError(_reason(e), st.result(p, messages)) from None
            st.finish()
            return st.result(p, messages)
        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception:  # noqa: BLE001 - closing a broken stream must not mask the real outcome
                    pass


class _StreamState:
    def __init__(self, on_delta: Callable[[str], Any] | None):
        self.on_delta = on_delta
        self.think = ThinkFilter()
        self.raw: list[str] = []
        self.visible_started = False
        self.ended = False
        self.finish_reason: str | None = None
        self.usage: tuple[int, int] | None = None
        self.ttft_ms: float | None = None

    def consume(self, ev: Any) -> None:
        if getattr(ev, "usage", None):
            self.usage = (ev.usage.prompt_tokens or 0, ev.usage.completion_tokens or 0)
        for choice in getattr(ev, "choices", None) or []:
            if choice.finish_reason:
                self.finish_reason = choice.finish_reason
            content = getattr(choice.delta, "content", None) if choice.delta else None
            if content:
                self.raw.append(content)
                self._deliver(self.think.feed(content))

    def finish(self) -> None:
        self._deliver(self.think.flush())

    def _deliver(self, text: str) -> None:
        if text:
            if not self.visible_started and not text.strip():
                return  # leading whitespace is not a first byte
            self.visible_started = True
            if self.on_delta is not None:
                self.on_delta(text)

    def result(self, p: _Provider, messages: Sequence[dict]) -> LLMResult:
        text = strip_think("".join(self.raw))
        if self.usage:
            prompt_tokens, completion_tokens, estimated = self.usage[0], self.usage[1], False
        else:  # some providers send no usage chunk: estimate at ~4 characters per token
            prompt_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4
            completion_tokens = len("".join(self.raw)) // 4
            estimated = True
        return LLMResult(text=text, finish_reason=self.finish_reason, prompt_tokens=prompt_tokens,
                         completion_tokens=completion_tokens, provider=p.cfg.name, model=p.cfg.model,
                         ttft_ms=self.ttft_ms, usage_estimated=estimated)
