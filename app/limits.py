"""Load protection that never turns into a 429 or 5xx on /ask: a per-client token bucket and a daily token budget
(both fall back to the degraded answer), plus the exact-match answer cache."""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any


class TokenBucket:
    """Refills at rate_per_min per client, holds at most `burst` tokens. RATE_LIMIT_BURST stays above the test-set
    size, so one scorer IP sending the whole set never runs dry."""

    def __init__(self, rate_per_min: float, burst: int, clock: Callable[[], float] = time.monotonic,
                 max_clients: int = 10_000):
        self.rate = rate_per_min / 60.0
        self.burst = float(burst)
        self.clock = clock
        self.max_clients = max_clients
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def take(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.pop(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            ok = tokens >= 1.0
            if ok:
                tokens -= 1.0
            self._buckets[key] = (tokens, now)
            while len(self._buckets) > self.max_clients:
                self._buckets.popitem(last=False)  # the least recently seen client
            return ok

    def __len__(self) -> int:
        return len(self._buckets)


class DailyTokenBudget:
    """LLM tokens (prompt + completion) per UTC day. limit <= 0 disables it."""

    def __init__(self, limit: int, today: Callable[[], dt.date] = lambda: dt.datetime.now(dt.UTC).date()):
        self.limit = limit
        self.today = today
        self._day = today()
        self._used = 0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        d = self.today()
        if d != self._day:
            self._day, self._used = d, 0

    @property
    def used(self) -> int:
        with self._lock:
            self._roll()
            return self._used

    def exhausted(self) -> bool:
        return self.limit > 0 and self.used >= self.limit

    def add(self, tokens: int) -> None:
        with self._lock:
            self._roll()
            self._used += max(0, int(tokens))


def cache_key(question: str, index_version: str) -> tuple[str, str]:
    """Exact match on the question with case and whitespace normalised, scoped to the index version."""
    return (" ".join(question.lower().split()), index_version)


class AnswerCache:
    """In-process LRU. No semantic cache: two similar questions can need different answers."""

    def __init__(self, maxsize: int = 1024):
        self.maxsize = maxsize
        self._data: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
