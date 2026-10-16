"""One writer at a time: index.build and index.refresh (CLI or the app's poller) take this lock.
Also the refresher's poll state (.cache/refresh_state.json): the sitemap ETag and git shortcuts,
never content."""

from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager

from ingest import config


class Busy(RuntimeError):
    pass


@contextmanager
def index_lock(blocking: bool = False):
    path = config.CACHE_DIR / "index.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as e:
            raise Busy("another index build or refresh is running") from e
        yield
    finally:
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()


def load_state() -> dict:
    try:
        return json.loads(config.REFRESH_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    config.REFRESH_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.REFRESH_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")
    tmp.replace(config.REFRESH_STATE)
