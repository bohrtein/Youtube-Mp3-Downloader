/* Friends' read-only library: expand an album to see its tracks, filter
   by album, artist or song title. */
(function () {
  "use strict";

  var rows = [].slice.call(document.querySelectorAll("#albumList .mx-row"));
  var count = document.getElementById("libraryCount");

  rows.forEach(function (row) {
    var head = row.querySelector(".mx-row-head");
    head.addEventListener("click", function () {
      var open = row.classList.toggle("mx-open");
      head.setAttribute("aria-expanded", open ? "true" : "false");
    });
  });

  document.getElementById("libraryFilter").addEventListener("input", function (e) {
    var words = e.target.value.toLowerCase().split(/\s+/).filter(Boolean);
    var shown = 0;
    rows.forEach(function (row) {
      var haystack = row.textContent.toLowerCase().replace(/\s+/g, " ");
      var match = words.every(function (w) { return haystack.indexOf(w) !== -1; });
      row.hidden = !match;
      if (match) shown++;
    });
    count.textContent = shown + (shown === 1 ? " album" : " albums");
  });

  document.getElementById("librarySort").addEventListener("change", function (e) {
    rows.sort(e.target.value === "name"
      ? function (a, b) { return a.dataset.name.localeCompare(b.dataset.name); }
      : function (a, b) { return Number(b.dataset.release) - Number(a.dataset.release); });
    rows.forEach(function (row) { row.parentNode.appendChild(row); });
  });
})();
