/* =====================================================================
   MATRIX — the moving parts of the design system.

       <script src="matrix.js" defer></script>

   Auto-starts on load: the background renders into <canvas id="mx-rain">,
   [data-mx-tab] buttons drive body[data-mx-view], and the command bar is
   kept above the iOS keyboard. Everything is also callable by hand on
   the global `MX` if you'd rather wire it yourself.

       MX.toast(true, "saved")            // transient message
       MX.decode(el, "ticket printer")    // one-off scramble-in
       MX.background.stop()               // free the animation

   No dependencies, no build step, ES5 syntax so it runs anywhere.
   Honours prefers-reduced-motion throughout.
   ===================================================================== */
window.MX = (function () {
  "use strict";

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------------------
     Background: digital rain, the film look.

     The glyphs sit on a fixed grid and never move; a stream is only a
     wave of illumination passing down one column, which is what the
     film's code actually does. Glyphs are half-width katakana plus a
     few digits and symbols, drawn mirrored (Simon Whiteley's typeface
     was mirrored kana). The head is near-white with a green glow, the
     cell behind it is full green, and the trail decays on a phosphor
     curve, pow(1 - d/len, 1.4), rather than a straight line. Settled
     glyphs flicker to a new character now and then. Several drops can
     share a column but never collide: a follower spawns only once the
     drop ahead has cleared its own trail plus a gap.

     Redrawn from scratch every frame -- no fade buffer, so nothing
     smears or accumulates -- and a quarter-resolution copy sits under
     the sharp canvas with a CSS blur for bloom. Capped at 25fps: every
     frame forces every backdrop-filter on the page to re-composite, so
     the cap roughly halves what the glass costs a phone.

     Pass both canvases; the bloom one is optional but it is what the
     glass mostly refracts, so a page without it will look flatter.
     ------------------------------------------------------------------ */
  function Background(canvas, bloom, opts) {
    opts = opts || {};
    var ctx = canvas && canvas.getContext && canvas.getContext("2d");
    var bctx = bloom ? bloom.getContext("2d", { alpha: false }) : null;
    if (!ctx) return { stop: function () {} };

    var KATA = "\uff71\uff72\uff73\uff74\uff75\uff76\uff77\uff78\uff79\uff7a\uff7b\uff7c\uff7d\uff7e\uff7f\uff80\uff81\uff82\uff83\uff84\uff85\uff86\uff87\uff88\uff89\uff8a\uff8b\uff8c\uff8d\uff8e\uff8f\uff90\uff91\uff92\uff93\uff94\uff95\uff96\uff97\uff98\uff99\uff9a\uff9b\uff9c\uff9d";
    var GLYPHS = (opts.glyphs || KATA + "0123456789" + "Z:\u30fb\"=*+-<>\u00a6|\u00e7").split("");
    var FONT = opts.font || '"MS Gothic", "Osaka-Mono", "Noto Sans Mono CJK JP", ui-monospace, Menlo, monospace';

    var FONT_PX = opts.cell || 16;                 // cell size, CSS px
    var FPS = opts.fps || 25;
    var MIN_SPEED = 0.25, MAX_SPEED = 1.1;         // rows per frame
    var MIN_TRAIL = 14, MAX_TRAIL = 44;            // rows
    var MUTATE = 0.02;                             // per lit cell per frame
    var GREEN = opts.green || "0,255,65";          // #00ff41 phosphor green
    var HEAD = opts.head || "rgb(205,255,215)";

    var w = 0, h = 0, cols = 0, rows = 0, cells = [], drops = [];

    function rnd(a) { return a[(Math.random() * a.length) | 0]; }

    function newDrop(scatter) {
      var trail = MIN_TRAIL + Math.random() * (MAX_TRAIL - MIN_TRAIL);
      return {
        y: scatter ? Math.random() * rows * 1.5 - rows * 0.5 : -Math.random() * 6,
        speed: MIN_SPEED + Math.random() * (MAX_SPEED - MIN_SPEED),
        trail: trail,
        gap: trail + 6 + Math.random() * 40   // rows the head clears before a follower spawns
      };
    }

    /* Sized from the canvas's own CSS box, not window.innerHeight, and
       the field is kept rather than rebuilt: a height change (address
       bar, keyboard, rotation) just adds or trims rows, and only a width
       change re-rolls the columns. Nothing visibly restarts. */
    function resize() {
      var nw = canvas.clientWidth || window.innerWidth;
      var nh = canvas.clientHeight || window.innerHeight;
      if (nw === w && nh === h) return;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var widthChanged = nw !== w;
      w = nw; h = nh;
      canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (bloom) { bloom.width = Math.max(2, (w / 4) | 0); bloom.height = Math.max(2, (h / 4) | 0); }
      cols = Math.ceil(w / FONT_PX); rows = Math.ceil(h / FONT_PX) + 1;
      if (widthChanged) { cells = []; drops = []; }
      for (var i = 0; i < cols; i++) {
        var col = cells[i] || (cells[i] = []);
        while (col.length < rows) col.push(rnd(GLYPHS));
        col.length = rows;
        if (!drops[i]) drops[i] = [newDrop(true)];
      }
      cells.length = cols; drops.length = cols;
      ctx.font = FONT_PX + "px " + FONT;     // canvas.width= resets context state
      ctx.textBaseline = "top";
    }

    function frame() {
      ctx.clearRect(0, 0, w, h);
      ctx.shadowBlur = 0;
      for (var i = 0; i < cols; i++) {
        var x = i * FONT_PX;
        var list = drops[i];
        for (var k = 0; k < list.length; k++) {
          var d = list[k];
          var headRow = Math.floor(d.y);
          var top = Math.max(0, Math.ceil(d.y - d.trail));
          var bottom = Math.min(rows - 1, headRow);
          for (var r = top; r <= bottom; r++) {
            if (Math.random() < MUTATE) cells[i][r] = rnd(GLYPHS);
            var a = Math.pow(1 - (d.y - r) / d.trail, 1.4);
            if (a <= 0.02) continue;
            ctx.save();
            ctx.translate(x + FONT_PX, r * FONT_PX);
            ctx.scale(-1, 1);                              // mirrored, like the film
            if (r === headRow) {
              ctx.shadowColor = "rgb(" + GREEN + ")";
              ctx.shadowBlur = 14;                         // glow only on the head: it's expensive
              ctx.fillStyle = HEAD;
            } else if (r === headRow - 1) {
              ctx.fillStyle = "rgba(" + GREEN + ",1)";
            } else {
              ctx.fillStyle = "rgba(" + GREEN + "," + (a * 0.85) + ")";
            }
            ctx.fillText(cells[i][r], 0, 0);
            ctx.restore();
          }
          d.y += d.speed;
        }
        if (list[0].y - list[0].trail > rows) list.shift();
        var newest = list[list.length - 1];
        // A column whose only drop was culled before its follower spawned
        // leaves an empty list, which throws on the next frame.
        if (!newest || newest.y > newest.gap) list.push(newDrop(false));
      }
      // bloom: downsample the finished frame; CSS blur/brightness does the rest
      if (bctx) {
        bctx.fillStyle = "#000";
        bctx.fillRect(0, 0, bloom.width, bloom.height);
        bctx.drawImage(canvas, 0, 0, bloom.width, bloom.height);
      }
    }

    var last = 0, acc = 0, running = false, stopped = false;
    function loop(t) {
      if (!running) return;
      requestAnimationFrame(loop);
      acc += t - last; last = t;
      if (acc >= 1000 / FPS) { acc = Math.min(acc - 1000 / FPS, 100); frame(); }
    }
    // start() is idempotent, so a page that loads hidden and is later
    // shown gets exactly one loop, not two.
    function start() {
      if (running || stopped) return;
      running = true; last = performance.now(); acc = 0;
      requestAnimationFrame(loop);
    }

    function onVisibility() { if (document.hidden) running = false; else start(); }
    var resizeTimer;
    function onResize() {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 200);
    }

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("resize", onResize);
    resize();
    if (!document.hidden) start();

    return {
      stop: function () {
        stopped = true;
        running = false;
        document.removeEventListener("visibilitychange", onVisibility);
        window.removeEventListener("resize", onResize);
        ctx.clearRect(0, 0, w, h);
        if (bctx) bctx.clearRect(0, 0, bloom.width, bloom.height);
      }
    };
  }

  /* --- tabs -----------------------------------------------------------
     Buttons carry data-mx-tab="<view>"; panels carry data-mx-panel with
     the views they appear in. Selection lands on body[data-mx-view] and
     the CSS does the rest, so above 900px this has no visible effect --
     every panel is shown there. */
  function tabs(root) {
    root = root || document;
    var buttons = [].slice.call(root.querySelectorAll("[data-mx-tab]"));
    if (!buttons.length) return null;
    var panels = [].slice.call(document.querySelectorAll("[data-mx-panel]"));
    // Only once tabs are actually wired does the CSS start hiding
    // panels -- otherwise a page with no JS would show none of them.
    document.body.classList.add("mx-tabbed");

    function show(view) {
      document.body.setAttribute("data-mx-view", view);
      for (var i = 0; i < buttons.length; i++) {
        var on = buttons[i].getAttribute("data-mx-tab") === view;
        buttons[i].setAttribute("aria-selected", on ? "true" : "false");
        if (on) buttons[i].classList.remove("mx-has-update");
      }
      // A panel may list several views: data-mx-panel="output log".
      for (var j = 0; j < panels.length; j++) {
        var views = (panels[j].getAttribute("data-mx-panel") || "").split(/\s+/);
        panels[j].classList.toggle("mx-shown", views.indexOf(view) !== -1);
      }
    }

    buttons.forEach(function (b) {
      b.addEventListener("click", function () { show(b.getAttribute("data-mx-tab")); });
    });

    var current = document.body.getAttribute("data-mx-view");
    show(current || buttons[0].getAttribute("data-mx-tab"));

    return {
      show: show,
      current: function () { return document.body.getAttribute("data-mx-view"); },
      /* True when the view is on screen: either it's the selected tab,
         or the viewport is wide enough that everything is shown. */
      visible: function (view) {
        return document.body.getAttribute("data-mx-view") === view || window.innerWidth >= 900;
      },
      mark: function (view) {
        buttons.forEach(function (b) {
          if (b.getAttribute("data-mx-tab") === view) b.classList.add("mx-has-update");
        });
      }
    };
  }

  /* --- keyboard-aware command bar --------------------------------------
     position:fixed is measured against the layout viewport, which does
     not shrink when the iOS keyboard opens -- so a bottom bar ends up
     behind the keyboard. visualViewport reports the real overlap; the
     bar rides up by --mx-kb. */
  function keyboardBar() {
    if (!window.visualViewport) return;
    var vv = window.visualViewport;
    function sync() {
      var overlap = Math.max(0, window.innerHeight - (vv.height + vv.offsetTop));
      document.documentElement.style.setProperty("--mx-kb", overlap + "px");
    }
    vv.addEventListener("resize", sync);
    vv.addEventListener("scroll", sync);
    sync();
  }

  /* --- toast ------------------------------------------------------------ */
  function toast(ok, message, host) {
    host = host || document.querySelector(".mx-toasts");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "mx-toast" + (ok ? "" : " mx-err");
    el.textContent = message;
    host.appendChild(el);
    setTimeout(function () {
      el.classList.add("mx-out");
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 260);
    }, 4200);
  }

  /* --- decode ------------------------------------------------------------
     Scrambles into the final string once, left to right. Decoration; it
     no-ops under reduced motion and leaves the text as it found it. */
  function decode(el, text, done) {
    if (!el) return;
    if (reduceMotion) { el.textContent = text; if (done) done(el); return; }
    var pool = "ABCDEFGHIJKLMNOPQRSTUVWXYZ#%&*+-<>/";
    var frame = 0;
    var timer = setInterval(function () {
      frame++;
      var out = "";
      for (var i = 0; i < text.length; i++) {
        if (i < frame / 2) out += text.charAt(i);
        else if (text.charAt(i) === " ") out += " ";
        else out += pool.charAt((Math.random() * pool.length) | 0);
      }
      el.textContent = out;
      if (done) done(el);
      if (frame / 2 >= text.length) clearInterval(timer);
    }, 38);
  }

  /* --- localStorage that cannot throw ------------------------------------
     Private mode and blocked site data make these accessors throw rather
     than return null, which takes the whole page down with them. */
  var store = {
    get: function (k, d) {
      try { var v = localStorage.getItem("mx." + k); return v === null ? d : v; }
      catch (e) { return d; }
    },
    set: function (k, v) {
      try { localStorage.setItem("mx." + k, v); } catch (e) { /* ignore */ }
    }
  };

  var api = {
    Background: Background,
    background: null,   // the running instance, once booted
    tabs: tabs,         // factory; the booted instance lands on MX.view
    view: null,
    keyboardBar: keyboardBar,
    toast: toast,
    decode: decode,
    store: store,
    reduceMotion: reduceMotion
  };

  function boot() {
    var canvas = document.getElementById("mx-rain");
    var bloom = document.getElementById("mx-rain-bloom");
    if (canvas) {
      if (reduceMotion) {
        canvas.style.display = "none";
        if (bloom) bloom.style.display = "none";
      } else {
        api.background = Background(canvas, bloom);
      }
    }
    api.view = tabs();
    keyboardBar();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  return api;
})();
