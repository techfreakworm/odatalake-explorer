"""The ordered provider chain: openai SDK, max_tokens on every call, failover before the first streamed byte.

The SDK runs against an httpx2 MockTransport, so the real request/stream parsing code is exercised without network.
"""

import asyncio
import contextlib
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


TEMPERATURE_400 = "`temperature` is deprecated for this model."
STREAM_OPTIONS_400 = "Unrecognized request argument supplied: stream_options"
MAX_TOKENS_400 = ("Unsupported parameter: 'max_tokens' is not supported with this model. "
                  "Use 'max_completion_tokens' instead.")


def held_400(reject, n=4):
    """A primary that answers 400 with reject(body), a message naming a param the request carries, and streams
    "ok [1]." when reject(body) is None. Each 400 is held until n requests have arrived, so all n cold requests are
    built before any adapt() runs; the wait is bounded, so a broken run fails instead of hanging."""
    arrived, all_in = [0], asyncio.Event()
    answer = ok(["ok [1]."])

    async def h(body):
        arrived[0] += 1
        if arrived[0] >= n:
            all_in.set()
        message = reject(body)
        if message is None:
            return await answer(body)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(all_in.wait(), 2)
        return await status(400, message)(body)
    return h


async def cold_calls(ch, n=4):
    return await asyncio.gather(*(call(ch) for _ in range(n)))


@pytest.mark.parametrize("key,message,effort", [
    ("temperature", TEMPERATURE_400, None),
    ("stream_options", STREAM_OPTIONS_400, None),
    ("reasoning_effort", "Unrecognized request argument supplied: reasoning_effort", "none"),
    ("max_tokens", MAX_TOKENS_400, None),
], ids=["temperature", "stream_options", "reasoning_effort", "max_tokens"])
def test_concurrent_cold_calls_all_adapt_to_a_rejected_param(key, message, effort):
    # 4 calls in flight on a fresh chain all get the 400 for a param they carried: every one adapts and retries on the
    # primary, not only the first to adapt (the others found the param already dropped and failed over)
    r = Router(primary=held_400(lambda body: message if key in body else None), fallback=ok(["unused"]))
    results = asyncio.run(cold_calls(chain(r, "primary", "fallback", effort=effort)))
    assert [(res.provider, res.failovers) for res, _ in results] == [("primary", [])] * 4
    assert [(res.text, streamed) for res, streamed in results] == [("ok [1].", "ok [1].")] * 4
    assert r.hosts() == ["primary"] * 8  # one rejected send and one retry per call; the fallback is never hit
    retries = [body for _, body in r.requests[4:]]
    assert all(key not in body for body in retries)
    if key == "max_tokens":
        assert all(body["max_completion_tokens"] == 600 for body in retries)


def test_concurrent_cold_calls_adapt_to_two_rejected_params_within_the_send_bound():
    rejected = {"temperature": TEMPERATURE_400, "stream_options": STREAM_OPTIONS_400}
    # each 400 names whichever rejected param comes first in the body
    r = Router(primary=held_400(lambda body: next((rejected[k] for k in body if k in rejected), None)),
               fallback=ok(["unused"]))
    results = asyncio.run(cold_calls(chain(r, "primary", "fallback")))
    assert [(res.provider, res.failovers) for res, _ in results] == [("primary", [])] * 4
    assert [streamed for _, streamed in results] == ["ok [1]."] * 4
    assert set(r.hosts()) == {"primary"} and len(r.requests) <= 16  # at most 4 sends per call, never the fallback


def test_a_400_for_a_param_the_request_left_out_fails_over_after_two_sends():
    # the primary rejects temperature even when the request has none: the second send already lacks it, so retrying
    # would resend an identical request; fail over instead
    r = Router(primary=status(400, TEMPERATURE_400), fallback=ok(["From fallback [1]."]))
    res, streamed = asyncio.run(call(chain(r, "primary", "fallback")))
    assert res.provider == "fallback" and streamed == "From fallback [1]."
    assert res.failovers == ["primary: HTTP 400"]
    assert r.hosts() == ["primary", "primary", "fallback"]
    assert "temperature" in r.requests[0][1] and "temperature" not in r.requests[1][1]


def test_no_failover_after_the_first_byte_of_an_adapted_retry():
    rejected, broken = status(400, TEMPERATURE_400), breaks_after_first_chunk()

    async def primary(body):
        return await (rejected if "temperature" in body else broken)(body)

    r = Router(primary=primary, fallback=ok(["should not be used"]))
    with pytest.raises(LLMStreamError) as e:
        asyncio.run(call(chain(r, "primary", "fallback")))
    assert e.value.partial.text == "Partial answer [1]."
    assert r.hosts() == ["primary", "primary"]


def test_empty_chain_is_unavailable():
    ch = ProviderChain([], timeout_s=5, max_tokens=600)
    assert not ch.configured
    with pytest.raises(LLMUnavailable):
        asyncio.run(call(ch))


def garbage_stream(body_bytes):
    async def h(body):
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body_bytes)
    return h


def test_failover_on_a_malformed_stream_before_the_first_byte():
    # verifier repro: the primary answers 200 with "data: {not json"; the fallback must answer
    r = Router(primary=garbage_stream(b"data: {not json\n\n"), fallback=ok(["From fallback [1]."]))
    res, streamed = asyncio.run(call(chain(r, "primary", "fallback")))
    assert res.provider == "fallback" and streamed == "From fallback [1]."
    assert r.hosts() == ["primary", "fallback"]
    assert res.failovers and res.failovers[0].startswith("primary: ")


def test_malformed_stream_after_the_first_byte_is_a_stream_error_not_a_failover():
    first = chunk({"role": "assistant", "content": "Partial answer [1]."}).encode()
    r = Router(primary=garbage_stream(first + b"data: {not json\n\n"), fallback=ok(["unused"]))
    with pytest.raises(LLMStreamError) as e:
        asyncio.run(call(chain(r, "primary", "fallback")))
    assert e.value.partial.text == "Partial answer [1]."
    assert r.hosts() == ["primary"]


def test_any_exception_from_a_provider_fails_over():
    async def boom(body):
        raise RuntimeError("weird provider failure")

    r = Router(primary=boom, fallback=ok(["ok [1]."]))
    res, _ = asyncio.run(call(chain(r, "primary", "fallback")))
    assert res.provider == "fallback"


def test_cancellation_is_never_turned_into_a_failover():
    r = Router(primary=hang(10), fallback=ok(["unused"]))

    async def go():
        task = asyncio.create_task(call(chain(r, "primary", "fallback", timeout_s=5)))
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert r.hosts() == ["primary"]
