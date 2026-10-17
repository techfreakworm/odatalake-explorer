"""The /ask pipeline: small talk -> cache -> retrieve -> off-topic gate -> limits -> one LLM call -> abstain policy ->
citations.

Small talk and "what can you do" messages (app/smalltalk.py) get a canned intro first, because the dense gate scores
a bare greeting below ABSTAIN_THRESHOLD and used to answer it with the off-topic decline. A general question about
the product ("who is OLake?", "tell me about Ask OLake", app/product_intro.py) can score below it too, so the gate lets
it through to the LLM.

Abstain policy (docs/research.md §4.3, decision D8): the dense gate only short-circuits clearly off-topic questions;
otherwise the model decides (NO_ANSWER, OUT_OF_SCOPE), and an answer with no valid citation left abstains. Every
outcome carries its reason. Load problems (queue wait, the whole-request bound, LLM failure after fallback, the
daily token budget, the per-client token bucket) return the degraded answer: the most relevant pages, never a
429 or 5xx.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app import product_intro, prompts, smalltalk
from app.citations import (
    CitedSource,
    citation_details,
    parse_citation_numbers,
    resolve_citations,
    salvage_truncated,
    strip_sources_section,
)
from app.config import Settings
from app.guard import LeakGuard, StreamSanitizer, detect_marker, remove_markers, tidy
from app.index_store import IndexHolder
from app.limits import AnswerCache, DailyTokenBudget, TokenBucket, cache_key
from app.llm import LLMResult, LLMStreamError, LLMUnavailable
from app.logs import log_event, redact
from app.models import Passage
from app.retrieval import RetrievalConfig, RetrievalResult, retrieve

MIN_RETRY_S = 1.0  # a retry of a truncated or unparseable answer starts only with this much time left
RETRIEVAL_HISTORY_CHARS = 300

ABSTAIN_REASONS = ("retrieval_gate", "model_dont_know", "no_valid_citation", "out_of_scope")
SMALLTALK_REASON = "smalltalk"  # the canned intro to small talk: an answer without sources, not an abstain


class NotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class AskRequest:
    question: str
    request_id: str = ""
    client: str = "anonymous"
    no_cache: bool = False
    history: Sequence[Mapping[str, str]] | None = None


@dataclass(frozen=True)
class AskOutcome:
    answer: str
    sources: list[str]
    citations: list[dict] = field(default_factory=list)
    reason: str = "answered"  # "answered", "smalltalk", an abstain reason, "prompt_leak_blocked" or a degraded reason
    abstain_reason: str | None = None
    degraded: bool = False
    gate_score: float | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str | None = None
    model: str | None = None
    failovers: list[str] = field(default_factory=list)
    cache_hit: bool = False
    prompt_leak_blocked: bool = False
    truncated: bool = False
    retried: bool = False
    top_doc_urls: list[str] = field(default_factory=list)
    index_version: str | None = None

    @property
    def abstained(self) -> bool:
        return self.abstain_reason is not None or (self.prompt_leak_blocked and not self.sources)


@dataclass
class _Run:
    t0: float
    retrieval: RetrievalResult | None = None
    version: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str | None = None
    model: str | None = None
    failovers: list[str] = field(default_factory=list)


class AskService:
    def __init__(self, settings: Settings, holder: IndexHolder, llm, *, embedder=None, reranker=None,
                 cache: AnswerCache | None = None, bucket: TokenBucket | None = None,
                 budget: DailyTokenBudget | None = None):
        self.s = settings
        self.holder = holder
        self.llm = llm
        self.embedder = embedder  # used for any embed_model not in `embedders`
        self.embedders: dict[str, Any] = {}  # embed_model -> query embedder (a refresh may change the model)
        self.reranker = reranker
        self.cache = cache or AnswerCache()
        self.bucket = bucket or TokenBucket(settings.rate_limit_per_min, settings.rate_limit_burst)
        self.budget = budget or DailyTokenBudget(settings.daily_token_budget)
        self.guard = LeakGuard(settings.canary, prompts.rules_text(settings.canary))
        self.rcfg = RetrievalConfig(mode=settings.retrieval_mode, gate_threshold=settings.abstain_threshold,
                                    source_url_style=settings.source_url_style)
        self._sem: asyncio.Semaphore | None = None
        self._sem_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ public

    async def answer(self, req: AskRequest, *, emit: Callable[[str], Any] | None = None) -> AskOutcome:
        """Never raises for load or LLM problems; the whole call is bounded by ASK_TIMEOUT_S."""
        loop = asyncio.get_running_loop()
        run = _Run(t0=loop.time())
        deadline = run.t0 + self.s.ask_timeout_s
        try:
            async with asyncio.timeout_at(deadline):
                return await self._run(req, run, deadline, emit)
        except TimeoutError:
            return self._degraded("ask_timeout", run)

    def retrieve_now(self, question: str, k: int = 10) -> RetrievalResult:
        """Blocking retrieval for /debug/retrieve (call it in a thread)."""
        snap = self.holder.current
        if snap is None:
            raise NotReady("index not loaded")
        return retrieve(snap, question, embedder=self._embedder(snap), reranker=self.reranker,
                        cfg=dataclasses.replace(self.rcfg, k=k))

    # ------------------------------------------------------------------ pipeline

    def _embedder(self, snap):
        if self.s.retrieval_mode != "hybrid":
            return None
        return self.embedders.get(snap.embed_model, self.embedder)

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._sem is None or self._sem_loop is not loop:
            self._sem, self._sem_loop = asyncio.Semaphore(self.s.max_concurrency), loop
        return self._sem

    async def _run(self, req: AskRequest, run: _Run, deadline: float,
                   emit: Callable[[str], Any] | None) -> AskOutcome:
        loop = asyncio.get_running_loop()
        snap = self.holder.current
        if snap is None:
            raise NotReady("index not loaded")
        run.version = snap.version
        kind = smalltalk.detect(req.question)
        if kind is not None:  # ahead of the cache and retrieval: never cached, no LLM call, no bucket token, no budget
            out = self._outcome(run, prompts.smalltalk_text(kind), [], [], SMALLTALK_REASON, None)
            if emit is not None:
                emit(out.answer)
            return out
        key = cache_key(req.question, snap.version)
        cacheable = not req.history
        if cacheable and not req.no_cache:
            cached: AskOutcome | None = self.cache.get(key)
            if cached is not None:
                if emit is not None and cached.answer:
                    emit(cached.answer)
                return dataclasses.replace(cached, cache_hit=True, tokens_in=0, tokens_out=0, retried=False,
                                           failovers=[], timings_ms=self._timings(run))

        query = req.question
        if req.history:
            last_user = next((str(t.get("content") or "") for t in reversed(req.history)
                              if t.get("role") == "user"), "")
            if last_user:
                query = last_user[:RETRIEVAL_HISTORY_CHARS] + "\n" + req.question
        t = loop.time()
        r = await asyncio.to_thread(retrieve, snap, query, embedder=self._embedder(snap), reranker=self.reranker,
                                    cfg=self.rcfg)
        run.retrieval = r
        run.timings["retrieve"] = r.timings_ms.get("retrieve", round((loop.time() - t) * 1000, 2))
        run.timings["rerank"] = r.timings_ms.get("rerank", 0.0)

        if self.s.gate_signal == "dense" and r.gate_score is not None and r.gate_score < self.s.abstain_threshold:
            if not product_intro.is_product_intro(req.question):  # the current message, never the history
                out = self._outcome(run, prompts.SHORT_CIRCUIT_TEXT, [], [], "retrieval_gate", "retrieval_gate")
                if cacheable:
                    self.cache.put(key, out)
                return out
            log_event("gate_override", gate_score=round(r.gate_score, 4))  # a general question about the product
        if not r.hits:  # nothing retrieved (possible in bm25 mode): same short-circuit, no LLM call
            out = self._outcome(run, prompts.SHORT_CIRCUIT_TEXT, [], [], "retrieval_gate", "retrieval_gate")
            if cacheable:
                self.cache.put(key, out)
            return out

        if not self.bucket.take(req.client):
            return self._degraded("rate_limited", run)
        if self.budget.exhausted():
            return self._degraded("budget_exhausted", run)

        sem = self._semaphore()
        t = loop.time()
        try:
            async with asyncio.timeout(max(0.0, min(self.s.queue_wait_s, deadline - loop.time()))):
                await sem.acquire()
        except TimeoutError:
            run.timings["queue"] = round((loop.time() - t) * 1000, 2)
            return self._degraded("queue_timeout", run)
        run.timings["queue"] = round((loop.time() - t) * 1000, 2)
        try:
            out = await self._generate(req, run, r, snap, deadline, emit)
        finally:
            sem.release()
        if out.degraded:
            return out
        if cacheable:
            self.cache.put(key, out)
        return out

    async def _generate(self, req: AskRequest, run: _Run, r: RetrievalResult, snap, deadline: float,
                        emit: Callable[[str], Any] | None) -> AskOutcome:
        loop = asyncio.get_running_loop()
        passages = [Passage(n=i + 1, chunk=h.chunk, source_url=h.source_url, score=h.score, source_urls=h.source_urls)
                    for i, h in enumerate(r.hits)]
        messages = prompts.build_messages(req.question, passages, snap.facts_line, self.s.canary, req.history,
                                          reminders=self.s.prompt_reminders)
        sanitizer = StreamSanitizer(self.guard) if emit is not None else None

        def on_delta(text: str) -> None:
            if sanitizer is not None:
                out = sanitizer.feed(text)
                if out:
                    emit(out)

        t = loop.time()
        try:
            res, broken = await self._call(messages, deadline, on_delta if emit is not None else None, run)
        except Exception as e:  # noqa: BLE001 - every provider failed, or the client broke: the degraded 200
            if not isinstance(e, LLMUnavailable):
                log_event("llm_error", logging.ERROR, error=redact(f"{type(e).__name__}: {e}"))
            run.timings["llm"] = round((loop.time() - t) * 1000, 2)
            return self._degraded("llm_failed", run)
        if res.ttft_ms is not None:
            run.timings["llm_ttft"] = round(res.ttft_ms, 2)

        text = res.text
        leak = self.guard.contains_leak(text)
        truncated = broken or res.finish_reason == "length"
        retried = False
        if not leak and (truncated or _unparseable(text)) and deadline - loop.time() > MIN_RETRY_S:
            retried = True
            if not self.s.prompt_reminders:  # off: the baseline retry, the very same messages once more
                retry_messages = messages
            elif truncated:
                retry_messages = [*messages[:-1], {"role": "user",
                                                   "content": messages[-1]["content"] + "\n\n" + prompts.RETRY_SHORTER}]
            elif text.strip():  # an answer without any [n]: show it back and ask for the citations
                retry_messages = [*messages, {"role": "assistant", "content": text},
                                  {"role": "user", "content": prompts.RETRY_ADD_CITATIONS}]
            else:
                retry_messages = messages
            try:
                async with asyncio.timeout_at(deadline - 0.25):
                    res2, broken2 = await self._call(retry_messages, deadline - 0.25, None, run)
                truncated2 = broken2 or res2.finish_reason == "length"
                if not _unparseable(res2.text) and (not truncated2 or truncated):
                    text, truncated = res2.text, truncated2
                    leak = self.guard.contains_leak(text)
            except Exception as e:  # noqa: BLE001 - the retry failed or ran out of time: keep the first attempt
                if not isinstance(e, (LLMUnavailable, TimeoutError)):
                    log_event("llm_error", logging.ERROR, error=redact(f"{type(e).__name__}: {e}"))
        elif sanitizer is not None:
            tail = sanitizer.finish()
            if tail:
                emit(tail)
        run.timings["llm"] = round((loop.time() - t) * 1000, 2)
        return self._finalize(run, text, passages, truncated=truncated, leak=leak, retried=retried)

    async def _call(self, messages: list[dict], deadline: float, on_delta, run: _Run) -> tuple[LLMResult, bool]:
        try:
            res = await self.llm.complete(messages, deadline=deadline, on_delta=on_delta)
            broken = False
        except LLMStreamError as e:
            res, broken = e.partial, True
        except LLMUnavailable as e:
            run.failovers.extend(e.failovers)
            raise
        run.tokens_in += res.prompt_tokens
        run.tokens_out += res.completion_tokens
        run.provider, run.model = res.provider, res.model
        run.failovers.extend(res.failovers)
        self.budget.add(res.prompt_tokens + res.completion_tokens)
        return res, broken

    def _finalize(self, run: _Run, text: str, passages: list[Passage], *, truncated: bool, leak: bool,
                  retried: bool) -> AskOutcome:
        extra = {"truncated": truncated, "retried": retried, "prompt_leak_blocked": leak}
        if leak:
            text = self.guard.scrub(text)
        elif (marker := detect_marker(text)) is not None:
            if marker == "NO_ANSWER":
                return self._outcome(run, prompts.ABSTAIN_TEXT, [], [], "model_dont_know", "model_dont_know", **extra)
            return self._outcome(run, prompts.OUT_OF_SCOPE_TEXT, [], [], "out_of_scope", "out_of_scope", **extra)
        text = strip_sources_section(remove_markers(text))
        if truncated:
            text = salvage_truncated(text, len(passages))
        cr = resolve_citations(text, passages)
        answer = tidy(cr.answer)
        if leak:
            if cr.sources:
                return self._outcome(run, f"{prompts.LEAK_REFUSAL}\n\n{answer}", cr.sources,
                                     citation_details(cr.cited), "answered", None, **extra)
            return self._outcome(run, prompts.LEAK_REFUSAL, [], [], "prompt_leak_blocked", None, **extra)
        if not cr.sources:
            return self._outcome(run, prompts.ABSTAIN_TEXT, [], [], "no_valid_citation", "no_valid_citation", **extra)
        return self._outcome(run, answer, cr.sources, citation_details(cr.cited), "answered", None, **extra)

    # ------------------------------------------------------------------ outcomes

    def _timings(self, run: _Run) -> dict[str, float]:
        out = {"retrieve": 0.0, "rerank": 0.0, "queue": 0.0, "llm": 0.0, **run.timings}
        out["total"] = round((asyncio.get_running_loop().time() - run.t0) * 1000, 2)
        return out

    def _outcome(self, run: _Run, answer: str, sources: list[str], citations: list[dict], reason: str,
                 abstain_reason: str | None, **extra) -> AskOutcome:
        r = run.retrieval
        return AskOutcome(
            answer=answer, sources=sources, citations=citations, reason=reason, abstain_reason=abstain_reason,
            gate_score=r.gate_score if r else None, timings_ms=self._timings(run), tokens_in=run.tokens_in,
            tokens_out=run.tokens_out, provider=run.provider, model=run.model, failovers=list(run.failovers),
            top_doc_urls=[str(h.chunk.get("doc_url")) for h in (r.hits[:5] if r else [])],
            index_version=run.version, **extra)

    def _degraded(self, reason: str, run: _Run) -> AskOutcome:
        """'I couldn't generate an answer right now' plus the top 3 pages, sources = those pages."""
        cited: list[CitedSource] = []
        for h in (run.retrieval.hits if run.retrieval else []):
            if h.source_url not in [c.url for c in cited]:
                n = len(cited) + 1
                cited.append(CitedSource(n, h.source_url, Passage(n=n, chunk=h.chunk, source_url=h.source_url)))
            if len(cited) == 3:
                break
        if cited:
            lines = [f"{c.n}. [{c.passage.chunk.get('title') or c.url}]({c.url}) [{c.n}]" for c in cited]
            answer = prompts.DEGRADED_INTRO + "\n\n" + "\n".join(lines)
        else:
            answer = prompts.DEGRADED_NO_PAGES
        out = self._outcome(run, answer, [c.url for c in cited], citation_details(cited), reason, None)
        return dataclasses.replace(out, degraded=True)


def _unparseable(text: str) -> bool:
    """Empty, or neither a marker nor any [n] marker: the model ignored the answer format."""
    if not text.strip():
        return True
    if detect_marker(text):
        return False
    return not parse_citation_numbers(text)
