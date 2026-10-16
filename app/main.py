"""The Ask OLake HTTP service (contract I2).

    uv run --env-file .env uvicorn app.main:app --port 8000

POST /ask            {"question"} -> exactly {"answer", "sources"}; 422 / 503 keep that shape; load never gives 429/5xx
POST /ask/stream     SSE: meta, token*, done (or error); optional history (last 4 turns used)
GET  /healthz        liveness + index manifest summary (never calls the LLM)
GET  /readyz         503 until the index and models are loaded and a warm-up retrieval ran
POST /feedback       204, logged
POST /debug/retrieve only with DEBUG=1: ranked passages and the gate score (the eval runner's --retrieval-only)
GET  /widget.js, /embed (CSP frame-ancestors *), /, /static/*   files from web/
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.index_store import IndexHolder, IndexLoadError, IndexSnapshot, index_info, load_snapshot
from app.llm import ProviderChain
from app.logs import configure_logging, log_event, redact, set_secrets
from app.pipeline import AskOutcome, AskRequest, AskService
from app.refresh import RefreshPoller, default_refresh_fn
from app.retrieval import retrieve

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
EMBED_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
             "font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")
mimetypes.add_type("text/javascript", ".mjs")  # the embed's ES modules, whatever the host's mime.types says
MAX_QUESTION_CHARS = 2000
MAX_BODY_BYTES = 64 * 1024
HISTORY_TURNS = 4
ASK_PATHS = ("/ask", "/ask/stream")
WARMUP_QUESTION = "How do I install OLake?"
NOT_READY_TEXT = "Ask OLake is starting up. Please try again in a few seconds."
ERROR_TEXT = "Something went wrong while answering. Please try again."
_RID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")


# ---------------------------------------------------------------- request bodies


class AskBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str

    @field_validator("question")
    @classmethod
    def _question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('"question" is empty: ask something about OLake')
        if len(v) > MAX_QUESTION_CHARS:
            raise ValueError(f'"question" is too long: at most {MAX_QUESTION_CHARS} characters (got {len(v)})')
        return v


class Turn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class AskStreamBody(AskBody):
    history: list[Turn] | None = Field(default=None, max_length=50)


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_id: str = Field(min_length=1, max_length=128)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)


class DebugBody(AskBody):
    k: int = Field(default=10, ge=1, le=50)


# ---------------------------------------------------------------- runtime


def default_embedder_factory(model_name: str, *, threads: int, cache_dir: Path):
    from app.embedder import FastEmbedQueryEmbedder

    return FastEmbedQueryEmbedder(model_name, threads=threads, cache_dir=cache_dir)


def default_reranker_factory(*, cache_dir: Path):
    from app.embedder import TinyBertReranker

    return TinyBertReranker(cache_dir)


class Runtime:
    """Everything that lives for the process: settings, the index holder, models, the service and the poller."""

    def __init__(self, settings: Settings, *, llm=None, embedder_factory: Callable | None = None,
                 reranker_factory: Callable | None = None, refresh_fn: Callable | None = None):
        self.s = settings
        self.holder = IndexHolder()
        self.llm = llm if llm is not None else ProviderChain(settings.providers, timeout_s=settings.llm_timeout_s,
                                                             max_tokens=settings.max_tokens)
        self.service = AskService(settings, self.holder, self.llm)
        self.embedder_factory = embedder_factory or default_embedder_factory
        self.reranker_factory = reranker_factory or default_reranker_factory
        self.refresh_fn = refresh_fn
        self.ready = False
        self.reason = "starting: loading the index and models"
        self.started_at = time.time()
        self.poller: RefreshPoller | None = None
        self._install_lock = threading.Lock()

    async def start(self) -> None:
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(self.load)
        except Exception as e:  # noqa: BLE001 - stay up (healthz) and report why in readyz
            self.reason = redact(f"{type(e).__name__}: {e}")
            log_event("startup_failed", logging.ERROR, reason=self.reason, index_dir=str(self.s.index_dir))
            return
        self.ready, self.reason = True, ""
        snap = self.holder.current
        log_event("ready", index_version=snap.version if snap else None, chunks=len(snap.chunks) if snap else 0,
                  startup_s=round(time.perf_counter() - t0, 2), retrieval_mode=self.s.retrieval_mode,
                  rerank=self.s.rerank, gate_signal=self.s.gate_signal, providers=list(self._providers()))
        if self.s.refresh_interval_min > 0:
            self.poller = RefreshPoller(
                interval_min=self.s.refresh_interval_min, index_dir=self.s.index_dir,
                refresh_fn=self.refresh_fn or default_refresh_fn(),
                current_version=lambda: self.holder.current.version if self.holder.current else None,
                reload=self.load)
            self.poller.start()

    def _providers(self) -> tuple[str, ...]:
        return tuple(getattr(self.llm, "providers", ()))

    def load(self) -> None:
        """Load data/index/CURRENT, make sure its models are ready, warm up, then swap it in (blocking)."""
        with self._install_lock:
            snap = load_snapshot(self.s.index_dir, blog=self.s.blog,
                                 require_embeddings=self.s.retrieval_mode == "hybrid")
            current = self.holder.current
            if current is not None and current.version == snap.version:
                return
            self._ensure_models(snap)
            retrieve(snap, WARMUP_QUESTION, embedder=self.service._embedder(snap), reranker=self.service.reranker,
                     cfg=self.service.rcfg)
            old = self.holder.swap(snap)
            if old is not None:
                log_event("index_swapped", old_version=old.version, new_version=snap.version,
                          chunks=len(snap.chunks))

    def _ensure_models(self, snap: IndexSnapshot) -> None:
        if self.s.retrieval_mode == "hybrid" and snap.embed_model not in self.service.embedders:
            if self.s.embed_model and self.s.embed_model != snap.embed_model:
                log_event("embed_model_mismatch", logging.WARNING, env=self.s.embed_model, index=snap.embed_model,
                          using=snap.embed_model)
            emb = self.embedder_factory(snap.embed_model, threads=self.s.onnx_threads,
                                        cache_dir=self.s.model_cache_dir)
            dim = len(emb.embed_query("dimension check"))
            if snap.embeddings is not None and dim != snap.embeddings.shape[1]:
                raise IndexLoadError(f"query embedder dim {dim} != index dim {snap.embeddings.shape[1]}")
            self.service.embedders[snap.embed_model] = emb
        if self.s.rerank == "tinybert" and self.service.reranker is None:
            self.service.reranker = self.reranker_factory(cache_dir=self.s.model_cache_dir)

    async def aclose(self) -> None:
        if self.poller is not None:
            self.poller.stop()
        close = getattr(self.llm, "aclose", None)
        if close is not None:
            await close()


# ---------------------------------------------------------------- helpers


def client_key(request: Request) -> str:
    """The token-bucket key. The right-most X-Forwarded-For hop is the one the platform's proxy appended (on Cloud
    Run, the client IP); earlier hops are client-controlled, so rotating them does not buy a fresh bucket. Behind a
    chain of proxies the right-most hop can be a proxy's own IP and several clients then share one bucket: still safe,
    because the burst stays above the test-set size and an empty bucket gives the degraded 200, never a 429."""
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if hops:
        return hops[-1][:64]
    return request.client.host if request.client else "unknown"


def wants_no_cache(request: Request) -> bool:
    return "no-cache" in request.headers.get("cache-control", "").lower()


def server_timing(t: dict[str, float]) -> str:
    keys = ("retrieve", "rerank", "queue", "llm", "total")
    return ", ".join(f"{k};dur={float(t.get(k, 0.0)):.1f}" for k in keys)


def ask_headers(out: AskOutcome) -> dict[str, str]:
    return {
        "Server-Timing": server_timing(out.timings_ms),
        "X-Ask-Reason": out.reason,
        "X-Ask-Gate-Score": "" if out.gate_score is None else f"{out.gate_score:.4f}",
        "X-Ask-Cache": "hit" if out.cache_hit else "miss",
    }


def log_ask(request: Request, endpoint: str, status: int, out: AskOutcome) -> None:
    log_event(
        "ask", request_id=request.state.request_id, endpoint=endpoint, status=status, reason=out.reason,
        abstain_reason=out.abstain_reason, degraded=out.degraded, cache_hit=out.cache_hit,
        gate_score=None if out.gate_score is None else round(out.gate_score, 4), timings_ms=out.timings_ms,
        tokens_in=out.tokens_in, tokens_out=out.tokens_out, provider=out.provider, model=out.model,
        failovers=out.failovers, prompt_leak_blocked=out.prompt_leak_blocked, max_tokens_truncated=out.truncated,
        retried=out.retried, top_doc_urls=out.top_doc_urls, n_sources=len(out.sources),
        index_version=out.index_version)


def done_payload(out: AskOutcome, request_id: str) -> dict[str, Any]:
    return {
        "answer": out.answer,
        "sources": out.sources,
        "citations": out.citations,
        "abstained": out.abstained,
        "abstain_reason": out.abstain_reason,
        "request_id": request_id,
        "timings_ms": {k: float(out.timings_ms.get(k, 0.0)) for k in ("retrieve", "rerank", "llm", "total")},
    }


def validation_message(errors: list[dict]) -> str:
    for e in errors:
        loc = tuple(e.get("loc") or ())
        typ = str(e.get("type") or "")
        if typ == "json_invalid":
            return 'The request body is not valid JSON. Send {"question": "..."}.'
        field = loc[1] if len(loc) > 1 and loc[0] == "body" else None
        if field is None or isinstance(field, int):
            return 'Send a JSON object like {"question": "How do I install OLake?"}.'
        if typ == "missing":
            return f'Missing "{field}": send {{"question": "..."}}.' if field == "question" else f'Missing "{field}".'
        if typ == "string_type":
            return f'"{field}" must be a string.'
        msg = str(e.get("msg") or "invalid value").removeprefix("Value error, ")
        return msg if field == "question" and typ == "value_error" else f'Invalid "{field}": {msg}.'
    return "Invalid request."


def error_json(status: int, code: str, message: str, path: str) -> JSONResponse:
    if path in ASK_PATHS:
        return JSONResponse({"answer": message, "sources": []}, status_code=status)
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class RequestContextMiddleware:
    """X-Request-ID (echo a sane incoming one, else generate), a body-size limit, one JSON access line per request,
    and a last-resort JSON error (never an HTML 500). Sits inside CORS so error responses keep CORS headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if _RID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        path = scope.get("path", "")
        t0 = time.perf_counter()
        state = {"status": 500, "started": False}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["started"], state["status"] = True, message["status"]
                h = MutableHeaders(scope=message)
                h["X-Request-ID"] = rid
                h.setdefault("X-Content-Type-Options", "nosniff")
            await send(message)

        try:
            length = headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_BODY_BYTES:
                resp = error_json(422 if path in ASK_PATHS else 413, "body_too_large",
                                  f"The request body is too large (at most {MAX_BODY_BYTES} bytes).", path)
                await resp(scope, receive, send_wrapper)
                return
            await self.app(scope, receive, send_wrapper)
        except Exception as e:  # noqa: BLE001 - last resort: log it, answer with JSON
            log_event("unhandled_error", logging.ERROR, request_id=rid, path=path,
                      error=redact(f"{type(e).__name__}: {e}"))
            if not state["started"]:
                await error_json(503, "internal", ERROR_TEXT, path)(scope, receive, send_wrapper)
        finally:
            log_event("http", request_id=rid, method=scope.get("method"), path=path, status=state["status"],
                      duration_ms=round((time.perf_counter() - t0) * 1000, 1))


# ---------------------------------------------------------------- app


def create_app(settings: Settings | None = None, *, llm=None, embedder_factory: Callable | None = None,
               reranker_factory: Callable | None = None, refresh_fn: Callable | None = None,
               web_dir: Path | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    set_secrets(settings.secret_values)
    for w in settings.warnings:
        log_event("config_warning", logging.WARNING, warning=w)
    if not settings.providers and llm is None:
        log_event("config_warning", logging.WARNING,
                  warning="no LLM provider configured: /ask will return the degraded answer")
    web = web_dir or WEB_DIR
    rt = Runtime(settings, llm=llm, embedder_factory=embedder_factory, reranker_factory=reranker_factory,
                 refresh_fn=refresh_fn)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(rt.start())
        try:
            yield
        finally:
            if not task.done():
                task.cancel()
            await rt.aclose()

    app = FastAPI(title="Ask OLake", version="1.0", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/openapi.json" if settings.debug else None)
    app.state.rt = rt
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"],
                       expose_headers=["x-request-id", "x-ask-reason", "x-ask-gate-score", "x-ask-cache",
                                       "server-timing"],
                       max_age=86400)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        return error_json(422, "invalid_request", validation_message(list(exc.errors())), request.url.path)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if path in ASK_PATHS and exc.status_code == 405:
            return error_json(405, "method_not_allowed", 'Use POST with a JSON body like {"question": "..."}.', path)
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        resp = error_json(exc.status_code, code, str(exc.detail), path)
        if exc.headers:
            resp.headers.update(exc.headers)
        return resp

    @app.post("/ask")
    async def ask(body: AskBody, request: Request):
        if not rt.ready:
            return JSONResponse({"answer": NOT_READY_TEXT, "sources": []}, status_code=503,
                                headers={"X-Ask-Reason": "not_ready"})
        try:
            out = await rt.service.answer(AskRequest(question=body.question, request_id=request.state.request_id,
                                                     client=client_key(request), no_cache=wants_no_cache(request)))
        except Exception as e:  # noqa: BLE001 - keep the contract shape
            log_event("ask_failed", logging.ERROR, request_id=request.state.request_id,
                      error=redact(f"{type(e).__name__}: {e}"))
            return JSONResponse({"answer": ERROR_TEXT, "sources": []}, status_code=503,
                                headers={"X-Ask-Reason": "error"})
        log_ask(request, "/ask", 200, out)
        return JSONResponse({"answer": out.answer, "sources": out.sources}, headers=ask_headers(out))

    @app.post("/ask/stream", response_class=EventSourceResponse)
    async def ask_stream(body: AskStreamBody, request: Request):
        rid = request.state.request_id
        snap = rt.holder.current
        yield ServerSentEvent(event="meta", data={"request_id": rid, "index_version": snap.version if snap else None})
        if not rt.ready:
            yield ServerSentEvent(event="error", data={"message": NOT_READY_TEXT, "request_id": rid})
            return
        history = [t.model_dump() for t in (body.history or [])][-HISTORY_TURNS:] or None
        req = AskRequest(question=body.question, request_id=rid, client=client_key(request),
                         no_cache=wants_no_cache(request), history=history)
        queue: asyncio.Queue = asyncio.Queue()

        async def work():
            try:
                out = await rt.service.answer(req, emit=lambda text: queue.put_nowait(("token", text)))
                queue.put_nowait(("done", out))
            except Exception as e:  # noqa: BLE001
                log_event("ask_failed", logging.ERROR, request_id=rid, error=redact(f"{type(e).__name__}: {e}"))
                queue.put_nowait(("error", None))

        task = asyncio.create_task(work())
        try:
            while True:
                kind, payload = await queue.get()
                if kind == "token":
                    yield ServerSentEvent(event="token", data={"text": payload})
                elif kind == "done":
                    log_ask(request, "/ask/stream", 200, payload)
                    yield ServerSentEvent(event="done", data=done_payload(payload, rid))
                    return
                else:
                    yield ServerSentEvent(event="error", data={"message": ERROR_TEXT, "request_id": rid})
                    return
        finally:
            if not task.done():
                task.cancel()

    @app.api_route("/healthz", methods=["GET", "HEAD"])
    async def healthz():
        snap = rt.holder.current
        return {"status": "ok", "git_sha": settings.git_sha, "index": index_info(snap) if snap else None,
                "uptime_s": int(time.time() - rt.started_at)}

    @app.api_route("/readyz", methods=["GET", "HEAD"])
    async def readyz():
        if rt.ready:
            return {"ready": True}
        return JSONResponse({"ready": False, "reason": rt.reason}, status_code=503)

    @app.post("/feedback", status_code=204)
    async def feedback(body: FeedbackBody, request: Request):
        log_event("feedback", request_id=request.state.request_id, rated_request_id=body.request_id,
                  rating=body.rating, comment=body.comment)
        return Response(status_code=204)

    if settings.debug:
        @app.post("/debug/retrieve")
        async def debug_retrieve(body: DebugBody):
            if not rt.ready:
                return JSONResponse({"error": {"code": "not_ready", "message": rt.reason}}, status_code=503)
            r = await asyncio.to_thread(rt.service.retrieve_now, body.question, body.k)
            return {"gate_score": r.gate_score,
                    "results": [{"rank": i, "doc_url": h.chunk.get("doc_url"), "url": h.chunk.get("url"),
                                 "id": h.chunk.get("id"), "source_type": h.chunk.get("source_type"),
                                 "score": round(float(h.score), 6), "source_url": h.source_url,
                                 "source_urls": list(h.source_urls or (h.source_url,)),
                                 "dense": None if h.dense is None else round(h.dense, 4)}
                                for i, h in enumerate(r.hits, start=1)]}

    def web_file(rel: str, media_type: str, headers: dict[str, str] | None = None):
        path = web / rel
        if not path.is_file():
            return error_json(404, "not_found", f"{rel} is not built yet", "")
        return FileResponse(path, media_type=media_type, headers=headers)

    @app.api_route("/widget.js", methods=["GET", "HEAD"])
    async def widget_js():
        return web_file("widget.js", "application/javascript", {"Cache-Control": "public, max-age=300"})

    @app.api_route("/embed", methods=["GET", "HEAD"])
    async def embed():
        # frame-ancestors only works as an HTTP header (not in <meta>); no X-Frame-Options, so any site can frame it.
        # A second policy locks the embed's own content to this origin (defence in depth for rendered answers).
        resp = web_file("embed.html", "text/html", {"Content-Security-Policy": "frame-ancestors *",
                                                    "Cache-Control": "no-cache"})
        if resp.status_code == 200:
            resp.headers.append("Content-Security-Policy", EMBED_CSP)
        return resp

    @app.api_route("/", methods=["GET", "HEAD"])
    async def demo():
        return web_file("demo/index.html", "text/html", {"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=web, check_dir=False), name="static")
    return app


def _lazy_app() -> FastAPI:
    return create_app()


app = _lazy_app()
