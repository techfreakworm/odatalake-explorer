"""Structured logs: one JSON object per line on stdout. Known secrets (API keys, the canary) are redacted from every
line as a last line of defence; the code never logs them on purpose."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import sys
from collections.abc import Iterable

log = logging.getLogger("ask_olake")
_SECRET_RE: re.Pattern | None = None


def set_secrets(values: Iterable[str]) -> None:
    global _SECRET_RE
    vals = sorted({v for v in values if v and len(v) >= 4}, key=len, reverse=True)
    _SECRET_RE = re.compile("|".join(re.escape(v) for v in vals), re.I) if vals else None


def redact(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text) if _SECRET_RE else text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
        }
        fields = getattr(record, "fields", None)
        msg = record.getMessage()
        if fields:
            out.update(fields)
            if msg and msg != fields.get("event"):
                out["msg"] = msg
        else:
            out["msg"] = msg
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return redact(json.dumps(out, default=str, ensure_ascii=False))


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is at emit time (keeps working under test capture)."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, value) -> None:
        pass


def configure_logging(level: str = "INFO") -> None:
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)  # some libraries set their own loggers to DEBUG on import
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.captureWarnings(True)  # library warnings become JSON lines too, not plain text on stderr
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # the request middleware writes one JSON access line per request instead
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2", "openai", "fastembed", "flashrank", "bm25s"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    log.log(level, event, extra={"fields": {"event": event, **fields}})
