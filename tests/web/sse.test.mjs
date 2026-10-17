// SSE frame parser for fetch() + ReadableStream (EventSource cannot POST). Run: node --test tests/web/
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSSEParser, footerText, domainOf } from "../../web/embed-core.mjs";

const names = (evs) => evs.map((e) => e.event);

test("several events in one chunk", () => {
  const p = createSSEParser();
  const evs = p.push('event: meta\ndata: {"request_id": "r1"}\n\nevent: token\ndata: {"text": "Hi"}\n\n');
  assert.deepEqual(names(evs), ["meta", "token"]);
  assert.equal(evs[0].json.request_id, "r1");
  assert.equal(evs[1].json.text, "Hi");
});

test("an event split anywhere across chunks", () => {
  const frame = 'event: token\ndata: {"text": "split ✓"}\n\n';
  for (let i = 1; i < frame.length; i++) {
    const p = createSSEParser();
    const evs = [...p.push(frame.slice(0, i)), ...p.push(frame.slice(i))];
    assert.deepEqual(evs.map((e) => e.json), [{ text: "split ✓" }], `split at ${i}`);
  }
});

test("CRLF and CR line endings, including a CR at the end of a chunk", () => {
  const p = createSSEParser();
  const evs = [...p.push('event: done\r\ndata: {"answer": "ok"}\r'), ...p.push('\n\r\nevent: token\rdata: {"text": "x"}\r\r')];
  assert.deepEqual(names(evs), ["done", "token"]);
  assert.equal(evs[0].json.answer, "ok");
});

test("comments and keep-alive pings are ignored", () => {
  const p = createSSEParser();
  assert.deepEqual(p.push(": ping\n\n"), []);
  assert.deepEqual(names(p.push(': ping\n\nevent: meta\ndata: {}\n\n')), ["meta"]);
});

test("multi-line data is joined with newlines and non-JSON data is kept", () => {
  const p = createSSEParser();
  const [ev] = p.push("data: line one\ndata: line two\n\n");
  assert.equal(ev.event, "message");
  assert.equal(ev.data, "line one\nline two");
  assert.equal(ev.json, null);
});

test("flush returns a last event that had no blank line after it", () => {
  const p = createSSEParser();
  assert.deepEqual(p.push('event: done\ndata: {"answer": "a"}'), []);
  assert.deepEqual(p.flush().map((e) => e.json), [{ answer: "a" }]);
  assert.deepEqual(p.flush(), []);
});

test("footer text from /healthz", () => {
  const h = { index: { built_at: "2026-10-16T22:44:45Z", docs_lastmod_max: "2026-10-15",
                       repos: { olake: "d20c68e", "olake-ui": "56826cf" } } };
  assert.equal(footerText(h), "Index 2026-10-16 22:44 UTC · docs lastmod 2026-10-15 · olake@d20c68e");
  assert.equal(footerText({ index: null }), "");
  assert.equal(domainOf("https://github.com/datazip-inc/olake/blob/master/README.md"), "github.com");
  assert.equal(domainOf("not a url"), "");
});

test("request timeout: default 35 s (the server's 30 s ASK_TIMEOUT_S + 5), clamped to 5-600", async () => {
  const { DEFAULT_TIMEOUT_S, timeoutSeconds } = await import("../../web/embed-core.mjs");
  assert.equal(DEFAULT_TIMEOUT_S, 35);
  assert.equal(timeoutSeconds(null), 35);
  assert.equal(timeoutSeconds(""), 35);
  assert.equal(timeoutSeconds("abc"), 35);
  assert.equal(timeoutSeconds("240"), 240);
  assert.equal(timeoutSeconds("1"), 5);
  assert.equal(timeoutSeconds("9999"), 600);
});
