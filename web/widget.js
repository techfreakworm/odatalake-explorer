/* Ask OLake loader. One line on any docs page:
     <script src="https://HOST/widget.js" data-api="https://HOST" async></script>
   data-api (default: this script's origin), data-title, data-position="left|right", data-accent="#hex",
   data-open="true", data-timeout="<seconds>" (default 35). Adds a launcher and an iframe panel (HOST/embed);
   sets no cookies and no storage, and its CSS only touches .askolake-* elements. */
(function () {
  "use strict";
  var s = document.currentScript; // only available while this script first runs
  if (!s || window.__askolake) return;
  window.__askolake = 1;
  var d = s.dataset, api, origin;
  try {
    api = (d.api || new URL(s.src, location.href).origin).replace(/\/+$/, "");
    origin = new URL(api).origin;
  } catch (e) {
    return;
  }
  var accent = /^#[0-9a-f]{3,8}$/i.test(d.accent || "") ? d.accent : "#1b6f80";
  var side = d.position === "left" ? "left" : "right";
  // 35 s = the server's ASK_TIMEOUT_S (30) + 5, so its degraded "most relevant pages" answer beats the browser's
  // own timeout; web/embed-core.mjs DEFAULT_TIMEOUT_S holds the same value
  var q = new URLSearchParams({ theme: "auto", timeout: String(Math.min(600, Math.max(5, parseInt(d.timeout, 10) || 35))) });
  if (d.title) q.set("title", d.title.slice(0, 60));
  if (d.accent && accent === d.accent) q.set("accent", accent);
  var btn, frame, isOpen = false, loaded = false, queue = [];

  function theme() {
    var t = document.documentElement.getAttribute("data-theme");
    return t === "dark" || t === "light" ? t : "auto";
  }

  // Until the frame has loaded it still holds about:blank on the host's origin, and posting to the api origin would
  // fail; queue the latest message of each type and send them on load.
  function post(msg) {
    if (!frame) return;
    if (!loaded) {
      queue = queue.filter(function (m) { return m.type !== msg.type; });
      queue.push(msg);
    } else if (frame.contentWindow) {
      frame.contentWindow.postMessage(msg, origin);
    }
  }

  function toggle(open) {
    if (open && !frame) {
      frame = document.createElement("iframe");
      frame.id = "askolake-panel";
      frame.className = "askolake-frame";
      frame.title = d.title || "Ask OLake";
      frame.src = api + "/embed?" + q;
      frame.setAttribute("allow", "clipboard-write");
      frame.addEventListener("load", function () {
        var pending = queue;
        loaded = true;
        queue = [];
        post({ type: "askolake:theme", theme: theme() });
        pending.forEach(function (m) { if (m.type !== "askolake:theme") post(m); });
      });
      document.body.appendChild(frame);
    }
    isOpen = open;
    if (!open) queue = queue.filter(function (m) { return m.type !== "askolake:open"; });
    btn.setAttribute("aria-expanded", String(open));
    if (!frame) return;
    frame.classList.toggle("askolake-hidden", !open);
    if (open) {
      frame.focus();
      post({ type: "askolake:open" });
    } else {
      btn.focus();
    }
  }

  function mount() {
    // on a dark host page the light shadows vanish: the panel gets a light edge instead, and both a black shadow
    var darkBtn = "box-shadow:0 2px 10px rgba(0,0,0,.5)",
      darkFrame = "border-color:rgba(255,255,255,.2);box-shadow:0 12px 40px rgba(0,0,0,.55)";
    var css = document.createElement("style");
    css.textContent =
      // all:initial first, so host-page rules for button, svg or iframe do not leak into the widget
      ".askolake-btn{all:initial;box-sizing:border-box;position:fixed;bottom:20px;" + side + ":20px;" +
      "z-index:2147483000;display:inline-flex;align-items:center;gap:8px;height:44px;padding:0 18px 0 14px;" +
      "border-radius:22px;background:" + accent + ";color:#fff;" +
      "font:600 15px/1 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;cursor:pointer;" +
      "box-shadow:0 2px 10px rgba(10,30,40,.3)}" +
      ".askolake-btn:focus-visible{outline:3px solid " + accent + ";outline-offset:3px}" +
      ".askolake-btn svg{all:initial;display:block;width:18px;height:18px;fill:none;stroke:#fff;stroke-width:2;" +
      "stroke-linejoin:round}" +
      // border-box keeps the hairline inside the 400 x 600 box
      ".askolake-frame{all:initial;box-sizing:border-box;border:1px solid rgba(10,30,40,.12);position:fixed;" +
      "bottom:76px;" + side + ":20px;z-index:2147483001;width:400px;" +
      "height:600px;max-width:calc(100vw - 40px);max-height:calc(100vh - 96px);border-radius:14px;" +
      "background:transparent;box-shadow:0 12px 40px rgba(10,30,40,.3);color-scheme:normal}" +
      ".askolake-hidden{display:none!important}" +
      // dark is decided as web/embed.css decides it: html[data-theme=dark], or a dark prefers-color-scheme unless
      // data-theme=light. :where() keeps these rules at (0,1,0): they beat the base rules by coming after them, and
      // the phone rule beats them the same way
      ":where(html[data-theme=dark]) .askolake-btn{" + darkBtn + "}" +
      ":where(html[data-theme=dark]) .askolake-frame{" + darkFrame + "}" +
      "@media (prefers-color-scheme:dark){:where(html:not([data-theme=light])) .askolake-btn{" + darkBtn + "}" +
      ":where(html:not([data-theme=light])) .askolake-frame{" + darkFrame + "}}" +
      "@media (max-width:640px){.askolake-frame{top:0;left:0;right:0;bottom:0;width:100%;height:100%;" +
      "max-width:none;max-height:none;border-radius:0;border:0;box-shadow:none}}";
    document.head.appendChild(css);

    btn = document.createElement("button");
    btn.type = "button";
    btn.className = "askolake-btn";
    btn.setAttribute("aria-label", "Ask OLake");
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "askolake-panel");
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg"), path = document.createElementNS(svg.namespaceURI, "path");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    path.setAttribute("d", "M4 5h16v11H9l-5 4z");
    svg.appendChild(path);
    btn.appendChild(svg);
    btn.appendChild(document.createTextNode("Ask OLake"));
    btn.addEventListener("click", function () { toggle(!isOpen); });
    document.body.appendChild(btn);

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && isOpen) toggle(false);
    });
    window.addEventListener("message", function (e) {
      if (!frame || e.origin !== origin || e.source !== frame.contentWindow || !e.data) return;
      if (e.data.type === "askolake:close") toggle(false);
      else if (e.data.type === "askolake:ready") post({ type: "askolake:theme", theme: theme() });
    });
    new MutationObserver(function () { post({ type: "askolake:theme", theme: theme() }); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    if (d.open === "true" || d.open === "1") toggle(true);
  }

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);
})();
