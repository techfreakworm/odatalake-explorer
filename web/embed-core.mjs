// Ask OLake embed core: Markdown -> a safe node tree, SSE frame parsing and small helpers.
// No DOM access here, so `node --test tests/web/*.test.mjs` can import it.
//
// Safety model: model text never becomes markup. The parser emits nodes {tag, attrs, children} from a fixed
// allow-list and {text} leaves; the browser builds them with createElement / setAttribute / createTextNode (toDOM),
// never innerHTML. toHTML escapes every text and attribute value and exists for tests.

const ALLOWED_TAGS = new Set(["p", "h3", "h4", "h5", "h6", "ul", "ol", "li", "pre", "code", "strong", "em", "a", "table",
  "thead", "tbody", "tr", "th", "td", "blockquote", "hr", "br", "del"]);
const ALLOWED_ATTRS = new Set(["href", "title", "target", "rel", "class", "data-n", "start"]);
const VOID_TAGS = new Set(["hr", "br"]);
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) => ESC[c]);
}

/** The URL if it is an absolute https URL, else null (javascript:, data:, http:, relative ... are all refused). */
export function safeUrl(href) {
  if (typeof href !== "string") return null;
  const s = href.trim();
  if (!/^https:\/\//i.test(s)) return null;
  try {
    const u = new URL(s);
    return u.protocol === "https:" ? u.href : null;
  } catch {
    return null;
  }
}

export function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

// The browser waits a little longer than the server's whole-request bound (ASK_TIMEOUT_S, 30 s by default), so when
// the LLM is slow the server's degraded "most relevant pages" answer arrives before the browser gives up.
export const DEFAULT_TIMEOUT_S = 35;

/** Seconds to wait for an answer: the ?timeout= / data-timeout value, clamped to 5-600, else DEFAULT_TIMEOUT_S. */
export function timeoutSeconds(raw) {
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? Math.min(600, Math.max(5, n)) : DEFAULT_TIMEOUT_S;
}

const el = (tag, attrs = {}, children = []) => ({ tag, attrs, children });
const tx = (text) => ({ text });

// ------------------------------------------------------------------ blocks

const FENCE = /^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$/;
const HEADING = /^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;
const HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^ {0,3}> ?(.*)$/;
const UL = /^( *)([-*+])[ \t]+(.*)$/;
const OL = /^( *)(\d{1,9})[.)][ \t]+(.*)$/;
const TABLE_SEP = /^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/;

/** Parse Markdown into a node tree. opts.cites = number of citations; [n] with 1 <= n <= cites becomes a link. */
export function parseMarkdown(src, opts = {}) {
  const ctx = { cites: Number.isInteger(opts.cites) ? opts.cites : 0 };
  const lines = String(src ?? "").replace(/\r\n?/g, "\n").split("\n");
  return parseBlocks(lines, ctx);
}

function indentOf(line) {
  return line.length - line.replace(/^ +/, "").length;
}

function isTableStart(lines, i) {
  return lines[i].includes("|") && i + 1 < lines.length && lines[i + 1].includes("-") && TABLE_SEP.test(lines[i + 1]);
}

function startsBlock(lines, i) {
  const line = lines[i];
  return FENCE.test(line) || HEADING.test(line) || HR.test(line) || QUOTE.test(line) ||
    (UL.test(line) && indentOf(line) < 4) || (OL.test(line) && indentOf(line) < 4) || isTableStart(lines, i);
}

function parseBlocks(lines, ctx) {
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (!line.trim()) {
      i++;
    } else if ((m = FENCE.exec(line))) {
      const [, indent, fence, lang] = m;
      const body = [];
      i++;
      while (i < lines.length && !isClosingFence(lines[i], fence)) body.push(lines[i++]);
      i++; // the closing fence, or past the end while a reply is still streaming
      const code = body.map((l) => l.slice(Math.min(indent.length, indentOf(l)))).join("\n");
      const cls = sanitizeLang(lang);
      out.push(el("pre", {}, [el("code", cls ? { class: "language-" + cls } : {}, [tx(code)])]));
    } else if ((m = HEADING.exec(line))) {
      out.push(el("h" + Math.min(6, m[1].length + 2), {}, parseInline(m[2], ctx)));
      i++;
    } else if (HR.test(line)) {
      out.push(el("hr"));
      i++;
    } else if (QUOTE.test(line)) {
      const inner = [];
      while (i < lines.length && (m = QUOTE.exec(lines[i]))) {
        inner.push(m[1]);
        i++;
      }
      out.push(el("blockquote", {}, parseBlocks(inner, ctx)));
    } else if (UL.test(line) || OL.test(line)) {
      const [node, next] = parseList(lines, i, ctx);
      out.push(node);
      i = next;
    } else if (isTableStart(lines, i)) {
      const [node, next] = parseTable(lines, i, ctx);
      out.push(node);
      i = next;
    } else {
      const para = [line.trim()];
      i++;
      while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) para.push(lines[i++].trim());
      out.push(el("p", {}, parseInline(para.join("\n"), ctx)));
    }
  }
  return out;
}

function isClosingFence(line, fence) {
  const s = line.trim();
  return s.length >= fence.length && s[0] === fence[0] && /^(`+|~+)$/.test(s);
}

function sanitizeLang(lang) {
  const m = /^[A-Za-z0-9_+#.-]{1,30}/.exec(lang || "");
  return m ? m[0].toLowerCase() : "";
}

function parseList(lines, start, ctx) {
  const first = lines[start];
  const ordered = !UL.test(first);
  const RX = ordered ? OL : UL;
  const base = indentOf(first);
  const items = [];
  let i = start;
  let startNum = 1;
  while (i < lines.length) {
    const m = RX.exec(lines[i]);
    if (!m || indentOf(lines[i]) > base + 1) break;
    if (!items.length && ordered) startNum = parseInt(m[2], 10);
    const content = [m[3]];
    const rest = [];
    i++;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) {
        // a blank line continues the item only if indented content (or the next item) follows
        let j = i + 1;
        while (j < lines.length && !lines[j].trim()) j++;
        if (j < lines.length && indentOf(lines[j]) > base && !(RX.test(lines[j]) && indentOf(lines[j]) <= base + 1)) {
          rest.push(...lines.slice(i, j));
          i = j;
          continue;
        }
        break;
      }
      const ind = indentOf(line);
      if (ind > base && !(RX.test(line) && ind <= base + 1)) {
        rest.push(line); // indented continuation: nested lists, code fences, paragraphs
      } else if (ind <= base + 1 && (UL.test(line) || OL.test(line))) {
        break; // the next item, or a different list
      } else if (!rest.length && !startsBlock(lines, i)) {
        content.push(line.trim()); // lazy paragraph continuation
      } else {
        break;
      }
      i++;
    }
    const dedent = Math.min(...rest.filter((l) => l.trim()).map(indentOf), Infinity);
    const body = parseBlocks([...content, ...rest.map((l) => (l.trim() ? l.slice(dedent) : ""))], ctx);
    const children = body.length && body[0].tag === "p" ? [...body[0].children, ...body.slice(1)] : body;
    items.push(el("li", {}, children));
    // a blank line between items keeps the list going
    let j = i;
    while (j < lines.length && !lines[j].trim()) j++;
    if (j > i && j < lines.length && RX.test(lines[j]) && indentOf(lines[j]) <= base + 1) i = j;
  }
  const attrs = ordered && startNum !== 1 ? { start: String(startNum) } : {};
  return [el(ordered ? "ol" : "ul", attrs, items), i];
}

function splitRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells = [];
  let cur = "";
  for (let k = 0; k < s.length; k++) {
    if (s[k] === "\\" && s[k + 1] === "|") {
      cur += "|";
      k++;
    } else if (s[k] === "|") {
      cells.push(cur.trim());
      cur = "";
    } else {
      cur += s[k];
    }
  }
  cells.push(cur.trim());
  return cells;
}

function parseTable(lines, start, ctx) {
  const head = splitRow(lines[start]);
  const align = splitRow(lines[start + 1]).map((c) => {
    const left = c.startsWith(":"), right = c.endsWith(":");
    return left && right ? "al-c" : right ? "al-r" : "";
  });
  const cell = (tag, text, k) => el(tag, align[k] ? { class: align[k] } : {}, parseInline(text, ctx));
  const rows = [];
  let i = start + 2;
  while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
    const cells = splitRow(lines[i]);
    rows.push(el("tr", {}, head.map((_, k) => cell("td", cells[k] ?? "", k))));
    i++;
  }
  const thead = el("thead", {}, [el("tr", {}, head.map((h, k) => cell("th", h, k)))]);
  return [el("table", {}, rows.length ? [thead, el("tbody", {}, rows)] : [thead]), i];
}

// ------------------------------------------------------------------ inline

const INLINE = new RegExp([
  "\\\\([\\\\`*_{}\\[\\]()#+\\-.!|<>~])", // 1 backslash escape
  "(`+)([^`]|[^`][\\s\\S]*?[^`])\\2(?!`)", // 2,3 code span
  "\\[(\\d{1,2})\\](?!\\()", // 4 citation marker
  "\\[([^\\]\\n]+)\\]\\(\\s*([^()\\s]*(?:\\([^()\\s]*\\)[^()\\s]*)*)(?:\\s+\"((?:[^\"\\\\\\n]|\\\\.)*)\")?\\s*\\)", // 5,6,7 link
  "<(https:\\/\\/[^\\s<>]+)>", // 8 angle autolink
  "(https:\\/\\/[^\\s<>\"'`)\\]]*[^\\s<>\"'`)\\].,;:!?])", // 9 bare https URL
  "\\*\\*(?=\\S)([\\s\\S]*?\\S)\\*\\*", // 10 bold
  "(?<![\\w_])__(?=\\S)([\\s\\S]*?\\S)__(?![\\w_])", // 11 bold
  "(?<![\\w*])\\*(?=[^\\s*])([^*\\n]*?[^\\s*])\\*(?![\\w*])", // 12 italic
  "(?<![\\w_])_(?=[^\\s_])([^_\\n]*?[^\\s_])_(?![\\w_])", // 13 italic
  "~~(?=\\S)([\\s\\S]*?\\S)~~", // 14 strikethrough
].join("|"), "g");

function pushText(out, s) {
  const parts = s.split("\n");
  parts.forEach((p, k) => {
    if (k) out.push(el("br"));
    if (p) out.push(tx(p));
  });
}

function link(label, href, title, ctx) {
  const url = safeUrl(href);
  if (!url) return parseInline(label, ctx);
  const attrs = { href: url };
  if (title) attrs.title = title.replace(/\\(.)/g, "$1");
  attrs.target = "_blank";
  attrs.rel = "noopener noreferrer";
  return [el("a", attrs, parseInline(label, ctx))];
}

function parseInline(text, ctx) {
  const out = [];
  let pos = 0;
  INLINE.lastIndex = 0;
  const rx = new RegExp(INLINE.source, "g"); // a private copy: parseInline recurses
  let m;
  while ((m = rx.exec(text))) {
    if (m.index > pos) pushText(out, text.slice(pos, m.index));
    pos = m.index + m[0].length;
    if (m[1] !== undefined) {
      pushText(out, m[1]);
    } else if (m[2] !== undefined) {
      let code = m[3];
      if (/^ .* $/.test(code) && code.trim()) code = code.slice(1, -1);
      out.push(el("code", {}, [tx(code)]));
    } else if (m[4] !== undefined) {
      const n = parseInt(m[4], 10);
      if (n >= 1 && n <= ctx.cites) out.push(el("a", { href: "#cite-" + n, class: "cite", "data-n": String(n) }, [tx(String(n))]));
      else pushText(out, m[0]);
    } else if (m[5] !== undefined) {
      out.push(...link(m[5], m[6], m[7], ctx));
    } else if (m[8] !== undefined || m[9] !== undefined) {
      const raw = m[8] ?? m[9];
      const url = safeUrl(raw);
      if (url) out.push(el("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, [tx(raw)]));
      else pushText(out, m[0]);
    } else if (m[10] !== undefined || m[11] !== undefined) {
      out.push(el("strong", {}, parseInline(m[10] ?? m[11], ctx)));
    } else if (m[12] !== undefined || m[13] !== undefined) {
      out.push(el("em", {}, parseInline(m[12] ?? m[13], ctx)));
    } else if (m[14] !== undefined) {
      out.push(el("del", {}, parseInline(m[14], ctx)));
    }
  }
  if (pos < text.length) pushText(out, text.slice(pos));
  return out;
}

// ------------------------------------------------------------------ output

/** Escaped HTML for a node tree (tests and debugging; the browser uses toDOM). */
export function toHTML(nodes) {
  return nodes.map(nodeHTML).join("");
}

function nodeHTML(n) {
  if ("text" in n) return escapeHTML(n.text);
  if (!ALLOWED_TAGS.has(n.tag)) return toHTML(n.children || []);
  const attrs = Object.entries(n.attrs || {}).filter(([k]) => ALLOWED_ATTRS.has(k))
    .map(([k, v]) => ` ${k}="${escapeHTML(v)}"`).join("");
  return VOID_TAGS.has(n.tag) ? `<${n.tag}${attrs}>` : `<${n.tag}${attrs}>${toHTML(n.children || [])}</${n.tag}>`;
}

/** Build DOM nodes. hooks.element(domElement, node) may return a replacement element (e.g. a code block wrapper). */
export function toDOM(nodes, doc, hooks = {}) {
  const frag = doc.createDocumentFragment();
  for (const n of nodes) frag.appendChild(nodeDOM(n, doc, hooks));
  return frag;
}

function nodeDOM(n, doc, hooks) {
  if ("text" in n) return doc.createTextNode(n.text);
  const e = doc.createElement(ALLOWED_TAGS.has(n.tag) ? n.tag : "span");
  for (const [k, v] of Object.entries(n.attrs || {})) {
    if (!ALLOWED_ATTRS.has(k)) continue;
    if (k === "href" && !(String(v).startsWith("#cite-") || safeUrl(String(v)))) continue;
    e.setAttribute(k, String(v));
  }
  for (const c of n.children || []) e.appendChild(nodeDOM(c, doc, hooks));
  return (hooks.element && hooks.element(e, n)) || e;
}

// ------------------------------------------------------------------ SSE

/** Incremental text/event-stream parser: push(decodedText) -> events; flush() at the end of the stream. */
export function createSSEParser() {
  let buf = "";
  let event = "";
  let data = [];
  let pendingCR = false; // the last chunk ended with \r: drop a \n that starts the next one

  function dispatch(out) {
    if (!data.length && !event) return;
    const ev = { event: event || "message", data: data.join("\n"), json: null };
    try {
      ev.json = JSON.parse(ev.data);
    } catch {
      ev.json = null;
    }
    event = "";
    data = [];
    out.push(ev);
  }

  function line(text, out) {
    if (text === "") return dispatch(out);
    if (text[0] === ":") return; // comment, e.g. the keep-alive ping
    const c = text.indexOf(":");
    const field = c < 0 ? text : text.slice(0, c);
    let value = c < 0 ? "" : text.slice(c + 1);
    if (value[0] === " ") value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  return {
    push(chunk) {
      if (pendingCR && chunk[0] === "\n") chunk = chunk.slice(1);
      pendingCR = false;
      buf += chunk;
      const out = [];
      for (;;) {
        const idx = buf.search(/[\r\n]/);
        if (idx < 0) break;
        if (buf[idx] === "\r" && idx + 1 === buf.length) pendingCR = true;
        const width = buf[idx] === "\r" && buf[idx + 1] === "\n" ? 2 : 1;
        const text = buf.slice(0, idx);
        buf = buf.slice(idx + width);
        line(text, out);
      }
      return out;
    },
    flush() {
      const out = [];
      if (buf) {
        line(buf.replace(/\r$/, ""), out);
        buf = "";
      }
      dispatch(out);
      return out;
    },
  };
}

// ------------------------------------------------------------------ footer

function fmtTime(s) {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return String(s);
  return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/** "Index <built_at> · docs lastmod <docs_lastmod_max> · olake@<sha7>" from GET /healthz. */
export function footerText(h) {
  const ix = h && h.index;
  if (!ix) return "";
  const parts = [];
  if (ix.built_at) parts.push("Index " + fmtTime(ix.built_at));
  if (ix.docs_lastmod_max) parts.push("docs lastmod " + ix.docs_lastmod_max);
  if (ix.repos && ix.repos.olake) parts.push("olake@" + String(ix.repos.olake).slice(0, 7));
  return parts.join(" · ");
}
