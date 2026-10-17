// The widget loader (web/widget.js) run against a small fake DOM: messages to the frame wait until it has loaded,
// and only messages from the frame on the api origin are obeyed; the CSS it injects keeps the open panel distinct
// from a dark host page. Run: node --test tests/web/*.test.mjs
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

  page.css = head.children.filter((c) => c.tagName === "STYLE").map((c) => c.textContent).join("\n");
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

// ---- the injected stylesheet. On a dark host page the open panel was nearly the page's colour and its shadow
// rgba(10,30,40,.3) invisible; the fix lives in the widget, so it holds on any host page.

// a tiny CSS reader for that one stylesheet (top-level rules and @media blocks, not a general parser)
const squash = (s) => s.replace(/\s+/g, " ").trim();
// selectors and @media preludes compare in one spelling: '@media (max-width: 640px)' -> '@media (max-width:640px)',
// 'html[data-theme="dark"]' -> 'html[data-theme=dark]', '0 12px 40px rgba(10, 30, 40, .3)' -> '... rgba(10,30,40,.3)'
const canon = (s) => squash(s).toLowerCase().replace(/["']/g, "").replace(/\s*([>+~,])\s*/g, "$1")
  .replace(/:\s+/g, ":").replace(/([([])\s+/g, "$1").replace(/\s+([)\]])/g, "$1");

// split on `sep` (one character, or " " for any run of whitespace) outside brackets and quotes
function splitTop(s, sep) {
  const out = [];
  let cur = "", depth = 0, quote = null;
  for (const ch of s) {
    if (quote) { if (ch === quote) quote = null; }
    else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(" || ch === "[") depth++;
    else if (ch === ")" || ch === "]") depth--;
    else if (!depth && (sep === " " ? /\s/.test(ch) : ch === sep)) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  return [...out, cur].map((x) => x.trim()).filter(Boolean);
}

const declarations = (body) => splitTop(body, ";").flatMap((d) => {
  const c = d.indexOf(":");
  if (c < 0) return [];
  const prop = d.slice(0, c).trim().toLowerCase(), value = squash(d.slice(c + 1));
  const important = /!\s*important$/i.test(value);
  return [{ prop, value: important ? value.replace(/\s*!\s*important$/i, "") : value, important }];
});

// rules in source order: { at: "" (top level) or e.g. "@media (max-width:640px)", pos, selectors, decls }
function cssRules(css) {
  const src = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];
  let i = 0;
  const upTo = (stops) => { // index of the next stop character outside brackets and quotes
    let j = i, depth = 0, quote = null;
    for (; j < src.length; j++) {
      const ch = src[j];
      if (quote) { if (ch === quote) quote = null; }
      else if (ch === '"' || ch === "'") quote = ch;
      else if (ch === "(" || ch === "[") depth++;
      else if (ch === ")" || ch === "]") depth--;
      else if (!depth && stops.includes(ch)) break;
    }
    return j;
  };
  const block = (at) => {
    while (i < src.length) {
      const j = upTo("{};"), prelude = squash(src.slice(i, j)), pos = i;
      i = j + 1;
      if (j >= src.length || src[j] === "}") return;
      if (src[j] === ";") continue;
      if (prelude.startsWith("@")) { block(squash(`${at} ${canon(prelude)}`)); continue; }
      const k = upTo("}");
      rules.push({ at, pos, selectors: splitTop(prelude, ",").map(canon), decls: declarations(src.slice(i, k)) });
      i = k + 1;
    }
  };
  block("");
  return rules;
}

// the declarations of `rules` merged in source order, the later one winning; all:initial drops the ones before it
function merged(rules) {
  const m = new Map();
  for (const { prop, value } of rules.flatMap((r) => r.decls)) {
    if (prop === "all") m.clear();
    m.set(prop, value);
  }
  return m;
}

// the border after the rules' declarations in source order; all:initial and the shorthand reset all three parts
function border(rules) {
  const edge = {};
  for (const { prop, value } of rules.flatMap((r) => r.decls)) {
    if (prop === "all" || prop === "border") Object.assign(edge, { width: "medium", style: "none", color: "currentcolor" });
    if (prop === "border") {
      for (const t of splitTop(value, " ")) {
        if (/^(none|hidden|dotted|dashed|solid|double|groove|ridge|inset|outset)$/.test(t)) edge.style = t;
        else if (/^(\d|\.\d|thin|medium|thick)/.test(t)) edge.width = t;
        else edge.color = t;
      }
    }
    if (/^border-(width|style|color)$/.test(prop)) edge[prop.slice(7)] = value;
  }
  return edge;
}

// "#rgb(a)", "#rrggbb(aa)", rgb() or rgba() with commas or spaces, black, white -> { r, g, b, a }; null otherwise
function color(text) {
  const s = (text ?? "").trim().toLowerCase();
  let m = /^#([0-9a-f]{3,8})$/.exec({ black: "#000", white: "#fff" }[s] ?? s);
  if (m && m[1].length !== 5 && m[1].length !== 7) {
    const [r, g, b, a = 255] = (m[1].length < 6 ? m[1].replace(/./g, "$&$&") : m[1]).match(/../g).map((x) => parseInt(x, 16));
    return { r, g, b, a: a / 255 };
  }
  m = /^rgba?\(([^)]*)\)$/.exec(s);
  if (!m) return null;
  const [r, g, b, a = "1"] = m[1].split(/[\s,/]+/).filter(Boolean);
  return { r: +r, g: +g, b: +b, a: a.endsWith("%") ? parseFloat(a) / 100 : +a };
}

// WCAG 2 relative luminance of a colour's rgb (its alpha aside)
const luminance = ({ r, g, b }) => [r, g, b].map((v) => v / 255)
  .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  .reduce((sum, v, k) => sum + v * [0.2126, 0.7152, 0.0722][k], 0);

// some layer of a box-shadow is black-ish (luminance <= .02) with alpha >= min
const blackShadow = (value, min) => !!value && value !== "none" && splitTop(value, ",").some((layer) => {
  const c = splitTop(layer, " ").map(color).find(Boolean);
  return !!c && luminance(c) <= 0.02 && c.a >= min;
});

// [ids, classes + attributes + pseudo-classes, types]; :where() adds nothing, :not(x) and :is(x) count as x
function specificity(selector) {
  let s = selector.replace(/:where\((?:[^()]|\([^()]*\))*\)/g, " ")
    .replace(/:(?:not|is)\(((?:[^()]|\([^()]*\))*)\)/g, " $1 ");
  const n = [0, 0, 0];
  for (const [re, k] of [[/\[[^\]]*\]/g, 1], [/::[\w-]+/g, 2], [/#[\w-]+/g, 0], [/[.:][\w-]+/g, 1], [/[a-z][\w-]*/gi, 2]]) {
    s = s.replace(re, () => { n[k]++; return " "; });
  }
  return n;
}
const outranks = (a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]; // > 0: a wins, 0: the later rule wins
// the subject (last compound) of a selector without :where(): ":where(html[data-theme=dark]) .x" -> ".x"
const subject = (sel) => splitTop(sel.replace(/[>+~]/g, " "), " ").at(-1).replace(/:where\((?:[^()]|\([^()]*\))*\)/g, "");
const px = (v) => (/^-?\d*\.?\d+(px)?$/.test(v ?? "") ? parseFloat(v) : NaN);

const RULES = cssRules(fakePage().css);
const rulesFor = (selector, at = "") => RULES.filter((r) => r.at === canon(at) && r.selectors.includes(canon(selector)));
const LIGHT_SHADOW = "0 12px 40px rgba(10,30,40,.3)";
const EDGE = /^(border(-(top|right|bottom|left))?(-(width|style|color))?|box-shadow)$/;

test("light: the open panel keeps its shadow and gains a 1px dark translucent hairline, inside its 400 x 600 box", () => {
  const base = rulesFor(".askolake-frame"), frame = merged(base), edge = border(base), c = color(edge.color);
  assert.ok(base.length, "there is a .askolake-frame rule");
  assert.equal(frame.get("box-sizing"), "border-box", "box-sizing:border-box keeps the border inside the panel's box");
  assert.equal(edge.width, "1px", `border width ${edge.width}: want 1px, declared after all:initial`);
  assert.equal(edge.style, "solid", `border style ${edge.style}: want solid, declared after all:initial`);
  assert.ok(c && luminance(c) <= 0.05 && c.a > 0 && c.a <= 0.25,
    `border colour ${edge.color}: want a dark translucent hairline (luminance <= .05, 0 < alpha <= .25)`);
  assert.equal(canon(frame.get("box-shadow") ?? ""), LIGHT_SHADOW, "the light-theme shadow stays as it is");
  assert.equal(frame.get("border-radius"), "14px");
});

for (const [name, at, scope] of [
  ["a dark host page (html[data-theme=dark])", "", ":where(html[data-theme=dark])"],
  ["the auto path (no data-theme on the host, prefers-color-scheme: dark)", "@media (prefers-color-scheme:dark)",
    ":where(html:not([data-theme=light]))"],
]) {
  test(`on ${name} the panel gets a light translucent edge and a black shadow, the launcher a black shadow`, () => {
    const inside = at && ` inside ${at}`;
    const frame = rulesFor(`${scope} .askolake-frame`, at), btn = rulesFor(`${scope} .askolake-btn`, at);
    assert.ok(frame.length, `no "${scope} .askolake-frame" rule${inside}: on a dark page the panel blends in`);
    const edge = border(frame).color, c = color(edge);
    assert.ok(c && luminance(c) >= 0.5 && c.a >= 0.15 && c.a < 1,
      `dark panel border colour ${edge}: want a light translucent edge (luminance >= .5, .15 <= alpha < 1)`);
    const shadow = merged(frame).get("box-shadow");
    assert.ok(blackShadow(shadow, 0.4), `dark panel box-shadow ${shadow}: want a black layer with alpha >= .4`);
    assert.ok(btn.length, `no "${scope} .askolake-btn" rule${inside}: the launcher's shadow vanishes on a dark page`);
    const glow = merged(btn).get("box-shadow");
    assert.ok(blackShadow(glow, 0.3), `dark launcher box-shadow ${glow}: want a black layer with alpha >= .3`);
    // :where() keeps both at the base rules' specificity (0,1,0): they win by coming after them
    for (const [rules, el] of [[frame, ".askolake-frame"], [btn, ".askolake-btn"]]) {
      const base = rulesFor(el);
      assert.ok(base.length && rules.every((r) => base.every((b) => r.pos > b.pos)),
        `"${scope} ${el}" must come after the base ${el} rule`);
    }
  });
}

test("on a phone (max-width:640px) the fullscreen panel has no border and no shadow, in any theme", () => {
  const phone = rulesFor(".askolake-frame", "@media (max-width:640px)");
  assert.ok(phone.length, "there is a .askolake-frame rule inside @media (max-width:640px)");
  const edge = border(phone), shadow = merged(phone).get("box-shadow");
  const shown = Object.entries(edge).map(([k, v]) => `${k} ${v}`).join(", ") || "not set";
  assert.ok(px(edge.width) === 0 || /^(none|hidden)$/.test(edge.style ?? ""), `phone panel border: ${shown}; want 0 or none`);
  assert.equal(shadow, "none", `phone panel box-shadow: ${shadow ?? "not set"}; want none`);
  // it wins only if every other rule that gives the frame a border or a shadow comes before it, at no higher
  // specificity and without !important; the dark rules among them
  const first = Math.min(...phone.filter((r) => r.decls.some((d) => EDGE.test(d.prop))).map((r) => r.pos));
  for (const r of RULES) {
    if (phone.includes(r) || !r.decls.some((d) => EDGE.test(d.prop))) continue;
    for (const s of r.selectors.filter((sel) => subject(sel) === ".askolake-frame")) {
      const o = outranks(specificity(s), specificity(".askolake-frame"));
      assert.ok(o < 0 || (o === 0 && r.pos < first),
        `"${s}"${r.at && ` (${r.at})`} outranks or follows the phone rule, so its border or shadow shows on a phone`);
      assert.ok(!r.decls.some((d) => EDGE.test(d.prop) && d.important), `"${s}" sets the panel's edge with !important`);
    }
  }
});
