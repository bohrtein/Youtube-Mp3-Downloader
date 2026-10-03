/* =====================================================================
   MATRIX 2.1.1 — the moving parts of the design system.

       <script src="matrix.js" defer></script>

   Layout is CSS: container queries decide every 2.0 layout, and nothing
   here measures a pane to lay it out. This file only does what CSS
   can't -- state, focus, keys, drags, and the background.

   Auto-starts on load:
     - adds the background layers to <body class="mx"> (skip with
       data-mx-bg="off") and starts the rain
     - wires tabs (per app), sheets, menus, list/detail and
       master-detail, image wells
     - 2.0: app nav selector, toolbar overflow menus, split handles,
       roving focus in tab strips, command palettes, switcher rows
     - keeps the command bar above the iOS keyboard, and moves it into
       the top bar on big screens when there is a [data-mx-slot="actions"]
     - arrow-key focus movement on a TV (<html data-mx-device="tv">)

   Everything is also callable by hand on the global `MX`:

       MX.toast(true, "saved")            // transient message
       MX.toast(true, "Deleted", {action: {label: "Undo", run: fn}})   // 2.1: one action
       MX.sheet.open("confirm")           // open <div class="mx-overlay" id="confirm">
       MX.theme.set("amber")              // switch theme (remembered per browser)
       MX.density.set("compact")          // comfortable | compact | dense (remembered)
       MX.range(el)                       // "micro" | "narrow" | "medium" | "large" | "wide"
                                          //   -- the width of the .mx-app around el
       MX.size()                          // the WINDOW: "compact" | "medium" | "expanded" | "wide" | "tv"
       MX.init(el)                        // wire markup added after load
       MX.decode(el, "ticket printer")    // one-off scramble-in
       MX.background.stop()               // free the animation

   No dependencies, no build step, ES5 syntax so it runs anywhere.
   Honours prefers-reduced-motion throughout.
   ===================================================================== */
// A page may load two copies: the live one from App Hub, then the
// project's synced copy as a fallback. The second one does nothing.
window.MX = window.MX || (function () {
  "use strict";

  var VERSION = "2.1.1";
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

  /* Returns false when a listener called preventDefault() on a
     cancelable event. */
  function fire(el, name, detail, cancelable) {
    var ev;
    try { ev = new CustomEvent(name, { bubbles: true, cancelable: !!cancelable, detail: detail === undefined ? null : detail }); }
    catch (e) { ev = document.createEvent("CustomEvent"); ev.initCustomEvent(name, true, !!cancelable, detail === undefined ? null : detail); }
    return el.dispatchEvent(ev);
  }

  function each(scope, selector, fn) {
    if (scope.nodeType === 1 && (scope.matches || scope.webkitMatchesSelector).call(scope, selector)) fn(scope);
    var list = scope.querySelectorAll(selector);
    for (var i = 0; i < list.length; i++) fn(list[i]);
  }
  function shown(el) { return !!(el && el.getClientRects().length); }
  var uid = 0;
  function idOf(el) { if (!el.id) el.id = "mx-" + (++uid); return el.id; }
  function svg(d) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + "</svg>";
  }
  /* Focus something without the browser scrolling the whole page to it. */
  function focusQuietly(el) {
    if (!el) return;
    if (!el.hasAttribute("tabindex") && !/^(A|BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) el.setAttribute("tabindex", "-1");
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
  }

  /* One ResizeObserver for everything that reacts to its own size. */
  var ro = window.ResizeObserver ? new ResizeObserver(function (entries) {
    for (var i = 0; i < entries.length; i++) if (entries[i].target.__mxResize) entries[i].target.__mxResize();
  }) : null;
  function watch(el, fn) {
    el.__mxResize = fn;
    if (ro) ro.observe(el); else window.addEventListener("resize", fn);
    fn();
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

  /* --- container ranges (2.0) ------------------------------------------------
     The same numbers as matrix.css's @container mx-app queries. A pane's
     range has nothing to do with the window: a 400px pane on a 3440px
     monitor is "narrow". Every .mx-app also carries data-mx-range for
     scripts (CSS never needs it -- it has the container queries). */
  var RANGES = { micro: 0, narrow: 360, medium: 520, large: 800, wide: 1200 };
  function rangeOf(w) {
    return w >= 1200 ? "wide" : w >= 800 ? "large" : w >= 520 ? "medium" : w >= 360 ? "narrow" : "micro";
  }
  function range(el) {
    var app = el ? closest(el, ".mx-app") : document.querySelector(".mx-app");
    return rangeOf(app ? app.clientWidth : window.innerWidth);
  }

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
    list: ["matrix", "amber", "ice", "magenta", "violet", "white"],
    get: function () { return root.getAttribute("data-mx-theme") || "matrix"; },
    set: function (name, remember) {
      if (!name || name === "matrix") root.removeAttribute("data-mx-theme");
      else root.setAttribute("data-mx-theme", name);
      if (remember !== false) store.set("theme", name === "matrix" ? null : name);
      if (api.background && api.background.recolor) api.background.recolor();
      fire(root, "mx:theme");
    }
  };

  /* --- density (2.0) -------------------------------------------------------
     <html data-mx-density="compact">, or the same attribute on any one
     element. set() changes the whole page and is remembered per browser,
     like the theme. Touch targets never shrink on a coarse pointer;
     the CSS sees to that. */
  var density = {
    list: ["comfortable", "compact", "dense"],
    get: function (el) {
      var host = el ? closest(el, "[data-mx-density]") : root;
      return (host && host.getAttribute("data-mx-density")) || "comfortable";
    },
    set: function (name, remember) {
      if (!name || name === "comfortable") root.removeAttribute("data-mx-density");
      else root.setAttribute("data-mx-density", name);
      if (remember !== false) store.set("density", name === "comfortable" ? null : name);
      fire(root, "mx:density");
    }
  };

  /* --- tabs -----------------------------------------------------------
     Buttons carry data-mx-tab="<view>"; panels carry data-mx-panel with
     the views they appear in.

     On a 1.x page the selection lands on body[data-mx-view] and the CSS
     does the rest, so from expanded up this has no visible effect --
     every panel is shown there. Inside an .mx-app (2.0) the buttons and
     panels of that app form their own group, the selection lands on the
     app, and one view shows at every width: two apps in two panes never
     share a selection. */
  function tabs(scope) {
    var app = scope && scope.nodeType === 1 && scope.classList.contains("mx-app") ? scope : null;
    var within = app || document;
    function own(el) { return closest(el, ".mx-app") === app; }
    var buttons = [].slice.call(within.querySelectorAll("[data-mx-tab]")).filter(own);
    if (!buttons.length) return null;
    var panels = [].slice.call(within.querySelectorAll("[data-mx-panel]")).filter(own);
    var host = app || document.body;
    // Only once tabs are actually wired does the CSS start hiding
    // panels -- otherwise a page with no JS would show none of them.
    host.classList.add("mx-tabbed");

    function show(view) {
      host.setAttribute("data-mx-view", view);
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
      fire(host, "mx:view", view);
      reveal();
    }

    /* A strip that scrolls (2.1.1): bring the selected tab into view by
       moving the strip itself, never the page. */
    function reveal() {
      var on = buttons.filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0];
      var strip = on && closest(on, ".mx-tabs");
      if (!strip || strip.scrollWidth <= strip.clientWidth) return;
      var r = on.getBoundingClientRect(), sr = strip.getBoundingClientRect(), pad = 16;
      var left = r.left - sr.left + strip.scrollLeft, right = left + r.width;
      if (left - pad < strip.scrollLeft) strip.scrollLeft = Math.max(0, left - pad);
      else if (right + pad > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = right + pad - strip.clientWidth;
    }
    if (window.ResizeObserver) {
      var strips = [];
      buttons.forEach(function (b) { var s = closest(b, ".mx-tabs"); if (s && strips.indexOf(s) === -1) strips.push(s); });
      strips.forEach(function (s) { watch(s, reveal); });
    }

    buttons.forEach(function (b) {
      b.addEventListener("click", function () { show(b.getAttribute("data-mx-tab")); });
    });

    var picked = buttons.filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0];
    show(host.getAttribute("data-mx-view") || (picked || buttons[0]).getAttribute("data-mx-tab"));

    return {
      show: show,
      current: function () { return host.getAttribute("data-mx-view"); },
      /* True when the view is on screen: either it's the selected tab,
         or (1.x page) the screen is big enough that everything shows. */
      visible: function (view) {
        return host.getAttribute("data-mx-view") === view ||
          (!app && !document.body.classList.contains("mx-nav-views") && isWide());
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
    // A command bar inside an .mx-app is part of that app's page (2.0).
    var bar = [].filter.call(document.querySelectorAll(".mx-cmdbar"), function (b) { return !closest(b, ".mx-app"); })[0];
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

  /* --- list + detail, master-detail ------------------------------------------------
     .mx-layout-list-detail (1.x) follows the window. .mx-master-detail
     (2.0) follows its app; when it is drilled in (the detail has
     replaced the list), opening moves focus into the detail and closing
     puts it back on the row that opened it. */
  var MD = ".mx-master-detail, .mx-layout-list-detail";
  function part(layout, cls) {
    for (var c = layout.firstElementChild; c; c = c.nextElementSibling) if (c.classList.contains(cls)) return c;
    return null;
  }
  var detail = {
    open: function (layout, opener) {
      layout = layout || document.querySelector(MD);
      if (!layout) return;
      layout.setAttribute("data-mx-detail", "open");
      if (!layout.classList.contains("mx-master-detail")) {
        // On small screens the detail replaces the list; bring its top into view.
        if (!isWide() && layout.getBoundingClientRect().top < 0) layout.scrollIntoView();
        return;
      }
      var list = part(layout, "mx-md-list"), det = part(layout, "mx-md-detail");
      if (opener && list && list.contains(opener)) {
        [].forEach.call(list.querySelectorAll("[data-mx-detail-open]"), function (o) {
          o.classList.toggle("mx-selected", o === opener);
          if (o === opener) o.setAttribute("aria-current", "true"); else o.removeAttribute("aria-current");
        });
        layout.__mxOpener = opener;
      }
      if (det && !shown(list)) {
        [].forEach.call(det.querySelectorAll(".mx-scroll-region"), function (r) { r.scrollTop = 0; });
        focusQuietly(det.querySelector("[data-mx-autofocus], .mx-md-title, h1, h2, h3") || det);
      }
      fire(layout, "mx:detail", "open");
    },
    close: function (layout) {
      layout = layout || document.querySelector(MD);
      if (!layout) return;
      var drilled = layout.classList.contains("mx-master-detail") && !shown(part(layout, "mx-md-list"));
      layout.removeAttribute("data-mx-detail");
      if (drilled && layout.__mxOpener) focusQuietly(layout.__mxOpener);
      fire(layout, "mx:detail", "close");
    },
    /* True while the detail has replaced the list (narrow layouts). */
    drilled: function (layout) {
      layout = layout || document.querySelector(".mx-master-detail");
      return !!(layout && layout.getAttribute("data-mx-detail") === "open" && !shown(part(layout, "mx-md-list")));
    }
  };

  /* --- app (2.0) -------------------------------------------------------------
     Each .mx-app gets its own tab group and a data-mx-range for scripts. */
  function app(el) {
    if (el.__mxApp) return;
    el.__mxApp = true;
    watch(el, function () {
      var r = rangeOf(el.clientWidth);
      if (r !== el.getAttribute("data-mx-range")) {
        el.setAttribute("data-mx-range", r);
        fire(el, "mx:range", r);
      }
    });
    el.mxView = tabs(el);
  }

  /* --- application navigation (2.0) --------------------------------------------
     The CSS turns .mx-app-nav into a sidebar, rail or tab strip. Below
     360px it becomes a selector, which needs a button: this adds one
     (unless the markup has it) that names the current section and
     opens the rest. It also keeps the current tab in view in the strip. */
  var navs = [];
  function appNav(nav) {
    var list = nav.querySelector(".mx-app-nav-list");
    if (nav.__mxNav || !list) return;
    nav.__mxNav = true;
    var toggle = nav.querySelector(".mx-app-nav-toggle");
    if (!toggle) {
      toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "mx-app-nav-toggle";
      toggle.innerHTML = "<span></span>" + svg('<path d="M6 9l6 6 6-6"/>');
      nav.insertBefore(toggle, list);
    }
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", idOf(list));
    var label = toggle.querySelector("span") || toggle;

    function current() {
      return list.querySelector('[aria-current="page"], [aria-selected="true"], .mx-selected') || list.querySelector(".mx-app-nav-item");
    }
    function sync() {
      var c = current();
      var l = c && (c.querySelector(".mx-app-nav-label") || c);
      label.textContent = l ? l.textContent.replace(/\s+/g, " ").trim() : "";
      // In the tab strip, scroll the strip (never the page) to the current item.
      if (c && list.scrollWidth > list.clientWidth + 1 && !nav.classList.contains("mx-open")) {
        var lr = list.getBoundingClientRect(), cr = c.getBoundingClientRect();
        if (cr.left < lr.left || cr.right > lr.right) list.scrollLeft += cr.left - lr.left - (lr.width - cr.width) / 2;
      }
    }
    function setOpen(open) {
      nav.classList.toggle("mx-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    nav.__mxClose = function (refocus) {
      if (!nav.classList.contains("mx-open")) return false;
      setOpen(false);
      if (refocus) toggle.focus();
      return true;
    };
    toggle.addEventListener("click", function () {
      var open = !nav.classList.contains("mx-open");
      setOpen(open);
      if (open) focusQuietly(current());
    });
    list.addEventListener("click", function (e) {
      if (closest(e.target, ".mx-app-nav-item")) { setOpen(false); setTimeout(sync, 0); }
    });
    if (window.MutationObserver) {
      new MutationObserver(sync).observe(list, { subtree: true, attributes: true, attributeFilter: ["aria-current", "aria-selected", "class"] });
    }
    watch(nav, sync);
    navs.push(nav);
  }

  /* --- adaptive toolbar (2.0) --------------------------------------------------
     The CSS moves actions to the overflow menu by priority and toolbar
     width. This builds that menu's copies when the markup doesn't have
     them (a copy clicks its original), and moves anything that still
     doesn't fit -- a long label, a translation -- lowest priority first.
     The bar never wraps to a second row. */
  function toolbar(tb) {
    if (tb.__mxBar) return;
    tb.__mxBar = true;
    function mine(el) { return closest(el.parentNode, ".mx-toolbar") === tb && !closest(el, ".mx-toolbar-more"); }
    var actions = [].filter.call(tb.querySelectorAll("[data-mx-priority]"), mine);
    if (!actions.length) return;
    var more = [].filter.call(tb.querySelectorAll(".mx-toolbar-more"), function (m) { return closest(m.parentNode, ".mx-toolbar") === tb; })[0];
    if (!more) {
      more = document.createElement("div");
      more.className = "mx-menu mx-toolbar-more";
      more.innerHTML = '<button class="mx-btn mx-square mx-ghost" type="button" data-mx-menu-toggle aria-haspopup="menu" aria-expanded="false" aria-label="More actions">' +
        svg('<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>') +
        '</button><div class="mx-menu-pop" role="menu"></div>';
      tb.appendChild(more);
    }
    var pop = more.querySelector(".mx-menu-pop");
    var first = pop.firstChild;
    var pairs = [];
    actions.forEach(function (a) {
      var key = a.getAttribute("data-mx-action");
      var copy = key && pop.querySelector('[data-mx-action="' + key + '"]');
      if (!copy) {
        copy = document.createElement("button");
        copy.type = "button";
        copy.className = "mx-menu-item" + (a.classList.contains("mx-danger") ? " mx-danger" : "");
        copy.setAttribute("role", "menuitem");
        copy.setAttribute("data-mx-priority", a.getAttribute("data-mx-priority"));
        var icon = a.querySelector("svg");
        if (icon) copy.appendChild(icon.cloneNode(true));
        var text = a.querySelector(".mx-toolbar-label") || a;
        copy.appendChild(document.createTextNode(a.getAttribute("aria-label") || text.textContent.replace(/\s+/g, " ").trim()));
        if (a.disabled) copy.disabled = true;
        copy.addEventListener("click", function () { a.click(); });
        pop.insertBefore(copy, first);
      }
      pairs.push({ a: a, c: copy, p: a.getAttribute("data-mx-priority") });
    });

    function fit() {
      pairs.forEach(function (x) { x.a.classList.remove("mx-overflowed"); x.c.classList.remove("mx-overflowed"); });
      more.hidden = false;
      var rank = { menu: 0, "1": 1, "2": 2, "3": 3 };
      var candidates = pairs.filter(function (x) { return x.p !== "menu" && shown(x.a); })
        .sort(function (x, y) { return (rank[y.p] || 0) - (rank[x.p] || 0) || pairs.indexOf(y) - pairs.indexOf(x); });
      while (tb.scrollWidth > tb.clientWidth + 1 && candidates.length) {
        var x = candidates.shift();
        x.a.classList.add("mx-overflowed");
        x.c.classList.add("mx-overflowed");
      }
      var any = [].some.call(pop.children, shown);
      if (!any) { menu.closeAll(); more.hidden = true; }
    }
    watch(tb, fit);
  }

  /* --- split handles (2.0) -----------------------------------------------------
     Drag, or arrow keys while focused, to move --mx-split on the
     .mx-split around it. data-mx-split-key on the .mx-split remembers
     the position per browser. Fires mx:split. */
  function split(handle) {
    var box = handle.parentNode;
    if (handle.__mxSplit || !box || !box.classList.contains("mx-split")) return;
    handle.__mxSplit = true;
    var vertical = box.classList.contains("mx-split-y");
    var lo = +(box.getAttribute("data-mx-split-min") || 15), hi = 100 - lo;
    var key = box.getAttribute("data-mx-split-key");
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", vertical ? "horizontal" : "vertical");
    if (!handle.hasAttribute("tabindex")) handle.setAttribute("tabindex", "0");
    handle.setAttribute("aria-valuemin", lo);
    handle.setAttribute("aria-valuemax", hi);
    function get() {
      var v = parseFloat(box.style.getPropertyValue("--mx-split"));
      if (!isNaN(v)) return v;
      var a = box.firstElementChild, r = box.getBoundingClientRect(), ar = a.getBoundingClientRect();
      return vertical ? ar.height / r.height * 100 : ar.width / r.width * 100;
    }
    function set(pct, remember) {
      pct = Math.max(lo, Math.min(hi, pct));
      box.style.setProperty("--mx-split", pct.toFixed(2) + "%");
      handle.setAttribute("aria-valuenow", Math.round(pct));
      if (key && remember) store.set("split." + key, pct.toFixed(2));
      fire(box, "mx:split", pct);
    }
    var saved = key && parseFloat(store.get("split." + key, ""));
    if (saved) set(saved); else handle.setAttribute("aria-valuenow", Math.round(get()));
    var dragging = null;
    function at(e) {
      var r = box.getBoundingClientRect();
      return vertical ? (e.clientY - r.top) / r.height * 100 : (e.clientX - r.left) / r.width * 100;
    }
    if (window.PointerEvent) {
      handle.addEventListener("pointerdown", function (e) {
        if (e.button !== 0) return;
        dragging = e.pointerId;
        handle.setPointerCapture(e.pointerId);
        handle.classList.add("mx-active");
        e.preventDefault();
      });
      handle.addEventListener("pointermove", function (e) { if (dragging === e.pointerId) set(at(e)); });
      var end = function (e) {
        if (dragging !== e.pointerId) return;
        dragging = null;
        handle.classList.remove("mx-active");
        set(get(), true);
      };
      handle.addEventListener("pointerup", end);
      handle.addEventListener("pointercancel", end);
    }
    handle.addEventListener("keydown", function (e) {
      var step = e.shiftKey ? 1 : 5, v = get(), to = null;
      var back = vertical ? ["ArrowUp", "Up"] : ["ArrowLeft", "Left"];
      var fwd = vertical ? ["ArrowDown", "Down"] : ["ArrowRight", "Right"];
      if (back.indexOf(e.key) !== -1) to = v - step;
      else if (fwd.indexOf(e.key) !== -1) to = v + step;
      else if (e.key === "Home") to = lo;
      else if (e.key === "End") to = hi;
      if (to === null) return;
      e.preventDefault();
      set(to, true);
    });
  }

  /* --- roving focus (2.0) --------------------------------------------------------
     A strip of tabs or items is one Tab stop; the arrow keys move inside
     it, Home and End jump to the ends. On .mx-pane-tabs and anything
     with data-mx-roving (its value, if any, is the item selector).
     Items with role="tab" are selected as focus lands on them, and fire
     mx:select. */
  function roving(group) {
    if (group.__mxRoving) return;
    group.__mxRoving = true;
    var sel = group.getAttribute("data-mx-roving") || '[role="tab"], .mx-quickswitch-item, .mx-app-nav-item';
    var vertical = group.getAttribute("aria-orientation") === "vertical";
    function items() { return [].filter.call(group.querySelectorAll(sel), function (el) { return shown(el) && !el.disabled; }); }
    function select(el) {
      if (el.getAttribute("role") !== "tab") return;
      items().forEach(function (t) {
        var on = t === el;
        t.setAttribute("aria-selected", on ? "true" : "false");
        var wrap = closest(t, ".mx-pane-tab");
        if (wrap) wrap.classList.toggle("mx-selected", on);
      });
      fire(el, "mx:select");
    }
    function settle(active) {
      var list = items();
      active = active || list.filter(function (t) { return t.getAttribute("aria-selected") === "true" || t.getAttribute("aria-current"); })[0] || list[0];
      list.forEach(function (t) { t.setAttribute("tabindex", t === active ? "0" : "-1"); });
    }
    group.addEventListener("keydown", function (e) {
      var list = items(), i = list.indexOf(document.activeElement);
      if (i === -1) return;
      var prev = vertical ? ["ArrowUp", "Up"] : ["ArrowLeft", "Left"];
      var next = vertical ? ["ArrowDown", "Down"] : ["ArrowRight", "Right"];
      var to = null;
      if (prev.indexOf(e.key) !== -1) to = (i - 1 + list.length) % list.length;
      else if (next.indexOf(e.key) !== -1) to = (i + 1) % list.length;
      else if (e.key === "Home") to = 0;
      else if (e.key === "End") to = list.length - 1;
      if (to === null) return;
      e.preventDefault();
      settle(list[to]);
      list[to].focus();
      select(list[to]);
    });
    group.addEventListener("click", function (e) {
      var t = closest(e.target, sel);
      if (t && group.contains(t)) { settle(t); select(t); }
    });
    settle();
  }

  /* --- command palette (2.0) ------------------------------------------------------
     <div class="mx-palette"> with an .mx-palette-input and a list of
     .mx-palette-result. Typing filters (data-mx-search, else the text)
     and marks what matched; arrows move; Enter clicks the active result;
     a click fires mx:pick on the result. The app decides what a pick
     does. */
  function palette(el) {
    if (el.__mxPalette) return el.__mxPalette;
    var input = el.querySelector(".mx-palette-input"), list = el.querySelector(".mx-palette-results");
    if (!input || !list) return null;
    var empty = el.querySelector(".mx-palette-empty");
    var results = [].slice.call(list.querySelectorAll(".mx-palette-result"));
    list.setAttribute("role", "listbox");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-controls", idOf(list));
    input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-autocomplete", "list");
    results.forEach(function (r) {
      r.setAttribute("role", "option");
      idOf(r);
      var t = r.querySelector(".mx-slot-title") || r;
      r.__mxTitle = t;
      r.__mxText = t.textContent;
    });
    var active = null;
    function setActive(r) {
      results.forEach(function (x) { x.setAttribute("aria-selected", x === r ? "true" : "false"); });
      active = r;
      if (r) {
        input.setAttribute("aria-activedescendant", r.id);
        var lr = list.getBoundingClientRect(), rr = r.getBoundingClientRect();
        if (rr.top < lr.top) list.scrollTop -= lr.top - rr.top + 8;
        else if (rr.bottom > lr.bottom) list.scrollTop += rr.bottom - lr.bottom + 8;
      } else input.removeAttribute("aria-activedescendant");
    }
    /* Indices of q's characters in text: a run if q appears whole, else
       the first subsequence. null when it doesn't match at all. */
    function match(text, q) {
      var lower = text.toLowerCase(), at = lower.indexOf(q), out = [], i, j = 0;
      if (at !== -1) { for (i = 0; i < q.length; i++) out.push(at + i); return out; }
      for (i = 0; i < lower.length && j < q.length; i++) if (lower.charAt(i) === q.charAt(j)) { out.push(i); j++; }
      return j === q.length ? out : null;
    }
    function paint(r, hits) {
      var t = r.__mxTitle, text = r.__mxText;
      while (t.firstChild) t.removeChild(t.firstChild);
      if (!hits) { t.appendChild(document.createTextNode(text)); return; }
      var run = "";
      for (var i = 0; i < text.length; i++) {
        if (hits.indexOf(i) !== -1) {
          if (run) { t.appendChild(document.createTextNode(run)); run = ""; }
          var m = document.createElement("mark");
          m.textContent = text.charAt(i);
          t.appendChild(m);
        } else run += text.charAt(i);
      }
      if (run) t.appendChild(document.createTextNode(run));
    }
    function filter() {
      var q = input.value.replace(/^\s+|\s+$/g, "").toLowerCase();
      var visible = [];
      results.forEach(function (r) {
        var hay = r.getAttribute("data-mx-search");
        var hits = q ? match(r.__mxText, q) : null;
        var ok = !q || !!hits || (hay && match(hay, q));
        r.hidden = !ok;
        paint(r, q && hits);
        if (ok) visible.push(r);
      });
      // A group label hides when nothing under it survived.
      [].forEach.call(list.querySelectorAll(".mx-palette-group"), function (g) {
        var n = g.nextElementSibling, any = false;
        while (n && !n.classList.contains("mx-palette-group")) { if (!n.hidden && n.classList.contains("mx-palette-result")) any = true; n = n.nextElementSibling; }
        g.hidden = !any;
      });
      if (empty) empty.hidden = visible.length > 0;
      setActive(visible[0] || null);
    }
    input.addEventListener("input", filter);
    input.addEventListener("keydown", function (e) {
      var visible = results.filter(function (r) { return !r.hidden; }), i = visible.indexOf(active);
      if (e.key === "ArrowDown" || e.key === "Down") { e.preventDefault(); setActive(visible[Math.min(i + 1, visible.length - 1)] || null); }
      else if (e.key === "ArrowUp" || e.key === "Up") { e.preventDefault(); setActive(visible[Math.max(i - 1, 0)] || null); }
      else if (e.key === "Enter" && active) { e.preventDefault(); active.click(); }
    });
    list.addEventListener("mousemove", function (e) {
      var r = closest(e.target, ".mx-palette-result");
      if (r && r !== active) setActive(r);
    });
    list.addEventListener("click", function (e) {
      var r = closest(e.target, ".mx-palette-result");
      if (r) { setActive(r); fire(r, "mx:pick", r.getAttribute("data-mx-value") || r.__mxText); }
    });
    filter();
    el.__mxPalette = { filter: filter, input: input, active: function () { return active; } };
    return el.__mxPalette;
  }

  /* --- dismissable rows (2.0) -------------------------------------------------------
     [data-mx-dismiss] removes the .mx-switcher-row around it (or the
     element its value selects), after a cancelable mx:dismiss on that
     row. Focus moves to the next row, so a keyboard user stays in the
     list. */
  function dismiss(btn) {
    var row = closest(btn, btn.getAttribute("data-mx-dismiss") || ".mx-switcher-row");
    if (!row || !fire(row, "mx:dismiss", null, true)) return;
    var next = row.nextElementSibling || row.previousElementSibling;
    function gone() {
      if (row.parentNode) row.parentNode.removeChild(row);
      var f = next && (next.querySelector("[data-mx-dismiss], a, button") || next);
      if (f) focusQuietly(f);
    }
    row.classList.add("mx-out");
    if (reduceMotion) gone(); else setTimeout(gone, 240);
  }

  /* --- layout switch (2.1) -------------------------------------------------
     <div class="mx-layout-switch" data-mx-layout-switch="albums" data-mx-remember="music-albums">
       <button data-mx-layout="list">..</button><button data-mx-layout="grid">..</button></div>
     Turns .mx-view-grid on the .mx-list with id "albums" on and off, fires
     mx:layout ("grid" | "list") on it, and remembers the choice per browser
     under data-mx-remember -- every App Hub app shares one origin, so name
     it after the app. */
  function layoutSwitch(group) {
    if (group.__mxLayout) return;
    var list = document.getElementById(group.getAttribute("data-mx-layout-switch"));
    if (!list) return;
    group.__mxLayout = true;
    var key = group.getAttribute("data-mx-remember");
    function set(layout, remember) {
      list.classList.toggle("mx-view-grid", layout === "grid");
      each(group, "[data-mx-layout]", function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-mx-layout") === layout ? "true" : "false");
      });
      if (remember && key) store.set("layout." + key, layout);
      if (remember) fire(list, "mx:layout", layout);
    }
    var saved = key ? store.get("layout." + key, null) : null;
    set(saved === "grid" || saved === "list" ? saved : (list.classList.contains("mx-view-grid") ? "grid" : "list"), false);
    group.addEventListener("click", function (e) {
      var b = closest(e.target, "[data-mx-layout]");
      if (b && group.contains(b)) set(b.getAttribute("data-mx-layout"), true);
    });
  }

  /* --- search fold (2.1) -------------------------------------------------------
     In an .mx-viewbar under 360px of app, the search box is a magnifier
     ([data-mx-search-open]); pressing it opens the field across the bar
     until Cancel ([data-mx-search-close]) or Escape, which also clears it
     (an input event tells the page to show everything again). */
  var search = {
    open: function (bar) {
      if (!bar) return;
      bar.classList.add("mx-searching");
      focusQuietly(bar.querySelector(".mx-viewbar-search input"));
    },
    close: function (bar) {
      if (!bar || !bar.classList.contains("mx-searching")) return false;
      bar.classList.remove("mx-searching");
      var input = bar.querySelector(".mx-viewbar-search input");
      if (input && input.value) {
        input.value = "";
        fire(input, "input");
      }
      focusQuietly(bar.querySelector("[data-mx-search-open]"));
      return true;
    }
  };

  /* --- hold (2.1): press and hold for an item's menu --------------------------
     <a class="mx-item" data-mx-hold="album-menu">..</a>
     A press held for HOLD_MS without moving, a right-click, or the menu key
     / Shift+F10 on the focused item fires a cancelable mx:hold on it
     (detail: {x, y, by: "press" | "menu" | "key"}); unless a listener
     cancels it, the sheet with that id opens (leave the value empty to
     handle mx:hold yourself). The click that ends a held press is
     swallowed, so the item doesn't open as well. */
  var HOLD_MS = 480;
  function hold(el) {
    if (el.__mxHold) return;
    el.__mxHold = true;
    var timer = 0, sx = 0, sy = 0, held = false;
    function clear() {
      clearTimeout(timer);
      timer = 0;
      el.classList.remove("mx-holding");
    }
    function trigger(x, y, by) {
      if (fire(el, "mx:hold", { x: x, y: y, by: by }, true)) {
        var id = el.getAttribute("data-mx-hold");
        if (id && document.getElementById(id)) sheet.open(id);
      }
    }
    el.addEventListener("pointerdown", function (e) {
      held = false;
      if (e.button !== 0) return;
      sx = e.clientX; sy = e.clientY;
      el.classList.add("mx-holding");
      timer = setTimeout(function () {
        timer = 0;
        held = true;
        el.classList.remove("mx-holding");
        try { if (navigator.vibrate) navigator.vibrate(10); } catch (err) { /* ignore */ }
        trigger(sx, sy, "press");
      }, HOLD_MS);
    });
    el.addEventListener("pointermove", function (e) {
      if (timer && Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) > 10) clear();
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach(function (t) { el.addEventListener(t, clear); });
    el.addEventListener("contextmenu", function (e) {
      e.preventDefault();
      clear();
      if (held) return; // Android also sends contextmenu after a long press
      trigger(e.clientX, e.clientY, "menu");
    });
    el.addEventListener("click", function (e) {
      if (!held) return;
      held = false;
      e.preventDefault();
      e.stopImmediatePropagation();
    }, true);
    el.addEventListener("keydown", function (e) {
      if (e.key !== "ContextMenu" && !(e.shiftKey && e.key === "F10")) return;
      e.preventDefault();
      var r = el.getBoundingClientRect();
      trigger(r.left + 16, r.bottom, "key");
    });
  }

  /* --- wire a subtree (2.0) -------------------------------------------------------------
     Runs on the whole page at load. Call MX.init(el) on markup added
     later; it is safe to call twice. */
  function init(scope) {
    scope = scope || document;
    each(scope, ".mx-app", app);
    each(scope, ".mx-app-nav", appNav);
    each(scope, ".mx-toolbar", toolbar);
    each(scope, ".mx-split-handle", split);
    each(scope, ".mx-pane-tabs, [data-mx-roving]", roving);
    each(scope, ".mx-palette", palette);
    each(scope, "[data-mx-layout-switch]", layoutSwitch);
    each(scope, "[data-mx-hold]", hold);
    var imgs = scope.querySelectorAll(".mx-media > img");
    for (var i = 0; i < imgs.length; i++) if (imgs[i].complete) markMedia(imgs[i], !imgs[i].naturalWidth);
  }

  /* One delegated click handler for sheets, menus and list/detail. */
  function onClick(e) {
    var t = e.target;
    var el;
    if ((el = closest(t, "[data-mx-open]"))) { e.preventDefault(); sheet.open(el.getAttribute("data-mx-open")); return; }
    if ((el = closest(t, "[data-mx-search-open]"))) { e.preventDefault(); search.open(closest(el, ".mx-viewbar")); return; }
    if ((el = closest(t, "[data-mx-search-close]"))) { e.preventDefault(); search.close(closest(el, ".mx-viewbar")); return; }
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
    var inNav = closest(t, ".mx-app-nav");
    navs.forEach(function (n) { if (n !== inNav && n.__mxClose) n.__mxClose(); });
    if ((el = closest(t, "[data-mx-dismiss]"))) { e.preventDefault(); dismiss(el); return; }
    if ((el = closest(t, "[data-mx-detail-open]"))) detail.open(closest(el, MD), el);
    if ((el = closest(t, "[data-mx-detail-close]"))) { e.preventDefault(); detail.close(closest(el, MD)); }
  }

  /* Arrow keys inside an open menu; Escape gives focus back to its button. */
  function menuKeys(e) {
    var pop = closest(document.activeElement, ".mx-menu-pop.mx-open, .mx-menu-popover.mx-open");
    if (!pop) return false;
    var items = [].filter.call(pop.querySelectorAll(".mx-menu-item"), function (i) { return shown(i) && !i.disabled; });
    var i = items.indexOf(document.activeElement), to = null;
    if (e.key === "ArrowDown" || e.key === "Down") to = items[(i + 1) % items.length];
    else if (e.key === "ArrowUp" || e.key === "Up") to = items[(i - 1 + items.length) % items.length];
    else if (e.key === "Home") to = items[0];
    else if (e.key === "End") to = items[items.length - 1];
    if (!to) return false;
    e.preventDefault();
    to.focus();
    return true;
  }

  function onKey(e) {
    if (e.key === "Escape" || e.key === "Esc") {
      // The innermost thing first: a menu, then an app nav selector, then
      // the top sheet -- so Escape in a menu inside a sheet closes the menu.
      var active = document.activeElement;
      if (search.close(closest(active, ".mx-viewbar.mx-searching"))) return;
      var menuEl = closest(active, ".mx-menu");
      var pop = menuEl && menuEl.querySelector(".mx-menu-pop.mx-open, .mx-menu-popover.mx-open");
      if (pop) {
        menu.closeAll();
        var back = menuEl.querySelector("[data-mx-menu-toggle]");
        if (back) back.focus();
        return;
      }
      var navEl = closest(active, ".mx-app-nav");
      if (navEl && navEl.__mxClose && navEl.__mxClose(true)) return;
      var ov = closest(active, ".mx-overlay.mx-open");
      if (ov) { sheet.close(ov); return; }
      // Escape inside a drilled-in detail goes back to the list.
      var md = closest(active, ".mx-master-detail");
      if (md && detail.drilled(md) && !closest(active, "input, textarea, select")) { detail.close(md); return; }
      ov = sheet.top();
      if (ov) { sheet.close(ov); return; }
      if (document.querySelector(".mx-menu-pop.mx-open, .mx-menu-popover.mx-open")) { menu.closeAll(); return; }
      for (var i = 0; i < navs.length; i++) if (navs[i].__mxClose(false)) return;
      return;
    }
    if (e.defaultPrevented) return;
    if ((e.target.getAttribute && e.target.getAttribute("data-mx-menu-toggle") !== null) &&
        (e.key === "ArrowDown" || e.key === "Down")) {
      var m = closest(e.target, ".mx-menu");
      var p = m && m.querySelector(".mx-menu-pop, .mx-menu-popover");
      if (p && !p.classList.contains("mx-open")) menu.toggle(m);
      var firstItem = p && [].filter.call(p.querySelectorAll(".mx-menu-item"), shown)[0];
      if (firstItem) { e.preventDefault(); firstItem.focus(); }
      return;
    }
    if (menuKeys(e)) return;
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
  /* The third argument is the toasts host (1.x), or options (2.1):
     {action: {label, run}, ms, host}. A toast with an action stays a
     little longer, and pressing the action dismisses it. Returns
     {dismiss}. */
  function toast(ok, message, opts) {
    var host = opts && opts.nodeType === 1 ? opts : null;
    opts = host ? {} : (opts || {});
    host = host || opts.host || document.querySelector(".mx-toasts");
    if (!host) {
      host = document.createElement("div");
      host.className = "mx-toasts";
      host.setAttribute("role", "status");
      host.setAttribute("aria-live", "polite");
      document.body.appendChild(host);
    }
    var el = document.createElement("div");
    el.className = "mx-toast " + (ok ? "mx-ok" : "mx-err");
    var gone = false;
    function dismiss() {
      if (gone) return;
      gone = true;
      el.classList.add("mx-out");
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 260);
    }
    var action = opts.action;
    if (action && action.label) {
      el.classList.add("mx-has-action");
      var msg = document.createElement("span");
      msg.className = "mx-toast-msg";
      msg.textContent = message;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mx-btn mx-ghost mx-sm";
      btn.textContent = action.label;
      btn.addEventListener("click", function () {
        dismiss();
        if (typeof action.run === "function") action.run();
      });
      el.appendChild(msg);
      el.appendChild(btn);
    } else {
      el.textContent = message;
    }
    host.appendChild(el);
    setTimeout(dismiss, opts.ms || (action ? 6500 : 4200));
    return { dismiss: dismiss };
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
    ranges: RANGES,
    range: range,
    density: density,
    init: init,
    toolbar: toolbar,
    appNav: appNav,
    split: split,
    roving: roving,
    palette: palette,
    layoutSwitch: layoutSwitch,   // 2.1
    hold: hold,                   // 2.1
    search: search,               // 2.1: open(bar) / close(bar)
    dismiss: dismiss,
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
  if (!root.hasAttribute("data-mx-density")) {
    var dens = store.get("density", null);
    if (dens) root.setAttribute("data-mx-density", dens);
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
    init(document);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  return api;
})();
