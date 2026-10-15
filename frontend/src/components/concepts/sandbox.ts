// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
/**
 * The document for the iframe that runs model-written animation code.
 *
 * The iframe is created with sandbox="allow-scripts" and without
 * allow-same-origin, so the code runs in an opaque origin: it cannot read the
 * app's DOM, storage or cookies, and requests it makes would not carry the
 * session cookie. The CSP below additionally blocks all network access, images
 * and fonts. The code arrives by postMessage, never inside this HTML, so it
 * cannot break out of the script tag.
 */
export const SANDBOX_CSP =
  "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; style-src 'unsafe-inline'";

export const SANDBOX_ATTR = "allow-scripts";

export function buildSandboxDoc(): string {
  return `<!doctype html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${SANDBOX_CSP}">
<style>html,body{margin:0;height:100%;background:#fff;overflow:hidden}canvas{display:block;width:100%;height:100%}</style>
</head><body><canvas id="c"></canvas>
<script>
(function () {
  var canvas = document.getElementById("c");
  var ctx = canvas.getContext("2d");
  var raf = 0, failed = false;
  function report(where, e) {
    if (failed) return;
    failed = true;
    cancelAnimationFrame(raf);
    parent.postMessage({ type: "concept-anim-error", message: "Animation crashed " + where + ": " + (e && e.message ? e.message : String(e)) }, "*");
  }
  function size() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(innerWidth * dpr);
    canvas.height = Math.floor(innerHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener("resize", size);
  window.addEventListener("message", function (ev) {
    if (!ev.data || ev.data.type !== "concept-anim-run") return;
    cancelAnimationFrame(raf);
    failed = false;
    size();
    var draw = null;
    try {
      var ret = new Function("api", "var ctx = api.ctx, width = api.width, height = api.height;\\n" + ev.data.code)(
        { ctx: ctx, width: innerWidth, height: innerHeight });
      if (!ret || typeof ret.draw !== "function") throw new Error("setup_code did not return { draw }");
      draw = ret.draw;
    } catch (e) { report("at setup", e); return; }
    var t0 = performance.now(), last = t0;
    function tick(now) {
      try { draw(ctx, innerWidth, innerHeight, (now - t0) / 1000, (now - last) / 1000); }
      catch (e) { report("mid-frame", e); return; }
      last = now;
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
  });
  window.addEventListener("error", function (e) { report("uncaught", e.error || e.message); });
  parent.postMessage({ type: "concept-anim-ready" }, "*");
})();
</script></body></html>`;
}
