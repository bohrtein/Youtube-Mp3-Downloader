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

  var activeJob = null;
  var endedJobs = {};
  function jobDock(data) {
    var dock = document.getElementById("progressContainer");
    if (!dock) return;
    // A fast worker can finish before the start request's acknowledgement.
    if (data.job_id && endedJobs[data.job_id] && data.state === "running") return;
    if (data.job_id && data.state && data.state !== "running") endedJobs[data.job_id] = true;
    if (data.job_id) activeJob = data.job_id;
    var running = data.state === "running";
    var known = data.percent !== null && data.percent !== undefined;
    dock.hidden = false;
    dock.classList.toggle("mx-busy", running && !known);
    dock.classList.toggle("mx-err", data.state === "failed");
    dock.style.setProperty("--mx-progress", known ? Math.max(0, Math.min(100, data.percent)) : 0);
    document.getElementById("statusText").textContent = data.title || "Library task";
    document.getElementById("statusDetail").textContent = data.status;
    document.getElementById("statusPercent").textContent = known ? Math.round(data.percent) + "%" : "";
    var cancel = document.getElementById("cancelJob");
    cancel.hidden = !running || !data.cancellable;
    cancel.disabled = data.status === "Cancelling…";
  }

  function deleteItem(element, path, name) {
    if (!element || !element.isConnected) return;
    var parent = element.parentNode;
    var next = element.nextSibling;
    element.remove();
    function restoreRow() {
      parent.insertBefore(element, next && next.parentNode === parent ? next : null);
      var search = document.querySelector(".mx-viewbar-search input");
      if (search) search.dispatchEvent(new Event("input", { bubbles: true }));
    }
    fetch(path, { method: "DELETE" }).then(function (response) { return response.json(); }).then(function (data) {
      if (!data.success) throw new Error(data.message || "Could not delete item.");
      MX.toast(true, "Deleted " + name, {
        ms: 8000,
        action: { label: "Undo", run: function () {
          return fetch(document.body.getAttribute("data-app-root") + "/restore_delete/" + data.undo, { method: "POST" })
            .then(function (response) { return response.json(); }).then(function (result) {
              if (!result.success) throw new Error(result.message || "Could not restore item.");
              restoreRow();
            }).catch(function (error) { MX.toast(false, error.message); });
        } }
      });
    }).catch(function (error) { restoreRow(); MX.toast(false, error.message || "Delete failed."); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    decodeAll(document);
    document.querySelectorAll("[data-app-collection]").forEach(function (bar) {
      var list = document.getElementById(bar.getAttribute("data-app-collection"));
      var items = [].slice.call(list.children);
      var input = bar.querySelector("input[type='search']");
      input.addEventListener("input", function () {
        var words = input.value.toLowerCase().split(/\s+/).filter(Boolean);
        items.forEach(function (item) {
          var text = item.textContent.toLowerCase();
          item.hidden = !words.every(function (word) { return text.indexOf(word) !== -1; });
        });
      });
      bar.querySelector("[data-collection-sort]").addEventListener("change", function (event) {
        bar.querySelector(".mx-viewbar-pick > span").textContent = event.target.selectedOptions[0].textContent;
        var ordered = items.slice();
        if (event.target.value === "name") ordered.sort(function (a, b) {
          return a.getAttribute("data-name").localeCompare(b.getAttribute("data-name"));
        });
        ordered.forEach(function (item) { list.appendChild(item); });
      });
    });
    var cancel = document.getElementById("cancelJob");
    if (cancel) cancel.addEventListener("click", function () {
      if (!activeJob) return;
      cancel.disabled = true;
      fetch(document.body.getAttribute("data-app-root") + "/api/downloads/" + activeJob + "/cancel", { method: "POST" })
        .then(function (response) { return response.json(); }).then(function (result) {
          if (!result.success) throw new Error(result.message || "Could not cancel download.");
        }).catch(function (error) { cancel.disabled = false; MX.toast(false, error.message); });
    });
  });

  return { decodeAll: decodeAll, jobDock: jobDock, deleteItem: deleteItem };
})();
