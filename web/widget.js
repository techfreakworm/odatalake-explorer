/* Ask OLake loader (placeholder; the full widget is built in Phase 2).
   <script src="https://HOST/widget.js" data-api="https://HOST" async></script> */
(function () {
  var s = document.currentScript;
  var api = (s && s.getAttribute("data-api")) || (s ? new URL(s.src).origin : location.origin);
  function mount() {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = "Ask OLake";
    b.setAttribute("aria-label", "Ask OLake");
    b.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483000;padding:10px 16px;border-radius:20px;border:0;background:#1f6feb;color:#fff;font:14px sans-serif;cursor:pointer";
    var f = null;
    b.addEventListener("click", function () {
      if (f) { f.remove(); f = null; return; }
      f = document.createElement("iframe");
      f.src = api.replace(/\/$/, "") + "/embed?theme=auto";
      f.title = "Ask OLake";
      f.style.cssText = "position:fixed;right:20px;bottom:70px;width:400px;height:600px;max-width:calc(100vw - 40px);max-height:calc(100vh - 90px);border:1px solid #ccc;border-radius:12px;z-index:2147483000;background:#fff";
      document.body.appendChild(f);
    });
    document.body.appendChild(b);
  }
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
