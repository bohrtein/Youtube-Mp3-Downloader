/* Friend suggestion page: search / paste a link -> flat song list ->
   basket (kept in localStorage until sent) -> submit.
   Every string from the server is set with textContent, never innerHTML. */
(function () {
  "use strict";

  var cfg = document.body.dataset;
  var toastHost = document.getElementById("toastHost");
  var MAX_KEPT = 50;
  var MAX_TOTAL = 150;
  var POLL_MS = 1500;
  var POLL_LIMIT_MS = 8 * 60 * 1000;

  var statusEl = document.getElementById("lookupStatus");
  var resultsPanel = document.getElementById("resultsPanel");
  var resultsList = document.getElementById("resultsList");
  var resultsNote = document.getElementById("resultsNote");
  var resultsCount = document.getElementById("resultsCount");
  var basketList = document.getElementById("basketList");
  var basketCount = document.getElementById("basketCount");
  var submitBtn = document.getElementById("submitBtn");
  var messageInput = document.getElementById("messageInput");
  var busy = false;
  var results = [];

  /* --- basket storage ---------------------------------------------------- */
  function loadBasket() {
    try {
      var saved = JSON.parse(localStorage.getItem(cfg.basketKey) || "[]");
      return Array.isArray(saved) ? saved.filter(function (s) { return s && s.youtube_id; }) : [];
    } catch (e) { return []; }
  }
  function saveBasket() {
    try { localStorage.setItem(cfg.basketKey, JSON.stringify(basket)); } catch (e) { /* private mode */ }
  }
  var basket = loadBasket();
  function inBasket(id) { return basket.some(function (s) { return s.youtube_id === id; }); }

  /* --- helpers ---------------------------------------------------------------- */
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function fmt(seconds) {
    if (!seconds && seconds !== 0) return "";
    seconds = Math.round(seconds);
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
  }
  function toast(ok, msg) { MX.toast(ok, msg, toastHost); }
  function setStatus(msg, isError) {
    statusEl.textContent = msg || "";
    statusEl.className = "sg-status" + (isError ? " mx-err" : "");
  }
  function api(url, options) {
    options = options || {};
    if (options.body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(options.body);
    }
    return fetch(url, options).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        return { ok: resp.ok, status: resp.status, data: data };
      });
    }).catch(function () {
      return { ok: false, status: 0, data: { error: "Couldn't reach the server. Check your connection." } };
    });
  }

  /* One song's text: what was asked for (Spotify) and what was found (YouTube). */
  function songInfo(song) {
    var main = el("div", "sg-song-main");
    var title = song.sp_title ? (song.sp_artist ? song.sp_artist + " - " : "") + song.sp_title : song.title;
    main.appendChild(el("span", "sg-song-title", title));
    var meta = [];
    if (song.sp_title) meta.push("YouTube: " + song.title);
    else if (song.channel || song.artist) meta.push(song.channel || song.artist);
    if (song.album && !song.sp_title) meta.push(song.album);
    if (song.duration) meta.push(fmt(song.duration));
    main.appendChild(el("span", "sg-song-meta", meta.join(" · ")));
    var pills = el("div", "sg-pills");
    if (song.in_library === "yes") pills.appendChild(el("span", "sg-flag sg-good", "in library"));
    else if (song.in_library === "maybe") pills.appendChild(el("span", "sg-flag", "maybe in library"));
    main.appendChild(pills);
    return main;
  }

  /* --- results ------------------------------------------------------------------ */
  function renderResults(note) {
    resultsPanel.hidden = false;
    APP.decodeAll(resultsPanel);
    resultsList.textContent = "";
    resultsNote.hidden = !note;
    resultsNote.textContent = note || "";
    resultsCount.textContent = results.length + (results.length === 1 ? " song" : " songs");
    results.forEach(function (song) {
      var row = el("div", "sg-song");
      row.appendChild(songInfo(song));
      var added = inBasket(song.youtube_id);
      var btn = el("button", "mx-btn sg-btn-sm" + (added ? " sg-added" : ""), added ? "Added" : "Add");
      btn.type = "button";
      btn.addEventListener("click", function () {
        if (inBasket(song.youtube_id)) removeFromBasket(song.youtube_id);
        else addToBasket([song]);
      });
      row.appendChild(btn);
      resultsList.appendChild(row);
    });
  }

  function addToBasket(songs) {
    var added = 0;
    songs.forEach(function (song) {
      if (inBasket(song.youtube_id)) return;
      if (basket.length >= MAX_TOTAL) return;
      basket.push({
        youtube_id: song.youtube_id, title: song.title, channel: song.channel || "",
        artist: song.artist || "", album: song.album || "", duration: song.duration || null,
        in_library: song.in_library || "no", sp_title: song.sp_title || "", sp_artist: song.sp_artist || "",
        kept: song.in_library !== "yes"
      });
      added++;
    });
    if (basket.length >= MAX_TOTAL && added < songs.length) toast(false, "The basket is full (" + MAX_TOTAL + " songs).");
    saveBasket();
    renderBasket();
    if (results.length) renderResults(resultsNote.textContent);
  }

  function removeFromBasket(id) {
    basket = basket.filter(function (s) { return s.youtube_id !== id; });
    saveBasket();
    renderBasket();
    if (results.length) renderResults(resultsNote.textContent);
  }

  /* --- basket ------------------------------------------------------------------- */
  function renderBasket() {
    basketList.textContent = "";
    var kept = basket.filter(function (s) { return s.kept; }).length;
    basketCount.textContent = basket.length
      ? kept + " of " + basket.length + " ticked" + (kept > MAX_KEPT ? " (max " + MAX_KEPT + ")" : "")
      : "empty";
    submitBtn.disabled = kept === 0 || kept > MAX_KEPT;
    if (!basket.length) {
      basketList.appendChild(el("p", "sg-empty", "Add songs from your search results."));
      return;
    }
    basket.forEach(function (song) {
      var row = el("div", "sg-song" + (song.kept ? "" : " sg-off"));
      var box = el("input", "sg-check");
      box.type = "checkbox";
      box.checked = !!song.kept;
      box.setAttribute("aria-label", "Keep " + (song.sp_title || song.title));
      box.addEventListener("change", function () {
        song.kept = box.checked;
        saveBasket();
        renderBasket();
      });
      row.appendChild(box);
      row.appendChild(songInfo(song));
      var remove = el("button", "mx-btn sg-btn-sm", "✕");
      remove.type = "button";
      remove.setAttribute("aria-label", "Remove from basket");
      remove.addEventListener("click", function () { removeFromBasket(song.youtube_id); });
      row.appendChild(remove);
      basketList.appendChild(row);
    });
  }

  /* --- lookups (search / link) ----------------------------------------------- */
  function setBusy(on) {
    busy = on;
    document.querySelectorAll("#searchForm button, #linkForm button").forEach(function (b) { b.disabled = on; });
  }

  function lookup(url, payload, label) {
    if (busy) return;
    setBusy(true);
    setStatus(label + "...");
    api(url, { method: "POST", body: payload }).then(function (res) {
      if (!res.ok) throw new Error(res.data.error || "That didn't work. Try again.");
      if (res.data.status === "done") return res.data;
      return poll(res.data.job_id, label, Date.now());
    }).then(function (data) {
      results = data.results || [];
      setStatus(results.length ? "" : "Nothing found.");
      renderResults(data.note);
    }).catch(function (err) {
      setStatus(err.message, true);
    }).then(function () { setBusy(false); });
  }

  function poll(jobId, label, started) {
    return new Promise(function (resolve, reject) {
      function tick() {
        api(cfg.jobUrl.replace("JOBID", encodeURIComponent(jobId))).then(function (res) {
          if (!res.ok) return reject(new Error(res.data.error || "That search expired. Try again."));
          var job = res.data;
          if (job.status === "done") return resolve(job);
          if (job.status === "error") return reject(new Error(job.error || "That didn't work."));
          if (Date.now() - started > POLL_LIMIT_MS) return reject(new Error("That's taking too long. Try again later."));
          setStatus(job.progress || (job.status === "queued" ? label + " (waiting for other searches)..." : label + "..."));
          setTimeout(tick, POLL_MS);
        });
      }
      setTimeout(tick, POLL_MS);
    });
  }

  document.getElementById("searchForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var q = document.getElementById("searchInput").value.trim();
    if (!q) return setStatus("Type something to search for.", true);
    var mode = document.querySelector('input[name="mode"]:checked').value;
    lookup(cfg.searchUrl, { mode: mode, q: q }, "Searching");
  });

  document.getElementById("linkForm").addEventListener("submit", function (e) {
    e.preventDefault();
    var link = document.getElementById("linkInput").value.trim();
    if (!link) return setStatus("Paste a link first.", true);
    lookup(cfg.resolveUrl, { url: link }, "Opening link");
  });

  var searchInput = document.getElementById("searchInput");
  var placeholders = { song: "Song title and artist...", artist: "Artist name...", album: "Album name and artist..." };
  document.querySelectorAll('input[name="mode"]').forEach(function (radio) {
    radio.addEventListener("change", function () { searchInput.placeholder = placeholders[radio.value]; });
  });

  document.getElementById("addAllBtn").addEventListener("click", function () { addToBasket(results); });
  document.getElementById("clearBasketBtn").addEventListener("click", function () {
    if (basket.length && confirm("Empty the basket?")) {
      basket = [];
      saveBasket();
      renderBasket();
      if (results.length) renderResults(resultsNote.textContent);
    }
  });

  /* --- submit + sent list ---------------------------------------------------- */
  submitBtn.addEventListener("click", function () {
    var kept = basket.filter(function (s) { return s.kept; }).length;
    if (!kept) return toast(false, "Tick at least one song.");
    submitBtn.disabled = true;
    api(cfg.submitUrl, {
      method: "POST",
      body: {
        items: basket.map(function (s) { return { youtube_id: s.youtube_id, kept: !!s.kept }; }),
        message: messageInput.value.trim()
      }
    }).then(function (res) {
      if (res.status === 409 && res.data.expired) {
        var gone = res.data.expired;
        basket = basket.filter(function (s) { return gone.indexOf(s.youtube_id) === -1; });
        saveBasket();
        renderBasket();
        return toast(false, res.data.error);
      }
      if (!res.ok) return toast(false, res.data.error || "Couldn't send. Try again.");
      toast(true, "Sent " + res.data.kept + (res.data.kept === 1 ? " song" : " songs") + ". Thanks!");
      basket = [];
      messageInput.value = "";
      saveBasket();
      renderBasket();
      if (results.length) renderResults(resultsNote.textContent);
      loadSent();
    }).then(function () { renderBasket(); });
  });

  var STATUS_LABELS = {
    pending: "waiting for review",
    in_review: "being reviewed",
    done: "done",
    rejected: "not this time"
  };

  function loadSent() {
    api(cfg.submissionsUrl).then(function (res) {
      if (!res.ok) return;
      var list = document.getElementById("sentList");
      list.textContent = "";
      var subs = res.data.submissions || [];
      if (!subs.length) return list.appendChild(el("p", "sg-empty", "Nothing sent yet."));
      subs.forEach(function (s) {
        var row = el("div", "sg-song");
        var main = el("div", "sg-song-main");
        main.appendChild(el("span", "sg-song-title", (s.kept_count || 0) + " songs · " + (s.created_at || "").slice(0, 10)));
        var meta = STATUS_LABELS[s.status] || s.status;
        if (s.downloaded_count) meta += " · " + s.downloaded_count + " added to the library";
        main.appendChild(el("span", "sg-song-meta", meta));
        row.appendChild(main);
        list.appendChild(row);
      });
    });
  }

  renderBasket();
  loadSent();
})();
