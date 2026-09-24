/* Friends' read-only library: expand an album to see its tracks, filter
   by album, artist or song title. */
(function () {
  "use strict";

  var rows = [].slice.call(document.querySelectorAll("#albumList .mx-row"));
  var count = document.getElementById("libraryCount");
  var haystacks = rows.map(function (row) { return row.textContent.toLowerCase().replace(/\s+/g, " "); });

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
    rows.forEach(function (row, i) {
      var match = words.every(function (w) { return haystacks[i].indexOf(w) !== -1; });
      row.hidden = !match;
      if (match) shown++;
    });
    count.textContent = shown + (shown === 1 ? " album" : " albums");
  });
})();
