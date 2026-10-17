// The demo page (web/demo/index.html): its "On this page" nav stays in view right under the sticky header, with
// its own scroll, and every anchor lands clear of the header. Reads the page's <style> with a tiny rule reader
// (top-level rules and @media blocks). Run: node --test tests/web/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// ---- a tiny CSS reader, enough for this page's stylesheet (not a general parser)

const squash = (s) => s.replace(/\s+/g, " ").trim();
// selectors and @media preludes compare in one spelling: '@media (max-width: 760px)' -> '@media (max-width:760px)',
// ':root[data-theme="dark"]' -> ':root[data-theme=dark]', 'a > b' -> 'a>b'
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
  const prop = d.slice(0, c).trim();
  return [{ prop: prop.startsWith("--") ? prop : prop.toLowerCase(), value: squash(d.slice(c + 1)) }];
});

// rules in source order: { at: "" (top level) or e.g. "@media (max-width:760px)", selectors, decls: [{ prop, value }] }
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

const find = (selector, at = "") => RULES.filter((r) => r.at === canon(at) && r.selectors.includes(canon(selector)));
// the declarations of `rules` merged in source order, the later one winning
const merged = (rules) => new Map(rules.flatMap((r) => r.decls.map((d) => [d.prop, d.value])));
// a length in px ("0", "56px", or rem at the default 16px root size); NaN for anything else
const px = (v) => {
  const m = /^(-?\d*\.?\d+)(px|rem)?$/.exec(v ?? "");
  return m ? Number(m[1]) * (m[2] === "rem" ? 16 : 1) : NaN;
};
const reEscape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); // for use inside a RegExp
// the subject (last compound) of a selector: "nav a:hover" -> "a:hover", ":not(pre)>code" -> "code"
const subject = (sel) => splitTop(sel.replace(/[>+~]/g, " "), " ").at(-1);

const PAGE = readFileSync(new URL("../../web/demo/index.html", import.meta.url), "utf8");
const MARKUP = PAGE.replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, "");
const RULES = cssRules([...PAGE.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)].map((m) => m[1]).join("\n"));
const TOP = merged(find(".top"));
const HEADER = TOP.get("height");
const LINKS = [...(/<nav\b[^>]*>([\s\S]*?)<\/nav>/i.exec(MARKUP)?.[1] ?? "")
  .matchAll(/<a\b[^>]*\bhref="(#[^"]*)"[^>]*>([\s\S]*?)<\/a>/gi)].map((m) => [m[1], squash(m[2].replace(/<[^>]*>/g, ""))]);

// ---- the header and the nav

test("the header stays a 56px bar stuck to the top of the viewport (guard)", () => {
  assert.equal(TOP.get("position"), "sticky", ".top is the sticky header");
  assert.equal(px(TOP.get("top")), 0, ".top sticks at top: 0");
  assert.equal(HEADER, "56px", ".top is 56px tall");
});

test("the On this page nav sticks right under the header and scrolls on its own when it is taller than the viewport",
  () => {
    const rules = find("nav"), nav = merged(rules);
    assert.equal(nav.get("position"), "sticky",
      `nav { position: ${nav.get("position") ?? "static"} } scrolls away with the page; it should be sticky`);
    assert.equal(px(nav.get("top")), px(HEADER),
      `nav should stick at top: ${HEADER}, the header's height (top: ${nav.get("top")})`);
    assert.match(nav.get("align-self") ?? "", /^(start|self-start|flex-start)$/,
      `nav needs align-self: start so the grid row does not stretch it to the page height ` +
      `(align-self: ${nav.get("align-self")})`);
    const box = ["height", "max-height"].filter((p) => nav.has(p)).map((p) => `${p}: ${canon(nav.get(p))}`);
    assert.ok(box.some((d) => d.endsWith(`: calc(100vh - ${HEADER})`) || d.endsWith(`: calc(100dvh - ${HEADER})`)),
      `nav needs height (or max-height) calc(100vh - ${HEADER}) to fit under the header; has ${box.join(", ") || "neither"}` +
      `, min-height: ${nav.get("min-height")}`);
    let overflowY = "visible";
    for (const { prop, value } of rules.flatMap((r) => r.decls)) {
      if (prop === "overflow") overflowY = value.split(" ").at(-1); // "overflow: x y" or one value for both
      if (prop === "overflow-y") overflowY = value;
    }
    assert.match(overflowY, /^(auto|scroll)$/,
      `a nav taller than the viewport needs its own scroll (overflow-y: ${overflowY})`);
  });

test("nothing around the nav turns sticky off: html, body and .layout keep overflow visible (guard)", () => {
  // an ancestor with overflow other than visible becomes the nav's scroll container and pins it to that box
  for (const r of RULES) {
    const ancestors = r.selectors.filter((s) => {
      const bare = subject(s).replace(/\[[^\]]*\]/g, "").replace(/::?[\w-]+(\((?:[^()]|\([^()]*\))*\))?/g, "");
      return ["", "*", "html", "body", "div", ".layout", "div.layout"].includes(bare);
    });
    if (!ancestors.length) continue;
    for (const { prop, value } of r.decls) {
      if (!/^overflow(-[xy])?$/.test(prop)) continue;
      assert.ok(value.split(" ").every((v) => v === "visible"),
        `${ancestors.join(", ")} { ${prop}: ${value} }${r.at && ` in ${r.at}`} breaks the sticky nav`);
    }
  }
});

test("on a phone (max-width: 760px) the nav is still hidden (guard)", () => {
  assert.equal(merged(find("nav", "@media (max-width: 760px)")).get("display"), "none",
    "@media (max-width: 760px) keeps nav { display: none }");
});

test("the nav keeps its right border, side background and padding (guard)", () => {
  const nav = merged(find("nav"));
  assert.ok(nav.has("border-right"), "nav keeps border-right");
  assert.ok(nav.has("background") || nav.has("background-color"), "nav keeps its background");
  assert.ok(nav.has("padding"), "nav keeps its padding");
});

// ---- the anchors

test("the nav links are Overview, Script tag, Plain iframe, Docusaurus, Options and Privacy, each with a target (guard)",
  () => {
    assert.deepEqual(LINKS.map(([, label]) => label),
      ["Overview", "Script tag", "Plain iframe", "Docusaurus", "Options", "Privacy"]);
    const ids = new Set([...MARKUP.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
    for (const [href, label] of LINKS) assert.ok(ids.has(href.slice(1)), `"${label}" points at ${href}: no such id`);
  });

test("every heading a nav link points at clears the sticky header when scrolled to (scroll-margin-top)", () => {
  assert.ok(LINKS.length, "the nav has links");
  for (const [href] of LINKS) {
    const id = href.slice(1);
    const tag = new RegExp(`<([a-z][a-z0-9]*)\\b[^>]*\\bid="${reEscape(id)}"`, "i").exec(MARKUP)?.[1].toLowerCase();
    assert.ok(tag, `no element with id="${id}"`);
    // top-level rules for that element: its tag, #id, tag#id, [id], :target or *
    const rules = RULES.filter((r) => r.at === "" && r.selectors.some((s) =>
      ["", "*", tag, `#${id}`, `${tag}#${id}`].includes(subject(s).replace(/\[[^\]]*\]|:target/g, ""))));
    let margin = 0;
    for (const { prop, value } of rules.flatMap((r) => r.decls)) {
      if (prop === "scroll-margin") margin = px(value.split(" ")[0]);
      if (prop === "scroll-margin-top" || prop === "scroll-margin-block-start") margin = px(value);
    }
    assert.ok(margin >= px(HEADER),
      `${href} lands on <${tag}> with scroll-margin-top ${margin}px, so it hides under the ${HEADER} sticky header`);
  }
});
