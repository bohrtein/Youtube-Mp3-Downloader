/* =====================================================================
   Music Manager — page-level motion on top of matrix.js.

       <script src="matrix.js" defer></script>
       <script src="app.js" defer></script>

   Any element carrying data-decode materialises out of random glyphs
   once on load, the way the ticket printer's brand line does: the
   panel titles and the tagline, top to bottom, 70ms apart, so the page
   reads as coming online rather than every header flickering at once.
   Titles inside a closed overlay or a [hidden] panel are skipped and
   decoded when that surface is shown instead (APP.decodeAll(el)).

   Nothing here runs per frame; MX.decode is a short setInterval that
   ends when the text lands, and it no-ops under reduced motion.
   ===================================================================== */
window.APP = (function () {
  "use strict";

  var STEP_MS = 70;

  function decodeAll(root) {
    root = root || document;
    var els = [].slice.call(root.querySelectorAll("[data-decode]"));
    if (root === document) {
      els = els.filter(function (el) { return !el.closest(".mx-overlay, [hidden]"); });
    }
    els.forEach(function (el, i) {
      // A caret child would be wiped by decode()'s textContent writes;
      // the callback puts it back after every frame.
      var caret = el.querySelector(".mx-caret");
      var text = el.getAttribute("data-decode") || el.textContent.trim();
      var run = function () {
        MX.decode(el, text, caret ? function (e) { e.appendChild(caret); } : null);
      };
      if (MX.reduceMotion || i === 0) run();
      else setTimeout(run, i * STEP_MS);
    });
  }

  document.addEventListener("DOMContentLoaded", function () { decodeAll(document); });

  return { decodeAll: decodeAll };
})();
