/* =====================================================================
   MATRIX 1.1.0 — the moving parts of the design system.

       <script src="matrix.js" defer></script>

   Auto-starts on load:
     - adds the background layers to <body class="mx"> (skip with
       data-mx-bg="off") and starts the rain
     - wires tabs, sheets, menus, list/detail, image wells
     - keeps the command bar above the iOS keyboard, and moves it into
       the top bar on big screens when there is a [data-mx-slot="actions"]
     - arrow-key focus movement on a TV (<html data-mx-device="tv">)

   Everything is also callable by hand on the global `MX`:

       MX.toast(true, "saved")            // transient message
       MX.sheet.open("confirm")           // open <div class="mx-overlay" id="confirm">
       MX.theme.set("amber")              // switch theme (remembered per browser)
       MX.size()                          // "compact" | "medium" | "expanded" | "wide" | "tv"
       MX.decode(el, "ticket printer")    // one-off scramble-in
       MX.background.stop()               // free the animation

   No dependencies, no build step, ES5 syntax so it runs anywhere.
   Honours prefers-reduced-motion throughout.
   ===================================================================== */
window.MX = (function () {
  "use strict";

  var VERSION = "1.1.0";
  var root = document.documentElement;
  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* --- localStorage that cannot throw ------------------------------------
     Private mode and blocked site data make these accessors throw rather
     than return null, which takes the whole page down with them. */
  var store = {
    get: function (k, d) {
      try { var v = localStorage.getItem("mx." + k); return v === null ? d : v; }
      catch (e) { return d; }
    },
    set: function (k, v) {
      try {
        if (v === null || v === undefined) localStorage.removeItem("mx." + k);
        else localStorage.setItem("mx." + k, v);
      } catch (e) { /* ignore */ }
    }
  };

  function closest(el, selector) {
    while (el && el.nodeType === 1) {
      if ((el.matches || el.msMatchesSelector || el.webkitMatchesSelector).call(el, selector)) return el;
      el = el.parentNode;
    }
    return null;
  }

  function fire(el, name) {
    var ev;
    try { ev = new CustomEvent(name, { bubbles: true }); }
    catch (e) { ev = document.createEvent("CustomEvent"); ev.initCustomEvent(name, true, false, null); }
    el.dispatchEvent(ev);
  }

  /* --- screen sizes --------------------------------------------------------
     The same widths as matrix.css. body[data-mx-size] follows the
     window so page scripts can branch on it without their own numbers. */
  function size() {
    if (root.getAttribute("data-mx-device") === "tv") return "tv";
    var w = window.innerWidth;
    if (w < 600) return "compact";
    if (w < 1024) return "medium";
    if (w < 1440) return "expanded";
    return "wide";
  }
  function isWide() { var s = size(); return s === "expanded" || s === "wide" || s === "tv"; }

  /* --- accent colour, read from the tokens -------------------------------- */
  function accentRGB() {
    var v = "";
    try { v = getComputedStyle(root).getPropertyValue("--mx-accent").trim(); } catch (e) { /* ignore */ }
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(v);
    if (m) return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
    m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(v);
    if (m) return [parseInt(m[1] + m[1], 16), parseInt(m[2] + m[2], 16), parseInt(m[3] + m[3], 16)];
    m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/i.exec(v);
    if (m) return [+m[1], +m[2], +m[3]];
    return [0, 255, 90];
  }

  /* ------------------------------------------------------------------
     Background: digital rain, the film look.

     The glyphs sit on a fixed grid and never move; a stream is only a
     wave of illumination passing down one column, which is what the
     film's code actually does. Glyphs are half-width katakana plus a
     few digits and symbols, drawn mirrored. The head is near-white
     with a glow, the cell behind it full accent, and the trail decays
     on a phosphor curve, pow(1 - d/len, 1.4). Settled glyphs flicker to
     a new character now and then. Several drops can share a column but
     never collide: a follower spawns only once the drop ahead has
     cleared its own trail plus a gap.

     Redrawn from scratch every frame -- no fade buffer, so nothing
     smears. The colour follows --mx-accent, so a theme recolours it.
     The second argument (the 1.0 bloom canvas) is accepted and ignored.
     ------------------------------------------------------------------ */
  function Background(canvas, _bloom, opts) {
    opts = opts || {};
    var ctx = canvas && canvas.getContext && canvas.getContext("2d");
    if (!ctx) return { stop: function () {}, recolor: function () {} };

    var KATA = "\uff71\uff72\uff73\uff74\uff75\uff76\uff77\uff78\uff79\uff7a\uff7b\uff7c\uff7d\uff7e\uff7f\uff80\uff81\uff82\uff83\uff84\uff85\uff86\uff87\uff88\uff89\uff8a\uff8b\uff8c\uff8d\uff8e\uff8f\uff90\uff91\uff92\uff93\uff94\uff95\uff96\uff97\uff98\uff99\uff9a\uff9b\uff9c\uff9d";
    var GLYPHS = (opts.glyphs || KATA + "0123456789" + "Z:\u30fb\"=*+-<>\u00a6|\u00e7").split("");
    var FONT = opts.font || '"MS Gothic", "Osaka-Mono", "Noto Sans Mono CJK JP", ui-monospace, Menlo, monospace';

    var FONT_PX = opts.cell || 16;                 // cell size, CSS px
    var FPS = opts.fps || 30;
    var MIN_SPEED = 0.25, MAX_SPEED = 1.1;         // rows per frame
    var MIN_TRAIL = 14, MAX_TRAIL = 44;            // rows
    var MUTATE = 0.02;                             // per lit cell per frame
    var COLOR, HEAD;

    function recolor(rgb) {
      rgb = rgb || (opts.green ? opts.green.split(",") : accentRGB());
      var r = +rgb[0], g = +rgb[1], b = +rgb[2];
      COLOR = r + "," + g + "," + b;
      // the head is the accent pushed most of the way to white
      HEAD = "rgb(" + Math.round(r + (255 - r) * 0.8) + "," + Math.round(g + (255 - g) * 0.8) + "," + Math.round(b + (255 - b) * 0.8) + ")";
    }
    recolor();

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

    /* Sized from the canvas's own CSS box, and the field is kept rather
       than rebuilt: a height change (address bar, keyboard, rotation)
       just adds or trims rows; only a width change re-rolls the columns. */
    function resize() {
      var nw = canvas.clientWidth || window.innerWidth;
      var nh = canvas.clientHeight || window.innerHeight;
      if (nw === w && nh === h) return;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var widthChanged = nw !== w;
      w = nw; h = nh;
      canvas.width = Math.floor(w * dpr); canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
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
              ctx.shadowColor = "rgb(" + COLOR + ")";
              ctx.shadowBlur = 14;                         // glow only on the head: it's expensive
              ctx.fillStyle = HEAD;
            } else if (r === headRow - 1) {
              ctx.fillStyle = "rgba(" + COLOR + ",1)";
            } else {
              ctx.fillStyle = "rgba(" + COLOR + "," + (a * 0.85) + ")";
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
      recolor: recolor,
      stop: function () {
        stopped = true;
        running = false;
        document.removeEventListener("visibilitychange", onVisibility);
        window.removeEventListener("resize", onResize);
        ctx.clearRect(0, 0, w, h);
      }
    };
  }

  /* The rain canvas, vignette and scanlines, added to <body class="mx">
     unless the page already has them or opts out with data-mx-bg="off". */
  function ensureLayers() {
    var body = document.body;
    if (!body || !body.classList.contains("mx")) return;
    if (body.getAttribute("data-mx-bg") === "off") return;
    if (document.getElementById("mx-rain")) return;
    var frag = document.createDocumentFragment();
    var canvas = document.createElement("canvas");
    canvas.id = "mx-rain";
    canvas.setAttribute("aria-hidden", "true");
    frag.appendChild(canvas);
    ["mx-vignette", "mx-scanlines"].forEach(function (cls) {
      var d = document.createElement("div");
      d.className = cls;
      d.setAttribute("aria-hidden", "true");
      frag.appendChild(d);
    });
    body.insertBefore(frag, body.firstChild);
  }

  /* --- theme -------------------------------------------------------------
     Themes are blocks in matrix.css keyed on <html data-mx-theme>.
     A theme chosen with set() is remembered per browser -- and since
     every app behind App Hub shares one origin, it follows you across
     apps. An app that hard-codes data-mx-theme in its HTML wins. */
  var theme = {
    list: ["matrix", "amber", "ice"],
    get: function () { return root.getAttribute("data-mx-theme") || "matrix"; },
    set: function (name, remember) {
      if (!name || name === "matrix") root.removeAttribute("data-mx-theme");
      else root.setAttribute("data-mx-theme", name);
      if (remember !== false) store.set("theme", name === "matrix" ? null : name);
      if (api.background && api.background.recolor) api.background.recolor();
      fire(root, "mx:theme");
    }
  };

  /* --- tabs -----------------------------------------------------------
     Buttons carry data-mx-tab="<view>"; panels carry data-mx-panel with
     the views they appear in. Selection lands on body[data-mx-view] and
     the CSS does the rest, so from expanded up this has no visible
     effect -- every panel is shown there. */
  function tabs(scope) {
    scope = scope || document;
    var buttons = [].slice.call(scope.querySelectorAll("[data-mx-tab]"));
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
         or the screen is big enough that everything is shown. */
      visible: function (view) {
        return document.body.getAttribute("data-mx-view") === view || isWide();
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
      root.style.setProperty("--mx-kb", overlap + "px");
    }
    vv.addEventListener("resize", sync);
    vv.addEventListener("scroll", sync);
    sync();
  }

  /* --- command bar placement ----------------------------------------------
     A bottom bar is in thumb reach on a phone and a long way from the
     mouse on a desktop. From expanded up, if the top bar offers a
     [data-mx-slot="actions"], the bar's contents move there. */
  function cmdbarPlacement() {
    var bar = document.querySelector(".mx-cmdbar");
    var inner = bar && bar.querySelector(".mx-cmdbar-inner");
    var slot = document.querySelector('[data-mx-slot="actions"]');
    if (!inner || !slot) return;
    function place() {
      var inline = isWide();
      if (inline && inner.parentNode !== slot) slot.appendChild(inner);
      else if (!inline && inner.parentNode !== bar) bar.appendChild(inner);
      document.body.classList.toggle("mx-cmd-inline", inline);
    }
    window.addEventListener("resize", place);
    place();
  }

  /* --- sheets ----------------------------------------------------------------
     <div class="mx-overlay" id="x" aria-hidden="true"><div class="mx-sheet" role="dialog">
     [data-mx-open="x"] opens it, [data-mx-close] inside closes it, as do
     a tap on the scrim and Escape. Fires mx:open / mx:close on the overlay. */
  var lastFocus = [];
  function overlayOf(target) {
    var el = typeof target === "string" ? document.getElementById(target) : target;
    return el ? (closest(el, ".mx-overlay") || el) : null;
  }
  var sheet = {
    open: function (target) {
      var ov = overlayOf(target);
      if (!ov || ov.classList.contains("mx-open")) return;
      lastFocus.push(document.activeElement);
      ov.classList.add("mx-open");
      ov.setAttribute("aria-hidden", "false");
      setTimeout(function () {
        var f = ov.querySelector("[autofocus], input, select, textarea, button, [href], [tabindex]:not([tabindex='-1'])");
        if (f) f.focus();
      }, 60);
      fire(ov, "mx:open");
    },
    close: function (target) {
      var ov = overlayOf(target);
      if (!ov || !ov.classList.contains("mx-open")) return;
      ov.classList.remove("mx-open");
      ov.setAttribute("aria-hidden", "true");
      var back = lastFocus.pop();
      if (back && back.focus) back.focus();
      fire(ov, "mx:close");
    },
    top: function () {
      var open = document.querySelectorAll(".mx-overlay.mx-open");
      return open.length ? open[open.length - 1] : null;
    }
  };

  /* --- menus -------------------------------------------------------------------- */
  var menu = {
    closeAll: function (except) {
      var pops = document.querySelectorAll(".mx-menu-pop.mx-open, .mx-menu-popover.mx-open");
      for (var i = 0; i < pops.length; i++) {
        if (pops[i] === except) continue;
        pops[i].classList.remove("mx-open");
        var t = pops[i].parentNode.querySelector("[data-mx-menu-toggle]");
        if (t) t.setAttribute("aria-expanded", "false");
      }
    },
    toggle: function (menuEl) {
      var pop = menuEl.querySelector(".mx-menu-pop, .mx-menu-popover");
      if (!pop) return;
      var open = !pop.classList.contains("mx-open");
      menu.closeAll(pop);
      pop.classList.toggle("mx-open", open);
      var t = menuEl.querySelector("[data-mx-menu-toggle]");
      if (t) t.setAttribute("aria-expanded", open ? "true" : "false");
    }
  };

  /* --- list + detail --------------------------------------------------------------- */
  var detail = {
    open: function (layout) {
      layout = layout || document.querySelector(".mx-layout-list-detail");
      if (!layout) return;
      layout.setAttribute("data-mx-detail", "open");
      // On small screens the detail replaces the list; bring its top into view.
      if (!isWide() && layout.getBoundingClientRect().top < 0) layout.scrollIntoView();
    },
    close: function (layout) {
      layout = layout || document.querySelector(".mx-layout-list-detail");
      if (layout) layout.removeAttribute("data-mx-detail");
    }
  };

  /* One delegated click handler for sheets, menus and list/detail. */
  function onClick(e) {
    var t = e.target;
    var el;
    if ((el = closest(t, "[data-mx-open]"))) { e.preventDefault(); sheet.open(el.getAttribute("data-mx-open")); return; }
    if ((el = closest(t, "[data-mx-close]"))) { e.preventDefault(); sheet.close(el); return; }
    if (t.classList && t.classList.contains("mx-overlay") && t.classList.contains("mx-open")) { sheet.close(t); return; }
    if ((el = closest(t, "[data-mx-menu-toggle]"))) {
      e.preventDefault();
      var m = closest(el, ".mx-menu");
      if (m) menu.toggle(m);
      return;
    }
    if (closest(t, ".mx-menu-item")) { menu.closeAll(); }
    else if (!closest(t, ".mx-menu")) { menu.closeAll(); }
    if ((el = closest(t, "[data-mx-detail-open]"))) detail.open(closest(el, ".mx-layout-list-detail"));
    if ((el = closest(t, "[data-mx-detail-close]"))) { e.preventDefault(); detail.close(closest(el, ".mx-layout-list-detail")); }
  }

  function onKey(e) {
    if (e.key === "Escape" || e.key === "Esc") {
      var ov = sheet.top();
      if (ov) { sheet.close(ov); return; }
      menu.closeAll();
      return;
    }
    if (size() === "tv") spatial(e);
  }

  /* --- TV: arrow keys move focus to the nearest control that way ------------ */
  var FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
  function spatial(e) {
    var dir = { ArrowLeft: "l", ArrowRight: "r", ArrowUp: "u", ArrowDown: "d", Left: "l", Right: "r", Up: "u", Down: "d" }[e.key];
    if (!dir) return;
    var cur = document.activeElement;
    if (cur && /^(INPUT|TEXTAREA)$/.test(cur.tagName) && (dir === "l" || dir === "r")) return;
    var scope = sheet.top() || document;
    var all = [].slice.call(scope.querySelectorAll(FOCUSABLE)).filter(function (el) {
      var r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
    });
    if (!all.length) return;
    if (!cur || cur === document.body || all.indexOf(cur) === -1) { all[0].focus(); e.preventDefault(); return; }
    var a = cur.getBoundingClientRect();
    var ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    var best = null, bestScore = Infinity;
    all.forEach(function (el) {
      if (el === cur) return;
      var b = el.getBoundingClientRect();
      var bx = b.left + b.width / 2, by = b.top + b.height / 2;
      var dx = bx - ax, dy = by - ay, main, cross;
      if (dir === "r") { main = dx; cross = dy; }
      else if (dir === "l") { main = -dx; cross = dy; }
      else if (dir === "d") { main = dy; cross = dx; }
      else { main = -dy; cross = dx; }
      if (main <= 1) return;
      var score = main + Math.abs(cross) * 2;
      if (score < bestScore) { bestScore = score; best = el; }
    });
    if (best) {
      e.preventDefault();
      best.focus();
      if (best.scrollIntoView) best.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  /* --- image wells: stop the shimmer once the picture is in ------------------ */
  function markMedia(img, failed) {
    var well = img.parentNode;
    if (!well || !well.classList || !well.classList.contains("mx-media")) return;
    well.classList.add("mx-loaded");
    if (failed) well.classList.add("mx-failed");
  }
  function onLoadCapture(e) {
    if (e.target && e.target.tagName === "IMG") markMedia(e.target, e.type === "error");
  }
  function scanMedia() {
    var imgs = document.querySelectorAll(".mx-media > img");
    for (var i = 0; i < imgs.length; i++) if (imgs[i].complete) markMedia(imgs[i], !imgs[i].naturalWidth);
  }

  /* --- toast ------------------------------------------------------------ */
  function toast(ok, message, host) {
    host = host || document.querySelector(".mx-toasts");
    if (!host) {
      host = document.createElement("div");
      host.className = "mx-toasts";
      host.setAttribute("role", "status");
      host.setAttribute("aria-live", "polite");
      document.body.appendChild(host);
    }
    var el = document.createElement("div");
    el.className = "mx-toast " + (ok ? "mx-ok" : "mx-err");
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

  var api = {
    version: VERSION,
    Background: Background,
    background: null,   // the running instance, once booted
    tabs: tabs,         // factory; the booted instance lands on MX.view
    view: null,
    keyboardBar: keyboardBar,
    size: size,
    theme: theme,
    sheet: sheet,
    menu: menu,
    detail: detail,
    toast: toast,
    decode: decode,
    store: store,
    reduceMotion: reduceMotion
  };

  // A remembered theme applies before anything paints the rain.
  if (!root.hasAttribute("data-mx-theme")) {
    var saved = store.get("theme", null);
    if (saved) root.setAttribute("data-mx-theme", saved);
  }
  // TVs announce themselves; a page can also set data-mx-device itself.
  if (!root.hasAttribute("data-mx-device") && /Tizen|SMART-TV|SmartTV|Web0S|webOS\.TV|HbbTV/i.test(navigator.userAgent)) {
    root.setAttribute("data-mx-device", "tv");
  }

  function boot() {
    ensureLayers();
    var canvas = document.getElementById("mx-rain");
    if (canvas) {
      if (reduceMotion) canvas.style.display = "none";
      else api.background = Background(canvas);
    }
    function syncSize() { document.body.setAttribute("data-mx-size", size()); }
    syncSize();
    window.addEventListener("resize", syncSize);
    api.view = tabs();
    keyboardBar();
    cmdbarPlacement();
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    document.addEventListener("load", onLoadCapture, true);
    document.addEventListener("error", onLoadCapture, true);
    scanMedia();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  return api;
})();
