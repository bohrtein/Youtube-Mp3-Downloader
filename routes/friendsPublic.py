"""The only pages friends can reach: /suggest/<token>/... Everything here is
public (the app hub lets it through without a login), so it must never
expose file paths, delete/download controls, or anything of the admin side."""
import re
from pathlib import Path

from flask import Blueprint, abort, g, jsonify, render_template, request

import core.lookupJobs as lookupJobs
import core.linkResolver as linkResolver
import core.songMatch as songMatch
import core.suggestFlags as suggestFlags
import database.suggestionsRepo as suggestionsRepo

bp = Blueprint("friends_public", __name__, url_prefix="/suggest/<token>")

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
MAX_KEPT_ITEMS = 50
MAX_TOTAL_ITEMS = 150
MAX_MESSAGE_LENGTH = 500
MAX_OPEN_SUBMISSIONS = 3
COVERS_DIR = Path(__file__).resolve().parent.parent / "static" / "covers"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


@bp.url_value_preprocessor
def load_friend(endpoint, values):
    token = (values or {}).pop("token", "")
    friend = suggestionsRepo.get_active_friend_by_token(token) if TOKEN_RE.match(token or "") else None
    if friend is None:
        # Unknown and revoked links look exactly like any other missing page.
        abort(404)
    g.friend = friend
    g.friend_token = token


@bp.url_defaults
def keep_token(endpoint, values):
    if "token" not in values and "friend_token" in g:
        values["token"] = g.friend_token


@bp.before_request
def suggestions_paused():
    if suggestionsRepo.suggestions_enabled():
        return None
    if request.blueprint == "friends_public" and request.endpoint.startswith("friends_public.api_"):
        return jsonify({"error": "Suggestions are paused right now."}), 503
    return render_template("suggest_paused.html", friend=g.friend), 503


@bp.after_request
def security_headers(response):
    # The token is in the URL: never leak it through Referer to YouTube links.
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    return response


def _error(message, status, retry_after=None):
    response = jsonify({"error": message})
    response.status_code = status
    if retry_after:
        response.headers["Retry-After"] = str(retry_after)
    return response


def _json_body():
    if not request.is_json:
        abort(415)
    return request.get_json(silent=True) or {}


# --- pages ---------------------------------------------------------------------

@bp.route("/")
def home():
    return render_template("suggest.html", friend=g.friend)


@bp.route("/library")
def library():
    albums = suggestionsRepo.public_library()
    for album in albums:
        album["has_cover"] = (COVERS_DIR / f"{album['album_id']}.jpg").exists()
    return render_template("suggest_library.html", friend=g.friend, albums=albums)


# --- API -------------------------------------------------------------------------

def _lookup_response(started):
    state, payload = started
    if state == "done":
        return jsonify({"status": "done", "results": payload["results"], "note": payload.get("note")})
    return jsonify({"status": "queued", "job_id": payload}), 202


@bp.route("/api/search", methods=["POST"])
def api_search():
    data = _json_body()
    try:
        return _lookup_response(lookupJobs.start_search(g.friend["friend_id"], data.get("mode"), str(data.get("q", ""))))
    except lookupJobs.LookupRefused as e:
        return _error(str(e), e.status, e.retry_after)


@bp.route("/api/resolve", methods=["POST"])
def api_resolve():
    data = _json_body()
    try:
        return _lookup_response(lookupJobs.start_resolve(g.friend["friend_id"], str(data.get("url", ""))))
    except lookupJobs.LookupRefused as e:
        return _error(str(e), e.status, e.retry_after)


@bp.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = lookupJobs.get_job(job_id, g.friend["friend_id"])
    if job is None:
        return _error("That search expired. Run it again.", 404)
    return jsonify(job)


@bp.route("/api/submit", methods=["POST"])
def api_submit():
    data = _json_body()
    friend_id = g.friend["friend_id"]
    raw_items = data.get("items")
    message = str(data.get("message") or "").strip()[:MAX_MESSAGE_LENGTH] or None

    if not isinstance(raw_items, list) or not raw_items:
        return _error("Your basket is empty.", 400)
    if len(raw_items) > MAX_TOTAL_ITEMS:
        return _error(f"A basket can hold at most {MAX_TOTAL_ITEMS} songs.", 400)

    picked, seen_ids = [], set()
    for raw in raw_items:
        if not isinstance(raw, dict) or not linkResolver.is_video_id(str(raw.get("youtube_id", ""))):
            return _error("Your basket has a broken entry. Clear it and search again.", 400)
        if raw["youtube_id"] not in seen_ids:
            seen_ids.add(raw["youtube_id"])
            picked.append((raw["youtube_id"], bool(raw.get("kept", True))))

    kept_count = sum(1 for _, kept in picked if kept)
    if kept_count == 0:
        return _error("Tick at least one song to send.", 400)
    if kept_count > MAX_KEPT_ITEMS:
        return _error(f"Send at most {MAX_KEPT_ITEMS} songs at a time.", 400)
    if suggestionsRepo.count_open_submissions(friend_id) >= MAX_OPEN_SUBMISSIONS:
        return _error("You already have a few suggestions waiting. Try again once they've been looked at.", 429)

    songs = {youtube_id: lookupJobs.served_song(friend_id, youtube_id) for youtube_id, _ in picked}
    expired = [youtube_id for youtube_id, song in songs.items() if song is None]
    if expired:
        return jsonify({"error": "Some songs in your basket are too old. They've been removed - search for them again.",
                        "expired": expired}), 409

    retry_after = suggestionsRepo.try_consume(friend_id, "submit", lookupJobs.FRIEND_LIMITS["submit"])
    if retry_after:
        return _error("That's enough suggestions for today. Try again tomorrow.", 429, retry_after)

    items, kept_titles = [], set()
    for youtube_id, kept in picked:
        song = songs[youtube_id]
        artist = song.get("sp_artist") or song.get("artist")
        title_key = (songMatch.normalize_title(song.get("sp_title") or song["title"], artist or song.get("channel")),
                     songMatch.normalize_artist(artist or song.get("channel")))
        duplicate = kept and title_key in kept_titles
        if kept:
            kept_titles.add(title_key)
        in_library = suggestionsRepo.library_status(song)
        items.append({
            "kept": 1 if kept else 0,
            "source": song.get("source") or "search",
            "youtube_id": youtube_id,
            "title": song["title"],
            "channel": song.get("channel"),
            "artist": song.get("artist"),
            "album": song.get("album"),
            "track_number": song.get("track_number"),
            "duration_seconds": song.get("duration"),
            "sp_track_id": song.get("sp_track_id"),
            "sp_title": song.get("sp_title"),
            "sp_artist": song.get("sp_artist"),
            "sp_album": song.get("sp_album"),
            "sp_duration_seconds": song.get("sp_duration_seconds"),
            "in_library": in_library,
            "flags": suggestFlags.compute_flags(
                song["title"], song.get("channel"), song.get("duration"), artist=artist,
                requested_title=song.get("sp_title"), spotify_duration=song.get("sp_duration_seconds"),
                in_library=in_library, duplicate=duplicate,
            ),
        })

    submission_id = suggestionsRepo.create_submission(friend_id, message, items)
    return jsonify({"submission_id": submission_id, "kept": kept_count}), 201


@bp.route("/api/submissions")
def api_submissions():
    return jsonify({"submissions": suggestionsRepo.list_friend_submissions(g.friend["friend_id"])})
