"""Contract + embed probe (local only).

    ASK_GATE_THRESHOLD=<tuned> uv run uvicorn api.app:app --host 127.0.0.1 --port 8000
    uv run python -I -m http.server 8081 --bind 127.0.0.1 --directory api/demo   # second origin

POST /ask   {"question": "..."} -> exactly {"answer": "...", "sources": ["<url>", ...]}
            errors keep the same shape (422 bad input, 503 LLM unavailable)
GET /healthz
GET /widget.js  one-script-tag widget (shadow DOM) for any docs site
CORS: any origin, no credentials; preflight cached for a day.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from answer.pipeline import AskPipeline

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("ask-olake")
STATE: dict = {}


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskOut(BaseModel):
    answer: str
    sources: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.perf_counter()
    gate = os.environ.get("ASK_GATE_THRESHOLD")
    STATE["pipe"] = AskPipeline(
        target=int(os.environ.get("ASK_CHUNK_TARGET", "300")),
        dense_model=os.environ.get("ASK_DENSE_MODEL", "BAAI/bge-small-en-v1.5"),
        reranker_model=os.environ.get("ASK_RERANKER", "Xenova/ms-marco-MiniLM-L-6-v2"),
        gate_threshold=float(gate) if gate else None,
        prompt_version=os.environ.get("ASK_PROMPT_VERSION", "v1"),
        threads=int(os.environ.get("ASK_ONNX_THREADS", "0")) or None,  # cap onnxruntime threads on small boxes
    )
    STATE["startup_s"] = round(time.perf_counter() - t0, 2)
    yield


app = FastAPI(title="Ask OLake (POC)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
    max_age=86400,
)


@app.exception_handler(RequestValidationError)
async def bad_request(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"answer": "Please send JSON like {\"question\": \"...\"} "
                                                            "with a non-empty question (max 2000 characters).",
                                                  "sources": []})


@app.post("/ask", response_model=AskOut)
def ask(body: AskIn) -> AskOut:  # sync: runs in the threadpool, the pipeline blocks
    try:
        res = STATE["pipe"].ask(body.question.strip())
    except Exception:  # noqa: BLE001  (LLM down, timeout...)
        log.exception("ask failed")
        return JSONResponse(status_code=503, content={"answer": "The assistant is temporarily unavailable. "
                                                                "Please try again shortly.", "sources": []})
    log.info("ask %s reason=%s timings=%s", body.question[:80], res.reason, res.timings_ms)
    return AskOut(answer=res.answer, sources=res.sources)


@app.get("/healthz")
def healthz() -> dict:
    pipe = STATE.get("pipe")
    return {"status": "ok" if pipe else "starting", "chunks": len(pipe.chunks) if pipe else 0,
            "llm_model": pipe.model if pipe else None, "startup_s": STATE.get("startup_s")}


@app.get("/widget.js")
def widget() -> FileResponse:
    return FileResponse(STATIC / "widget.js", media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=300"})
