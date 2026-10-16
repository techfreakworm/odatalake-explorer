/* Ask OLake embeddable widget (POC).
 * Usage on any page:
 *   <script src="https://API_HOST/widget.js" data-api="https://API_HOST" defer></script>
 * Renders a launcher button + chat panel inside a shadow root (host page CSS cannot leak in or out)
 * and calls POST {data-api}/ask with {"question": "..."}.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  var API = (script && script.dataset.api) || (script ? new URL(script.src).origin : "");
  var TITLE = (script && script.dataset.title) || "Ask OLake";

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u) ? u : "#"; }

  // Minimal markdown: escape first, then add a few of our own tags.
  function render(md, sources) {
    var blocks = [];
    var html = esc(md).replace(/```[a-zA-Z0-9_-]*\n([\s\S]*?)```/g, function (_, code) {
      blocks.push("<pre><code>" + code + "</code></pre>");
      return "\u0000" + (blocks.length - 1) + "\u0000";
    });
    html = html
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\[(\d+)\]/g, function (m, n) {
        var u = sources[Number(n) - 1];
        return u ? '<sup><a href="' + esc(safeUrl(u)) + '" target="_blank" rel="noopener">' + n + "</a></sup>" : "";
      })
      .replace(/^\s*[-*] /gm, "• ")
      .replace(/\n/g, "<br>");
    return html.replace(/\u0000(\d+)\u0000/g, function (_, i) { return blocks[Number(i)]; });
  }

  var host = document.createElement("div");
  host.setAttribute("data-ask-olake", "");
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML =
    "<style>" +
    ":host{all:initial}*{box-sizing:border-box;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}" +
    ".launch{position:fixed;right:20px;bottom:20px;z-index:2147483000;border:0;border-radius:999px;padding:12px 18px;" +
    "background:#1f6feb;color:#fff;font-size:14px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.2)}" +
    ".panel{position:fixed;right:20px;bottom:76px;z-index:2147483000;width:min(420px,calc(100vw - 32px));" +
    "height:min(560px,calc(100vh - 110px));display:flex;flex-direction:column;background:#fff;color:#1f2328;" +
    "border:1px solid #d0d7de;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.18);overflow:hidden}" +
    ".panel[hidden]{display:none}" +
    "header{padding:10px 14px;font-weight:600;border-bottom:1px solid #d0d7de;display:flex;justify-content:space-between}" +
    "header button{border:0;background:none;font-size:18px;cursor:pointer;color:inherit}" +
    ".log{flex:1;overflow:auto;padding:12px 14px;font-size:14px;line-height:1.45}" +
    ".q{font-weight:600;margin:10px 0 4px}.a{margin:0 0 8px}.err{color:#cf222e}" +
    ".src{font-size:12px;margin:4px 0 12px;padding-left:18px}.src a{color:#0969da;word-break:break-all}" +
    "pre{background:#f6f8fa;padding:8px;border-radius:6px;overflow:auto;font-size:12px}code{font-size:12px;background:#f6f8fa;padding:0 3px;border-radius:4px}" +
    "form{display:flex;gap:6px;padding:10px;border-top:1px solid #d0d7de}" +
    "input{flex:1;padding:8px 10px;border:1px solid #d0d7de;border-radius:8px;font-size:14px}" +
    "form button{border:0;border-radius:8px;padding:8px 12px;background:#1f6feb;color:#fff;cursor:pointer}" +
    "form button:disabled{opacity:.6;cursor:wait}" +
    "@media (prefers-color-scheme: dark){.panel{background:#0d1117;color:#e6edf3;border-color:#30363d}" +
    "header,form{border-color:#30363d}input{background:#0d1117;color:#e6edf3;border-color:#30363d}" +
    "pre,code{background:#161b22}.src a{color:#58a6ff}}" +
    "</style>" +
    '<button class="launch" aria-expanded="false">' + esc(TITLE) + "</button>" +
    '<div class="panel" role="dialog" aria-label="' + esc(TITLE) + '" hidden>' +
    "<header><span>" + esc(TITLE) + '</span><button class="close" aria-label="Close">×</button></header>' +
    '<div class="log" aria-live="polite"><p class="a">Ask anything about OLake. Answers cite the docs.</p></div>' +
    '<form><input name="q" autocomplete="off" maxlength="2000" placeholder="e.g. How do I enable CDC for Postgres?" aria-label="Question">' +
    "<button>Ask</button></form></div>";

  var panel = root.querySelector(".panel");
  var launch = root.querySelector(".launch");
  var log = root.querySelector(".log");
  var form = root.querySelector("form");
  var input = form.querySelector("input");
  var btn = form.querySelector("button");

  function toggle(open) {
    panel.hidden = !open;
    launch.setAttribute("aria-expanded", String(open));
    if (open) input.focus();
  }
  launch.addEventListener("click", function () { toggle(panel.hidden); });
  root.querySelector(".close").addEventListener("click", function () { toggle(false); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) return;
    input.value = "";
    btn.disabled = true;
    var qEl = document.createElement("p"); qEl.className = "q"; qEl.textContent = q; log.appendChild(qEl);
    var aEl = document.createElement("div"); aEl.className = "a"; aEl.textContent = "Thinking…"; log.appendChild(aEl);
    log.scrollTop = log.scrollHeight;
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 60000);
    fetch(API + "/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
      signal: ctrl.signal,
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var sources = Array.isArray(data.sources) ? data.sources : [];
        aEl.innerHTML = render(data.answer || "", sources);
        if (sources.length) {
          var ol = document.createElement("ol"); ol.className = "src";
          sources.forEach(function (u) {
            var li = document.createElement("li"); var a = document.createElement("a");
            a.href = safeUrl(u); a.target = "_blank"; a.rel = "noopener"; a.textContent = u.replace(/^https?:\/\//, "");
            li.appendChild(a); ol.appendChild(li);
          });
          log.appendChild(ol);
        }
      })
      .catch(function (err) {
        aEl.className = "a err";
        aEl.textContent = "Could not reach Ask OLake (" + (err && err.name === "AbortError" ? "timeout" : "network/CORS error") + ").";
      })
      .finally(function () {
        clearTimeout(timer); btn.disabled = false; log.scrollTop = log.scrollHeight; input.focus();
      });
  });
})();
