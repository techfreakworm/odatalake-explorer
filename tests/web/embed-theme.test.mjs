// The embed's palette (web/embed.css): the two dark blocks stay one theme, the dark panel sits visibly lighter than
// the demo page's dark background (it was almost the same colour), and text keeps its WCAG contrast in both themes.
// Run: node --test tests/web/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// ---- a tiny CSS reader, enough for these stylesheets (not a general parser)

const squash = (s) => s.replace(/\s+/g, " ").trim();
// selectors and @media preludes compare in one spelling: '@media (prefers-color-scheme: dark)' ->
// '@media (prefers-color-scheme:dark)', ':root[data-theme="dark"]' -> ':root[data-theme=dark]'
const canon = (s) => squash(s).toLowerCase().replace(/["']/g, "").replace(/\s*([>+~,])\s*/g, "$1")
  .replace(/:\s+/g, ":").replace(/([([])\s+/g, "$1").replace(/\s+([)\]])/g, "$1");

// split on `sep` (one character) outside brackets and quotes
function splitTop(s, sep) {
  const out = [];
  let cur = "", depth = 0, quote = null;
  for (const ch of s) {
    if (quote) { if (ch === quote) quote = null; }
    else if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(" || ch === "[") depth++;
    else if (ch === ")" || ch === "]") depth--;
    else if (!depth && ch === sep) { out.push(cur); cur = ""; continue; }
    cur += ch;
  }
  return [...out, cur].map((x) => x.trim()).filter(Boolean);
}

const declarations = (body) => splitTop(body, ";").flatMap((d) => {
  const c = d.indexOf(":");
  if (c < 0) return [];
  const prop = d.slice(0, c).trim();
  return [{ prop: prop.startsWith("--") ? prop : prop.toLowerCase(), value: squash(d.slice(c + 1)) }];
});

// rules in source order: { at: "" (top level) or e.g. "@media (prefers-color-scheme:dark)", selectors, decls }
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
      const j = upTo("{};"), prelude = squash(src.slice(i, j));
      i = j + 1;
      if (j >= src.length || src[j] === "}") return;
      if (src[j] === ";") continue;
      if (prelude.startsWith("@")) { block(squash(`${at} ${canon(prelude)}`)); continue; }
      const k = upTo("}");
      rules.push({ at, selectors: splitTop(prelude, ",").map(canon), decls: declarations(src.slice(i, k)) });
      i = k + 1;
    }
  };
  block("");
  return rules;
}

// every declaration of the rules for exactly `selector` (in the `at` context), the later one winning
const declared = (rules, selector, at = "") => Object.fromEntries(rules
  .filter((r) => r.at === canon(at) && r.selectors.includes(canon(selector)))
  .flatMap((r) => r.decls.map((d) => [d.prop, d.value])));

// ---- colours

// "#rgb(a)", "#rrggbb(aa)", rgb() or rgba() with commas or spaces -> { r, g, b, a }; null otherwise
function color(text) {
  const s = (text ?? "").trim().toLowerCase();
  let m = /^#([0-9a-f]{3,8})$/.exec(s);
  if (m && m[1].length !== 5 && m[1].length !== 7) {
    const [r, g, b, a = 255] = (m[1].length < 6 ? m[1].replace(/./g, "$&$&") : m[1]).match(/../g).map((x) => parseInt(x, 16));
    return { r, g, b, a: a / 255 };
  }
  m = /^rgba?\(([^)]*)\)$/.exec(s);
  if (!m) return null;
  const [r, g, b, a = "1"] = m[1].split(/[\s,/]+/).filter(Boolean);
  return { r: +r, g: +g, b: +b, a: a.endsWith("%") ? parseFloat(a) / 100 : +a };
}

// WCAG 2 relative luminance and contrast ratio
const luminance = ({ r, g, b }) => [r, g, b].map((v) => v / 255)
  .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  .reduce((sum, v, k) => sum + v * [0.2126, 0.7152, 0.0722][k], 0);
const contrast = (x, y) => {
  const [hi, lo] = [luminance(x), luminance(y)].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
};

// a theme token as written, var(--x) resolved within the same theme
function value(theme, name) {
  let v = theme[name];
  for (let n = 0; n < 8 && /^var\(/.test(v ?? ""); n++) {
    const [, ref, fallback] = /^var\(\s*(--[\w-]+)\s*(?:,\s*(.*))?\)$/.exec(v) ?? [];
    v = theme[ref] ?? fallback;
  }
  return v;
}
// a theme token as an opaque colour: a translucent one is laid over the theme's --bg
function rgb(theme, name) {
  const c = color(value(theme, name));
  assert.ok(c, `${name} is ${theme[name]}, not a colour this test reads`);
  if (c.a >= 1 || name === "--bg") return c;
  const bg = rgb(theme, "--bg"), mix = (k) => c[k] * c.a + bg[k] * (1 - c.a);
  return { r: mix("r"), g: mix("g"), b: mix("b"), a: 1 };
}

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const EMBED = cssRules(read("../../web/embed.css"));
const DEMO = cssRules([...read("../../web/demo/index.html").matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)]
  .map((m) => m[1]).join("\n"));
const LIGHT = declared(EMBED, ":root");
const DARK_AUTO = declared(EMBED, ':root:not([data-theme="light"])', "@media (prefers-color-scheme: dark)");
const DARK = declared(EMBED, ':root[data-theme="dark"]');
// a dark block only overrides :root, so --t-docs (var(--accent)) and the rest come from there; +1: each step of the
// --bg, --code-bg, --surface, --line ramp is lighter, -1: darker
const THEMES = [["light", LIGHT, -1], ["dark (prefers-color-scheme)", { ...LIGHT, ...DARK_AUTO }, 1],
  ["dark (data-theme=dark)", { ...LIGHT, ...DARK }, 1]];

test("the two dark blocks, prefers-color-scheme and data-theme=dark, declare the same tokens (guard)", () => {
  assert.ok(Object.keys(DARK_AUTO).length,
    'a :root:not([data-theme="light"]) block inside @media (prefers-color-scheme: dark)');
  assert.ok(Object.keys(DARK).length, 'a :root[data-theme="dark"] block');
  assert.deepEqual(DARK_AUTO, DARK);
});

test("the dark panel is lighter than the demo page's dark background, at a contrast ratio of at least 1.1", () => {
  const page = declared(DEMO, ':root[data-theme="dark"]')["--bg"], host = color(page);
  assert.ok(host, `the demo page's dark --bg is ${page}`);
  for (const [name, dark] of [["prefers-color-scheme", DARK_AUTO], ["data-theme=dark", DARK]]) {
    const bg = color(dark["--bg"]);
    assert.ok(bg, `the ${name} block's --bg is ${dark["--bg"]}`);
    const lighter = luminance(bg) > luminance(host), ratio = contrast(bg, host);
    assert.ok(lighter && ratio >= 1.1, `the ${name} --bg ${dark["--bg"]} is ${lighter ? "lighter" : "darker"} than the ` +
      `demo page's ${page} at contrast ${ratio.toFixed(3)}: the open panel blends into the page (want lighter, >= 1.1)`);
  }
});

for (const [name, theme] of THEMES) {
  test(`${name}: text keeps its contrast: ink >= 7; muted, accent and every --t-* >= 4.5 on --bg; muted >= 4.5 on ` +
    "--surface (guard)", () => {
    const tags = Object.keys(theme).filter((k) => k.startsWith("--t-"));
    assert.ok(tags.includes("--t-docs") && tags.length >= 6, `the source-type tokens: ${tags.join(" ")}`);
    const pairs = [["--ink", "--bg", 7], ["--muted", "--bg", 4.5], ["--accent", "--bg", 4.5],
      ...tags.map((t) => [t, "--bg", 4.5]), ["--muted", "--surface", 4.5]];
    for (const [fg, bg, min] of pairs) {
      const ratio = contrast(rgb(theme, fg), rgb(theme, bg));
      assert.ok(ratio >= min,
        `${fg} ${value(theme, fg)} on ${bg} ${value(theme, bg)}: contrast ${ratio.toFixed(2)}, want >= ${min}`);
    }
  });
}

for (const [name, theme, way] of THEMES) {
  test(`${name}: --code-bg, --surface and --line each step further from --bg, so they move with it (guard)`, () => {
    const ramp = ["--bg", "--code-bg", "--surface", "--line"];
    for (let k = 1; k < ramp.length; k++) {
      const [prev, cur] = [ramp[k - 1], ramp[k]].map((t) => luminance(rgb(theme, t)));
      assert.ok(way * (cur - prev) > 0, `${ramp[k]} ${value(theme, ramp[k])} should be ${way > 0 ? "lighter" : "darker"} ` +
        `than ${ramp[k - 1]} ${value(theme, ramp[k - 1])}`);
    }
  });
}
