"""Per-client token bucket, daily token budget and the exact-match answer cache."""

import datetime as dt

from app.limits import AnswerCache, DailyTokenBudget, TokenBucket, cache_key


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_token_bucket_burst_then_refill():
    clock = Clock()
    b = TokenBucket(rate_per_min=60, burst=3, clock=clock)
    assert [b.take("ip1") for _ in range(4)] == [True, True, True, False]
    assert b.take("ip2")  # buckets are per client
    clock.t += 1.0  # 60/min refills one token per second
    assert b.take("ip1")
    assert not b.take("ip1")
    clock.t += 100
    assert [b.take("ip1") for _ in range(4)] == [True, True, True, False]  # capped at burst


def test_token_bucket_forgets_idle_clients():
    b = TokenBucket(rate_per_min=60, burst=2, clock=Clock(), max_clients=3)
    for k in ("a", "b", "c", "d"):
        b.take(k)
    assert len(b) == 3


def test_daily_budget_counts_tokens_and_resets_each_utc_day():
    today = [dt.date(2026, 10, 18)]
    b = DailyTokenBudget(limit=1000, today=lambda: today[0])
    assert not b.exhausted()
    b.add(600)
    assert not b.exhausted() and b.used == 600
    b.add(400)
    assert b.exhausted()
    today[0] = dt.date(2026, 10, 19)
    assert not b.exhausted() and b.used == 0


def test_zero_budget_means_unlimited():
    b = DailyTokenBudget(limit=0)
    b.add(10**9)
    assert not b.exhausted()


def test_cache_key_normalises_case_and_whitespace_and_includes_the_index_version():
    assert cache_key("  How do I  install OLake? ", "v1") == cache_key("how do i install olake?", "v1")
    assert cache_key("How do I install OLake?", "v1") != cache_key("How do I install OLake?", "v2")
    assert cache_key("install olake", "v1") != cache_key("install olake!", "v1")  # exact match only


def test_lru_cache_evicts_least_recently_used():
    c = AnswerCache(maxsize=2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1  # a is now most recent
    c.put("c", 3)
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3
