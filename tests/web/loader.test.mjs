// The widget loader (web/widget.js) run against a small fake DOM: messages to the frame wait until it has loaded,
// and only messages from the frame on the api origin are obeyed. Run: node --test tests/web/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const SRC = readFileSync(new URL("../../web/widget.js", import.meta.url), "utf8");
const API = "http://localhost:8000";

function fakePage({ data = { api: API }, theme = null } = {}) {
  const posted = [];
  const winListeners = {};
  const docListeners = {};
  let observerCallback = null;
  const page = { posted, focused: null };

  function element(tag) {
    const classes = new Set();
    const e = {
      tagName: tag.toUpperCase(), attrs: {}, children: [], listeners: {}, dataset: {}, className: "",
      classList: {
        toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        contains: (c) => classes.has(c),
      },
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      appendChild(c) { this.children.push(c); return c; },
      addEventListener(t, f) { (this.listeners[t] ||= []).push(f); },
      fire(t, ev = {}) { for (const f of this.listeners[t] || []) f(ev); },
      focus() { page.focused = this; },
    };
    if (tag === "iframe") {
      e.loaded = false;
      e.contentWindow = { postMessage: (msg, origin) => posted.push({ msg, origin, afterLoad: e.loaded }) };
    }
    return e;
  }

  const html = element("html");
  if (theme) html.setAttribute("data-theme", theme);
  const body = element("body");
  const head = element("head");
  const script = element("script");
  script.src = API + "/widget.js";
  Object.assign(script.dataset, data);
  const document = {
    currentScript: script, body, head, documentElement: html,
    createElement: element,
    createElementNS: (_ns, tag) => element(tag),
    createTextNode: (text) => ({ text }),
    addEventListener: (t, f) => (docListeners[t] ||= []).push(f),
  };
  class MutationObserver {
    constructor(cb) { observerCallback = cb; }
    observe() {}
  }
  const window = { addEventListener: (t, f) => (winListeners[t] ||= []).push(f) };
  const ctx = { window, document, location: { href: "https://docs.example.com/page" }, URL, URLSearchParams,
                MutationObserver, String, Math, parseInt };
  vm.runInNewContext(SRC, ctx);

  page.button = body.children.find((c) => c.className === "askolake-btn");
  page.frame = () => body.children.find((c) => c.tagName === "IFRAME");
  page.click = () => page.button.fire("click");
  page.load = () => { page.frame().loaded = true; page.frame().fire("load"); };
  page.message = (ev) => (winListeners.message || []).forEach((f) => f(ev));
  page.key = (key) => (docListeners.keydown || []).forEach((f) => f({ key }));
  page.setTheme = (t) => { html.setAttribute("data-theme", t); observerCallback && observerCallback([]); };
  return page;
}

test("nothing is posted to the frame before it has loaded; queued messages go out on load", () => {
  const p = fakePage({ theme: "dark" });
  p.click();
  assert.ok(p.frame(), "the first click creates the iframe");
  p.setTheme("light"); // the host theme changes while the frame is still loading
  p.message({ origin: API, source: p.frame().contentWindow, data: { type: "askolake:ready" } });
  assert.deepEqual(p.posted, [], "no postMessage while the frame still holds about:blank");
  p.load();
  assert.ok(p.posted.length >= 2 && p.posted.every((m) => m.afterLoad && m.origin === API));
  const types = p.posted.map((m) => m.msg.type);
  assert.ok(types.includes("askolake:open"));
  assert.equal(p.posted.filter((m) => m.msg.type === "askolake:theme").at(-1).msg.theme, "light");
});

test("after load, messages go out immediately and only to the api origin", () => {
  const p = fakePage();
  p.click();
  p.load();
  p.posted.length = 0;
  p.setTheme("dark");
  const plain = JSON.parse(JSON.stringify(p.posted.map((m) => [m.msg, m.origin]))); // objects from the vm realm
  assert.deepEqual(plain, [[{ type: "askolake:theme", theme: "dark" }, API]]);
});

test("the frame closes on its own close message or Esc, and focus returns to the launcher", () => {
  const p = fakePage();
  p.click();
  p.load();
  const frame = p.frame();
  p.message({ origin: "https://evil.example", source: frame.contentWindow, data: { type: "askolake:close" } });
  assert.equal(frame.classList.contains("askolake-hidden"), false, "a foreign origin cannot close it");
  p.message({ origin: API, source: {}, data: { type: "askolake:close" } });
  assert.equal(frame.classList.contains("askolake-hidden"), false, "another window cannot close it");
  p.message({ origin: API, source: frame.contentWindow, data: { type: "askolake:close" } });
  assert.equal(frame.classList.contains("askolake-hidden"), true);
  assert.equal(p.focused, p.button);
  assert.equal(p.button.getAttribute("aria-expanded"), "false");
  p.click();
  assert.equal(frame.classList.contains("askolake-hidden"), false);
  p.key("Escape");
  assert.equal(frame.classList.contains("askolake-hidden"), true);
});

test("options: api from data-api, title and timeout into the frame URL, accent only when it is a hex color", () => {
  const p = fakePage({ data: { api: API + "/", title: "Docs help", timeout: "240", accent: "red;}" } });
  p.click();
  const src = new URL(p.frame().src);
  assert.equal(src.origin + src.pathname, API + "/embed");
  assert.equal(src.searchParams.get("title"), "Docs help");
  assert.equal(src.searchParams.get("timeout"), "240");
  assert.equal(src.searchParams.get("accent"), null);
  assert.equal(p.button.getAttribute("aria-label"), "Ask OLake");
});

test("the frame gets a 35 s timeout by default, so the server's degraded answer (sent at 30 s) arrives first", () => {
  const p = fakePage();
  p.click();
  assert.equal(new URL(p.frame().src).searchParams.get("timeout"), "35");
});
