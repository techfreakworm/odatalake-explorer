// Ask OLake embed app (the iframe behind /embed). Streams POST /ask/stream with fetch() and a stream reader
// (EventSource cannot POST); falls back to POST /ask once. Model text reaches the DOM only as text nodes.
import { createSSEParser, domainOf, footerText, parseMarkdown, safeUrl, toDOM } from "./embed-core.mjs";

const params = new URLSearchParams(location.search);
const TIMEOUT_S = Math.min(600, Math.max(5, parseInt(params.get("timeout"), 10) || 30));
const EMBEDDED = window.parent !== window;
const HISTORY_ENTRIES = 4; // the last 4 turns (user and assistant messages) go to /ask/stream as history
const SVG = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);
const log = $("log");
const input = $("q");
const sendBtn = $("send");
const welcome = $("welcome");
const history = [];
let busy = false;
let seq = 0;

class ClientError extends Error {}
class ServerError extends Error {}

init();

function init() {
  const title = (params.get("title") || "").trim().slice(0, 60);
  if (title) {
    $("title").textContent = title;
    document.title = title;
  }
  const accent = params.get("accent") || "";
  if (/^#[0-9a-f]{3,8}$/i.test(accent)) document.documentElement.style.setProperty("--accent", accent);
  applyTheme(params.get("theme"));

  const close = $("close");
  if (EMBEDDED) close.addEventListener("click", requestClose);
  else close.hidden = true;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && EMBEDDED) {
      e.preventDefault();
      requestClose();
    }
  });
  window.addEventListener("message", (e) => {
    if (e.source !== window.parent || !e.data || typeof e.data !== "object") return;
    if (e.data.type === "askolake:theme") applyTheme(e.data.theme);
    else if (e.data.type === "askolake:open") input.focus();
  });

  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    submit();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  });
  input.addEventListener("input", autosize);
  for (const chip of document.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => {
      input.value = chip.textContent;
      submit();
      input.focus();
    });
  }

  fetch("/healthz").then((r) => r.json()).then((h) => { $("foot").textContent = footerText(h); }).catch(() => {});
  if (EMBEDDED) window.parent.postMessage({ type: "askolake:ready" }, "*");
  input.focus();
}

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function requestClose() {
  window.parent.postMessage({ type: "askolake:close" }, "*");
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}

function submit() {
  const question = input.value.trim();
  if (!question || busy) return;
  input.value = "";
  autosize();
  ask(question);
}

// ------------------------------------------------------------------ DOM helpers

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function icon(paths) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  for (const d of paths) {
    const p = document.createElementNS(SVG, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  return svg;
}

function nearBottom() {
  return log.scrollHeight - log.scrollTop - log.clientHeight < 48;
}

function keepAtBottom(fn) {
  const stick = nearBottom();
  fn();
  if (stick) log.scrollTop = log.scrollHeight;
}

// ------------------------------------------------------------------ one question

async function ask(question) {
  busy = true;
  sendBtn.disabled = true;
  log.setAttribute("aria-busy", "true");
  welcome.hidden = true;

  const id = "m" + ++seq;
  const askEl = h("div", "ask", question);
  const turn = h("article", "turn");
  turn.setAttribute("aria-label", "Answer");
  const body = h("div", "answer");
  const typing = h("span", "typing");
  typing.append(h("i"), h("i"), h("i"), h("span", "sr-only", "Answering"));
  body.append(typing);
  turn.append(body);
  keepAtBottom(() => log.append(askEl, turn));

  const hist = history.slice(-HISTORY_ENTRIES);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_S * 1000);
  try {
    let result;
    try {
      result = await streamAnswer(question, hist, body, ctrl.signal);
    } catch (err) {
      if (ctrl.signal.aborted || err instanceof ClientError) throw err;
      result = await plainAnswer(question, ctrl.signal); // streaming failed: one plain POST /ask
    }
    keepAtBottom(() => renderFinal(turn, body, result, id));
    history.push({ role: "user", content: question.slice(0, 2000) },
                 { role: "assistant", content: result.answer.slice(0, 4000) });
    history.splice(0, Math.max(0, history.length - HISTORY_ENTRIES));
  } catch (err) {
    keepAtBottom(() => renderError(body, err, ctrl.signal.aborted, () => {
      askEl.remove();
      turn.remove();
      ask(question);
    }));
  } finally {
    clearTimeout(timer);
    busy = false;
    sendBtn.disabled = false;
    log.setAttribute("aria-busy", "false");
  }
}

async function streamAnswer(question, hist, body, signal) {
  const res = await fetch("/ask/stream", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question, history: hist }),
    signal,
  });
  if (res.status === 422) {
    const j = await res.json().catch(() => null);
    throw new ClientError((j && j.answer) || "That question could not be sent.");
  }
  if (!res.ok || !res.body) throw new Error("stream HTTP " + res.status);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const sse = createSSEParser();
  let raw = "";
  let requestId = res.headers.get("x-request-id") || "";
  let done = null;
  let frame = 0;
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      const events = end ? [...sse.push(decoder.decode()), ...sse.flush()] : sse.push(decoder.decode(value, { stream: true }));
      for (const ev of events) {
        const d = ev.json || {};
        if (ev.event === "meta") requestId = d.request_id || requestId;
        else if (ev.event === "token") {
          raw += typeof d.text === "string" ? d.text : "";
          if (!frame) {
            frame = requestAnimationFrame(() => {
              frame = 0;
              keepAtBottom(() => body.replaceChildren(toDOM(parseMarkdown(raw), document)));
            });
          }
        } else if (ev.event === "done") done = d;
        else if (ev.event === "error") throw new ServerError(d.message || "The answer failed.");
      }
      if (done || end) break;
    }
  } finally {
    if (frame) cancelAnimationFrame(frame);
    reader.cancel().catch(() => {});
  }
  if (!done) throw new Error("the stream ended before the answer was complete");
  return {
    answer: String(done.answer || ""),
    citations: Array.isArray(done.citations) ? done.citations : [],
    requestId: done.request_id || requestId,
  };
}

async function plainAnswer(question, signal) {
  const res = await fetch("/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  const j = await res.json().catch(() => null);
  if (!j || typeof j.answer !== "string") throw new Error("HTTP " + res.status);
  if (res.status === 422) throw new ClientError(j.answer);
  if (!res.ok) throw new ServerError(j.answer);
  const sources = Array.isArray(j.sources) ? j.sources : [];
  return {
    answer: j.answer,
    citations: sources.map((url, k) => ({ n: k + 1, url, title: domainOf(url) || url, label: "", source_type: "", snippet: "" })),
    requestId: res.headers.get("x-request-id") || "",
  };
}

// ------------------------------------------------------------------ rendering

function renderFinal(turn, body, r, id) {
  const cites = r.citations.length;
  body.replaceChildren(toDOM(parseMarkdown(r.answer, { cites }), document, { element: (e) => decorate(e, id) }));
  if (cites) turn.append(sourceList(r.citations, id));
  if (r.requestId) turn.append(feedback(r.requestId));
}

function decorate(e, id) {
  if (e.tagName === "PRE") return codeBlock(e);
  if (e.tagName === "A" && e.classList.contains("cite")) {
    const n = e.dataset.n;
    e.href = `#${id}-src-${n}`;
    e.setAttribute("aria-label", `Source ${n}`);
    e.addEventListener("click", (ev) => {
      ev.preventDefault();
      const card = document.getElementById(`${id}-src-${n}`);
      if (card) {
        card.scrollIntoView({ block: "nearest" });
        card.focus({ preventScroll: true });
      }
    });
    const lit = (on) => {
      const card = document.getElementById(`${id}-src-${n}`);
      if (card) card.classList.toggle("lit", on);
    };
    e.addEventListener("mouseenter", () => lit(true));
    e.addEventListener("mouseleave", () => lit(false));
    e.addEventListener("focus", () => lit(true));
    e.addEventListener("blur", () => lit(false));
  }
  return null;
}

function codeBlock(pre) {
  const wrap = h("div", "code");
  const btn = h("button", "copy", "Copy");
  btn.type = "button";
  btn.setAttribute("aria-label", "Copy code");
  btn.addEventListener("click", () => copyText(pre.textContent, btn));
  wrap.append(pre, btn);
  return wrap;
}

async function copyText(text, btn) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch {
    const ta = h("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.className = "sr-only";
    document.body.append(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    ta.remove();
  }
  btn.textContent = ok ? "Copied" : "Copy failed";
  setTimeout(() => { btn.textContent = "Copy"; }, 1600);
}

const TYPE_CLASS = { repo: "t-repo", release: "t-release", "release-gh": "t-release", issue: "t-issue",
                     outside: "t-outside", blog: "t-blog" };

function sourceList(citations, id) {
  const section = h("section", "srcs");
  const heading = h("h2", "srcs-h", "Sources");
  heading.id = `${id}-srcs`;
  section.setAttribute("aria-labelledby", heading.id);
  const list = h("ol", "cards");
  for (const c of citations) {
    const url = safeUrl(String(c.url || ""));
    const card = h("li", "card " + (TYPE_CLASS[c.source_type] || "t-docs"));
    card.id = `${id}-src-${c.n}`;
    card.tabIndex = -1;
    const box = url ? h("a", "card-link") : h("div", "card-link");
    if (url) {
      box.href = url;
      box.target = "_blank";
      box.rel = "noopener noreferrer";
    }
    const top = h("span", "card-top");
    top.append(h("span", "card-n", String(c.n)), h("span", "card-title", String(c.title || domainOf(url) || "Source")));
    const meta = h("span", "card-meta");
    const domain = domainOf(url);
    if (domain) meta.append(h("span", "card-domain", domain));
    const label = String(c.label || "");
    if (c.source_type === "outside") meta.append(h("span", "badge", label || "outside OLake docs"));
    else if (label) meta.append(h("span", "card-label", label));
    box.append(top, meta);
    if (c.snippet) box.append(h("span", "card-snip", String(c.snippet)));
    card.append(box);
    list.append(card);
  }
  section.append(heading, list);
  return section;
}

const THUMB_UP = ["M7 11v9H4v-9h3z", "M7 11l4-7c1.3 0 2.2 1 2 2.3L12.5 10H18a2 2 0 0 1 2 2.3l-1.2 6A2 2 0 0 1 16.8 20H7"];
const THUMB_DOWN = ["M7 13V4H4v9h3z", "M7 13l4 7c1.3 0 2.2-1 2-2.3L12.5 14H18a2 2 0 0 0 2-2.3l-1.2-6A2 2 0 0 0 16.8 4H7"];

function feedback(requestId) {
  const row = h("div", "fb");
  const label = h("span", "fb-l", "Was this helpful?");
  row.append(label);
  const buttons = [["up", "Helpful", THUMB_UP], ["down", "Not helpful", THUMB_DOWN]].map(([rating, text, paths]) => {
    const b = h("button", "icon-btn");
    b.type = "button";
    b.setAttribute("aria-label", text);
    b.setAttribute("aria-pressed", "false");
    b.append(icon(paths));
    b.addEventListener("click", () => {
      for (const other of buttons) other.disabled = true;
      b.setAttribute("aria-pressed", "true");
      label.textContent = "Thanks for the feedback.";
      fetch("/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ request_id: requestId, rating }),
      }).catch(() => {});
    });
    return b;
  });
  row.append(...buttons);
  return row;
}

function renderError(body, err, timedOut, retry) {
  let msg = "The answer could not be loaded. Check your connection, then retry.";
  if (timedOut) msg = `No answer arrived within ${TIMEOUT_S} seconds. Retry, or ask a shorter question.`;
  else if (err instanceof ClientError || err instanceof ServerError) msg = err.message;
  const box = h("div", "err");
  box.setAttribute("role", "alert");
  box.append(h("p", "", msg));
  if (!(err instanceof ClientError)) {
    const b = h("button", "btn", "Retry");
    b.type = "button";
    b.addEventListener("click", retry);
    box.append(b);
  }
  body.replaceChildren(box);
}
