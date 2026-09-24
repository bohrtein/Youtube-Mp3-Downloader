"""Friend-side searches and link lookups, run one at a time on a background
worker so friends can never fire yt-dlp in parallel. Pages poll for job
results: the app hub proxy times out after 30s, and friends get no
Socket.IO."""
import queue
import secrets
import threading
import time

import core.linkResolver as linkResolver
import core.musicSearch as musicSearch
import core.songMatch as songMatch
import core.spotifyClient as spotifyClient
import core.suggestFlags as suggestFlags
import core.interfaceComponents as interfaceComponents
import database.suggestionsRepo as suggestionsRepo

# --- limits -----------------------------------------------------------------
HOUR, DAY = 3600, 86400
FRIEND_LIMITS = {
    "search": [(HOUR, 30), (DAY, 150)],
    "resolve": [(HOUR, 10), (DAY, 40)],
    "submit": [(DAY, 5)],
}
SERVER_YTDLP_LIMITS = [(DAY, 300)]
YTDLP_MIN_SPACING_SECONDS = 2.0
MAX_QUEUED_JOBS = 20
MAX_QUEUED_JOBS_PER_FRIEND = 2
MAX_QUERY_LENGTH = 100
MAX_SPOTIFY_TRACKS = 100
JOB_TTL_SECONDS = HOUR

SEARCH_CACHE_TTL = DAY
LINK_CACHE_TTL = 7 * DAY
SPOTIFY_MATCH_CACHE_TTL = 30 * DAY
SERVED_TTL = 7 * DAY

SEARCH_MODES = ("song", "artist", "album")


class LookupRefused(Exception):
    """A request we won't queue; message is safe to show a friend."""

    def __init__(self, message, status=429, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class LookupFailed(Exception):
    """A job that ran but couldn't produce results; message is friend-safe."""


# --- job registry -------------------------------------------------------------
_jobs = {}
_jobs_lock = threading.Lock()
_queue = queue.Queue(maxsize=MAX_QUEUED_JOBS)
_worker_started = False
_last_ytdlp_call = [0.0]


def _ensure_worker():
    global _worker_started
    with _jobs_lock:
        if not _worker_started:
            threading.Thread(target=_worker_loop, name="friend-lookups", daemon=True).start()
            _worker_started = True


def _prune_jobs():
    cutoff = time.time() - JOB_TTL_SECONDS
    for job_id in [j for j, job in _jobs.items() if job["created"] < cutoff]:
        del _jobs[job_id]


def get_job(job_id, friend_id):
    """A job's public state, only for the friend who started it."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None or job["friend_id"] != friend_id:
            return None
        return {k: job[k] for k in ("status", "results", "note", "error", "progress")}


# --- cache keys ------------------------------------------------------------------

def search_cache_key(mode, query):
    return f"search:{mode}:{' '.join(query.lower().split())}"


def link_cache_key(link):
    return f"link:{link['kind']}:{link['id']}"


def _remember_served(friend_id, songs):
    """What each friend was shown, so a submission can only contain songs we
    actually served them - with our metadata, not whatever the page sends."""
    suggestionsRepo.cache_set_many([(f"served:{friend_id}:{s['youtube_id']}", s) for s in songs])


def served_song(friend_id, youtube_id):
    return suggestionsRepo.cache_get(f"served:{friend_id}:{youtube_id}", SERVED_TTL)


def with_library_status(songs):
    return [dict(song, in_library=suggestionsRepo.library_status(song)) for song in songs]


# --- entry points (request threads) -------------------------------------------

def start_search(friend_id, mode, query):
    """
    Returns ("done", results) on a cache hit, else ("queued", job_id).

    Raises:
        LookupRefused: bad input, rate limit, or queue full.
    """
    query = " ".join((query or "").split())
    if mode not in SEARCH_MODES:
        raise LookupRefused("Pick Song, Artist or Album.", status=400)
    if not query:
        raise LookupRefused("Type something to search for.", status=400)
    if len(query) > MAX_QUERY_LENGTH:
        raise LookupRefused(f"Keep searches under {MAX_QUERY_LENGTH} characters.", status=400)
    return _start(friend_id, "search", search_cache_key(mode, query), SEARCH_CACHE_TTL,
                  {"mode": mode, "query": query})


def start_resolve(friend_id, raw_link):
    try:
        link = linkResolver.parse_link(raw_link)
    except linkResolver.LinkError as e:
        raise LookupRefused(str(e), status=400)
    return _start(friend_id, "resolve", link_cache_key(link), LINK_CACHE_TTL, {"link": link})


def _start(friend_id, kind, cache_key, cache_ttl, params):
    cached = suggestionsRepo.cache_get(cache_key, cache_ttl)
    if cached is not None:
        _remember_served(friend_id, cached["results"])
        return "done", {"results": with_library_status(cached["results"]), "note": cached.get("note")}

    with _jobs_lock:
        _prune_jobs()
        mine = sum(1 for j in _jobs.values() if j["friend_id"] == friend_id and j["status"] in ("queued", "running"))
    if mine >= MAX_QUEUED_JOBS_PER_FRIEND:
        raise LookupRefused("Wait for your current search to finish.")

    retry_after = suggestionsRepo.try_consume(friend_id, kind, FRIEND_LIMITS[kind])
    if retry_after:
        minutes = max(1, retry_after // 60)
        raise LookupRefused(f"That's a lot of searching - try again in about {minutes} min.", retry_after=retry_after)

    job_id = secrets.token_urlsafe(12)
    job = {"id": job_id, "friend_id": friend_id, "kind": kind, "params": params, "cache_key": cache_key,
           "status": "queued", "results": None, "note": None, "error": None, "progress": None,
           "created": time.time()}
    _ensure_worker()
    with _jobs_lock:
        _jobs[job_id] = job
    try:
        _queue.put_nowait(job_id)
    except queue.Full:
        with _jobs_lock:
            del _jobs[job_id]
        raise LookupRefused("The server is busy with other searches. Try again in a minute.", status=503)
    return "queued", job_id


# --- worker ----------------------------------------------------------------------

def _worker_loop():
    while True:
        job_id = _queue.get()
        with _jobs_lock:
            job = _jobs.get(job_id)
        if job is None:
            continue
        job["status"] = "running"
        try:
            results, note = _run(job)
            suggestionsRepo.cache_set(job["cache_key"], {"results": results, "note": note})
            _remember_served(job["friend_id"], results)
            job.update(results=with_library_status(results), note=note, status="done")
        except (LookupFailed, spotifyClient.SpotifyError) as e:
            job.update(error=str(e), status="error")
        except Exception as e:
            interfaceComponents.Print_Tag(f"Friend lookup failed: {e!r}", tag="Error")
            job.update(error="Something went wrong looking that up. Try again later.", status="error")


def _ytdlp(fn, *args, cost=1):
    """Calls a musicSearch function under the server-wide yt-dlp budget and
    pacing, which protect this server's IP from YouTube blocks."""
    wait = _last_ytdlp_call[0] + YTDLP_MIN_SPACING_SECONDS - time.time()
    if wait > 0:
        time.sleep(wait)
    if suggestionsRepo.try_consume(None, "ytdlp", SERVER_YTDLP_LIMITS, cost=cost):
        raise LookupFailed("The server has done all the searching it will do today. Try again tomorrow.")
    try:
        return fn(*args)
    finally:
        _last_ytdlp_call[0] = time.time()


def _tag(songs, source, **extra):
    return [dict(song, source=source, **extra) for song in songs]


def _run(job):
    params = job["params"]
    if job["kind"] == "search":
        mode, query = params["mode"], params["query"]
        if mode == "song":
            songs = _ytdlp(musicSearch.search_songs, query, 20)
        elif mode == "artist":
            songs = _ytdlp(musicSearch.search_artist_songs, query)
        else:
            songs = _ytdlp(musicSearch.search_album_tracks, query, cost=2)
        if not songs:
            raise LookupFailed("Nothing found. Try different words.")
        return _tag(songs, "search"), None

    link = params["link"]
    kind = link["kind"]
    if kind == "video":
        song = _ytdlp(musicSearch.get_video, link["id"])
        if not song:
            raise LookupFailed("Couldn't open that video (private, removed or region-locked?).")
        return _tag([song], "youtube"), None
    if kind in ("playlist", "album"):
        songs = _ytdlp(musicSearch.list_playlist_tracks, link["url"])
        if not songs:
            raise LookupFailed("Couldn't open that playlist (private or empty?).")
        note = None
        if len(songs) >= musicSearch.MAX_PLAYLIST_TRACKS:
            note = f"Only the first {musicSearch.MAX_PLAYLIST_TRACKS} songs are shown."
        return _tag(songs, "ytm_album" if songs[0].get("album") else "yt_playlist"), note
    return _run_spotify(job, link)


def _run_spotify(job, link):
    kind = link["kind"]
    if kind == "spotify_playlist":
        tracks, truncated = spotifyClient.playlist_tracks(link["id"], MAX_SPOTIFY_TRACKS)
    elif kind == "spotify_album":
        tracks, truncated = spotifyClient.album_tracks(link["id"], MAX_SPOTIFY_TRACKS)
    else:
        tracks, truncated = spotifyClient.single_track(link["id"])
    if not tracks:
        raise LookupFailed("That Spotify link has no songs.")

    songs, unmatched = [], []
    for index, track in enumerate(tracks):
        job["progress"] = f"Matching {index + 1} of {len(tracks)} on YouTube"
        match = suggestionsRepo.cache_get(f"spmatch:{track['sp_track_id']}", SPOTIFY_MATCH_CACHE_TTL)
        if match is None:
            query = f"{track['sp_artist']} - {songMatch.strip_version_suffix(track['sp_title'])}"
            candidates = _ytdlp(musicSearch.search_songs, query, 5)
            match = best_youtube_match(track, candidates) or {}
            suggestionsRepo.cache_set(f"spmatch:{track['sp_track_id']}", match)
        if match:
            songs.append(dict(match, **track, artist=track["sp_artist"], album=track["sp_album"],
                              track_number=None, source="spotify"))
        else:
            unmatched.append(track["sp_title"])

    notes = []
    if truncated:
        notes.append(f"Spotify only shares the first {MAX_SPOTIFY_TRACKS} songs of a playlist; "
                     "search for the rest or paste them as YouTube links.")
    if unmatched:
        notes.append(f"No YouTube match for: {', '.join(unmatched[:10])}{'...' if len(unmatched) > 10 else ''}")
    if not songs:
        raise LookupFailed("None of those songs could be found on YouTube.")
    return songs, " ".join(notes) or None


def best_youtube_match(track, candidates):
    """
    Picks the YouTube result most likely to be this Spotify track: the
    artist's own channel, the same title, the same length, and none of the
    live/cover/lyrics markers the Spotify title doesn't have.
    """
    best, best_score = None, None
    wanted_title = songMatch.normalize_title(track["sp_title"], track["sp_artist"])
    for candidate in candidates:
        score = 0
        channel = candidate.get("channel") or ""
        if songMatch.artist_matches(channel, track["sp_artist"]):
            score += 3
            if channel.lower().endswith("- topic"):
                score += 1
        title = songMatch.normalize_title(candidate.get("title"), track["sp_artist"])
        if title == wanted_title:
            score += 3
        elif wanted_title and (wanted_title in title or title in wanted_title):
            score += 1
        if candidate.get("duration") and track.get("sp_duration_seconds"):
            score += -3 if suggestFlags.duration_mismatch(candidate["duration"], track["sp_duration_seconds"]) else 3
        keyword_flags = suggestFlags.compute_flags(candidate.get("title"), requested_title=track["sp_title"])
        score -= 2 * len([f for f in keyword_flags if f not in ("too_long", "too_short")])
        if best_score is None or score > best_score:
            best, best_score = candidate, score
    return best
