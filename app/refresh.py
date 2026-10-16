"""In-app freshness poller (decision D9): every REFRESH_INTERVAL_MIN minutes call ingest's
index.refresh.refresh_once(), then hot-swap the index when data/index/CURRENT names a new version. Off by default."""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from app.index_store import read_current
from app.logs import log_event, redact


def default_refresh_fn() -> Callable | None:
    try:
        from index.refresh import refresh_once
    except ImportError as e:
        log_event("refresh_unavailable", logging.WARNING, error=redact(str(e)))
        return None
    return refresh_once


class RefreshPoller:
    def __init__(self, *, interval_min: float, index_dir: Path, refresh_fn: Callable | None,
                 current_version: Callable[[], str | None], reload: Callable[[], None]):
        self.interval_s = interval_min * 60.0
        self.index_dir = index_dir
        self.refresh_fn = refresh_fn
        self.current_version = current_version
        self.reload = reload
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="index-refresh", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.tick()

    def tick(self) -> None:
        """One refresh round. Never raises: a failed refresh keeps serving the current index."""
        if self.refresh_fn is not None:
            try:
                params = inspect.signature(self.refresh_fn).parameters
                result = (self.refresh_fn(index_dir=self.index_dir) if "index_dir" in params
                          else self.refresh_fn())
                log_event("refresh_done", result=_summary(result))
            except Exception as e:  # noqa: BLE001 - the poller must survive any refresh failure
                log_event("refresh_failed", logging.WARNING, error=redact(f"{type(e).__name__}: {e}"))
        try:
            on_disk = read_current(self.index_dir)
            if on_disk and on_disk != self.current_version():
                self.reload()
        except Exception as e:  # noqa: BLE001
            log_event("index_swap_failed", logging.ERROR, error=redact(f"{type(e).__name__}: {e}"))


def _summary(result) -> object:
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if isinstance(v, (str, int, float, bool, type(None)))}
    return None if result is None else str(result)[:200]
