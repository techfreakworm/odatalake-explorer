"""The ordered provider chain: openai SDK, max_tokens on every call, failover before the first streamed byte.

The SDK runs against an httpx2 MockTransport, so the real request/stream parsing code is exercised without network.
"""

import asyncio
import json
import time

import httpx2
import pytest

from app.config import ProviderConfig
from app.llm import LLMStreamError, LLMUnavailable, ProviderChain


def chunk(delta=None, finish=None, usage=None):
    c = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "m",
         "choices": [] if delta is None and finish is None else
         [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
    if usage:
        c["usage"] = {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}
    return "data: " + json.dumps(c) + "\n\n"


def sse(parts, finish="stop", usage=(11, 3)):
    out = [chunk({"role": "assistant", "content": ""})]
    out += [chunk({"content": p}) for p in parts]
    out.append(chunk({}, finish=finish))
    if usage:
        out.append(chunk(usage=usage))
    out.append("data: [DONE]\n\n")
    return "".join(out).encode()


class Router:
    """Dispatches by provider host and records every request body."""

    def __init__(self, **handlers):
        self.handlers = handlers
        self.requests: list[tuple[str, dict]] = []

    async def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        self.requests.append((request.url.host, body))
        return await self.handlers[request.url.host](body)

    def hosts(self):
        return [h for h, _ in self.requests]


def ok(parts, **kw):
    async def h(body):
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=sse(parts, **kw))
    return h


def status(code, message="nope"):
    async def h(body):
        return httpx2.Response(code, json={"error": {"message": message, "type": "error"}})
    return h


def hang(seconds):
    async def h(body):
        await asyncio.sleep(seconds)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=sse(["late"]))
    return h


def breaks_after_first_chunk():
    async def body_iter():
        yield chunk({"role": "assistant", "content": "Partial answer [1]."}).encode()
        raise httpx2.ReadError("connection reset")

    async def h(body):
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body_iter())
    return h


def chain(router, *names, timeout_s=5.0, effort=None):
    provs = [ProviderConfig(n, f"http://{n}/v1", f"key-{n}", f"model-{n}", effort if i == 0 else None)
             for i, n in enumerate(names)]
    return ProviderChain(provs, timeout_s=timeout_s, max_tokens=600, transport=httpx2.MockTransport(router))


async def call(ch, deadline_s=10.0):
    deltas = []
    loop = asyncio.get_running_loop()
    res = await ch.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}],
                            deadline=loop.time() + deadline_s, on_delta=deltas.append)
    return res, "".join(deltas)


def test_streams_text_usage_and_finish_reason():
    r = Router(primary=ok(["Hel", "lo [1]."]))
    res, streamed = asyncio.run(call(chain(r, "primary")))
    assert res.text == "Hello [1]." and streamed == "Hello [1]."
    assert (res.finish_reason, res.prompt_tokens, res.completion_tokens) == ("stop", 11, 3)
    assert (res.provider, res.model, res.failovers) == ("primary", "model-primary", [])
    assert res.ttft_ms is not None


def test_request_carries_max_tokens_temperature_zero_and_no_json_mode():
    r = Router(primary=ok(["x [1]."]))
    asyncio.run(call(chain(r, "primary")))
    body = r.requests[0][1]
    assert body["model"] == "model-primary"
    assert body["max_tokens"] == 600
    assert body["temperature"] == 0
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    assert "reasoning_effort" not in body
    assert "response_format" not in body
    assert body["messages"][1] == {"role": "user", "content": "q"}


def test_reasoning_effort_only_when_set():
    r = Router(primary=ok(["x"]))
    asyncio.run(call(chain(r, "primary", effort="none")))
    assert r.requests[0][1]["reasoning_effort"] == "none"


def test_failover_on_429_is_immediate():
    r = Router(primary=status(429, "rate limited"), fallback=ok(["From fallback [1]."]))
    t0 = time.perf_counter()
    res, streamed = asyncio.run(call(chain(r, "primary", "fallback")))
    assert time.perf_counter() - t0 < 1.0  # no SDK retry sleep when another provider can answer
    assert res.provider == "fallback" and streamed == "From fallback [1]."
    assert r.hosts() == ["primary", "fallback"]
    assert res.failovers == ["primary: HTTP 429"]


def test_failover_on_5xx():
    r = Router(primary=status(503), fallback=ok(["ok [1]."]))
    res, _ = asyncio.run(call(chain(r, "primary", "fallback")))
    assert res.provider == "fallback"
    assert res.failovers == ["primary: HTTP 503"]


def test_failover_on_timeout_before_the_first_byte():
    r = Router(primary=hang(10), fallback=ok(["ok [1]."]))
    t0 = time.perf_counter()
    res, _ = asyncio.run(call(chain(r, "primary", "fallback", timeout_s=0.3)))
    assert time.perf_counter() - t0 < 3.0
    assert res.provider == "fallback"
    assert res.failovers == ["primary: timeout"]


def test_failover_on_connection_error():
    async def refuse(body):
        raise httpx2.ConnectError("connection refused")

    r = Router(primary=refuse, fallback2=ok(["ok [1]."]))
    res, _ = asyncio.run(call(chain(r, "primary", "fallback2")))
    assert res.provider == "fallback2"
    assert res.failovers[0].startswith("primary: connection error")


def test_all_providers_failing_raises_llm_unavailable():
    r = Router(primary=status(429), fallback=status(500))
    with pytest.raises(LLMUnavailable) as e:
        asyncio.run(call(chain(r, "primary", "fallback")))
    assert e.value.failovers == ["primary: HTTP 429", "fallback: HTTP 500"]


def test_deadline_bounds_the_chain():
    r = Router(primary=hang(10), fallback=hang(10))
    t0 = time.perf_counter()
    with pytest.raises(LLMUnavailable):
        asyncio.run(call(chain(r, "primary", "fallback", timeout_s=5), deadline_s=0.4))
    assert time.perf_counter() - t0 < 2.0


def test_no_failover_after_the_first_byte():
    r = Router(primary=breaks_after_first_chunk(), fallback=ok(["should not be used"]))
    with pytest.raises(LLMStreamError) as e:
        asyncio.run(call(chain(r, "primary", "fallback")))
    assert e.value.partial.text == "Partial answer [1]."
    assert r.hosts() == ["primary"]


def test_think_tags_are_stripped_from_text_and_deltas():
    r = Router(primary=ok(["<think>plan the", " answer</think>", "Answer [1]."]))
    res, streamed = asyncio.run(call(chain(r, "primary")))
    assert res.text == "Answer [1]."
    assert streamed == "Answer [1]."


def test_truncation_is_reported():
    r = Router(primary=ok(["cut off mid"], finish="length"))
    res, _ = asyncio.run(call(chain(r, "primary")))
    assert res.finish_reason == "length"


def test_missing_usage_is_estimated():
    r = Router(primary=ok(["a" * 400], usage=None))
    res, _ = asyncio.run(call(chain(r, "primary")))
    assert res.usage_estimated
    assert res.completion_tokens == 100 and res.prompt_tokens > 0


def test_adapts_to_a_provider_that_wants_max_completion_tokens():
    calls = []

    async def picky(body):
        calls.append(body)
        if "max_tokens" in body:
            return httpx2.Response(400, json={"error": {
                "message": "Unsupported parameter: 'max_tokens' is not supported with this model. "
                           "Use 'max_completion_tokens' instead.", "type": "invalid_request_error"}})
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=sse(["ok [1]."]))

    r = Router(primary=picky, fallback=ok(["unused"]))
    res, _ = asyncio.run(call(chain(r, "primary", "fallback")))
    assert res.provider == "primary"
    assert calls[-1]["max_completion_tokens"] == 600 and "max_tokens" not in calls[-1]
    assert r.hosts() == ["primary", "primary"]


def test_empty_chain_is_unavailable():
    ch = ProviderChain([], timeout_s=5, max_tokens=600)
    assert not ch.configured
    with pytest.raises(LLMUnavailable):
        asyncio.run(call(ch))
