"""My side of Friend Suggestions: friend links, the review queue, fixing
matches and approving downloads. Admin-only - app.py's hub-login guard
404s every route here for requests that didn't pass the app hub login."""
import threading

from flask import Blueprint, abort, current_app, jsonify, render_template, request, url_for

import core.approvedDownloads as approvedDownloads
import core.linkResolver as linkResolver
import core.musicSearch as musicSearch
import core.suggestFlags as suggestFlags
import database.databaseConnector as databaseConnector
import database.suggestionsRepo as suggestionsRepo

bp = Blueprint("suggest_admin", __name__)

MAX_FRIEND_NAME_LENGTH = 60
PUBLIC_BASE_URL_KEY = "public_base_url"


def _json_body():
    # JSON-only POSTs: a cross-site <form> can't send application/json.
    if not request.is_json:
        abort(415)
    return request.get_json(silent=True) or {}


def _get_setting(key, default=""):
    conn = databaseConnector.connect_to_db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row["value"] if row and row["value"] else default


def _set_setting(key, value):
    conn = databaseConnector.connect_to_db()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def friend_link(token):
    """The link to hand a friend: the public (Tailscale Funnel) origin plus
    this app's own prefixed path, e.g. https://box.tailnet.ts.net:8443/app/<slug>/suggest/<token>/."""
    return _get_setting(PUBLIC_BASE_URL_KEY).rstrip("/") + url_for("friends_public.home", token=token)


# --- friends ---------------------------------------------------------------------

@bp.route("/friends")
def friends_page():
    friends = suggestionsRepo.list_friends()
    for friend in friends:
        friend["link"] = friend_link(friend["token"])
    return render_template(
        "friends.html",
        friends=friends,
        public_base_url=_get_setting(PUBLIC_BASE_URL_KEY),
        suggestions_enabled=suggestionsRepo.suggestions_enabled(),
    )


@bp.route("/friends", methods=["POST"])
def create_friend():
    name = str(_json_body().get("name", "")).strip()[:MAX_FRIEND_NAME_LENGTH]
    if not name:
        return jsonify({"error": "Give the friend a name."}), 400
    friend = suggestionsRepo.create_friend(name)
    return jsonify({"friend_id": friend["friend_id"], "link": friend_link(friend["token"])}), 201


@bp.route("/friends/<int:friend_id>/revoke", methods=["POST"])
def revoke_friend(friend_id):
    _json_body()
    suggestionsRepo.revoke_friend(friend_id)
    return jsonify({"ok": True})


@bp.route("/friends/<int:friend_id>/rotate", methods=["POST"])
def rotate_friend(friend_id):
    _json_body()
    token = suggestionsRepo.rotate_friend_token(friend_id)
    return jsonify({"link": friend_link(token)})


@bp.route("/settings/suggestions", methods=["POST"])
def suggestion_settings():
    data = _json_body()
    if "enabled" in data:
        suggestionsRepo.set_suggestions_enabled(bool(data["enabled"]))
    if "public_base_url" in data:
        base = str(data["public_base_url"]).strip().rstrip("/")
        if base and not base.startswith(("https://", "http://")):
            return jsonify({"error": "The public address must start with https://"}), 400
        _set_setting(PUBLIC_BASE_URL_KEY, base)
    return jsonify({"ok": True})


# --- review ------------------------------------------------------------------------

@bp.route("/review")
def review_list():
    return render_template(
        "review.html",
        open_submissions=suggestionsRepo.list_submissions(["pending", "in_review"]),
        closed_submissions=suggestionsRepo.list_submissions(["done", "rejected"])[:30],
    )


@bp.route("/review/<int:submission_id>")
def review_detail(submission_id):
    submission = suggestionsRepo.get_submission(submission_id)
    if submission is None:
        abort(404)
    return render_template(
        "review_detail.html",
        submission=submission,
        kept=[i for i in submission["items"] if i["kept"]],
        unticked=[i for i in submission["items"] if not i["kept"]],
        flag_labels=suggestFlags.FLAG_LABELS,
    )


def _item_or_404(item_id):
    item = suggestionsRepo.get_item(item_id)
    if item is None:
        abort(404)
    return item


@bp.route("/review/items/<int:item_id>/candidates")
def match_candidates(item_id):
    item = _item_or_404(item_id)
    artist = item["sp_artist"] or item["artist"] or ""
    title = item["sp_title"] or item["title"]
    query = f"{artist} - {title}" if artist else title
    candidates = musicSearch.search_songs(query, limit=6)
    return jsonify({"query": query, "candidates": [c for c in candidates if c["youtube_id"] != item["youtube_id"]][:5]})


@bp.route("/review/items/<int:item_id>/match", methods=["POST"])
def fix_match(item_id):
    item = _item_or_404(item_id)
    if item["decision"] == "downloading":
        return jsonify({"error": "That song is downloading right now."}), 409
    value = str(_json_body().get("video", "")).strip()
    video_id = value if linkResolver.is_video_id(value) else linkResolver.extract_video_id(value)
    if not video_id:
        return jsonify({"error": "Paste a YouTube video link or ID."}), 400
    song = musicSearch.get_video(video_id)
    if song is None:
        return jsonify({"error": "Couldn't open that video."}), 400
    # Keep what the friend asked for (album/track from an album list) unless
    # the new video brings its own.
    song["album"] = song.get("album") or item["album"]
    song["track_number"] = song.get("track_number") or item["track_number"]
    song["artist"] = song.get("artist") or item["artist"]
    in_library = suggestionsRepo.library_status(song)
    flags = suggestFlags.compute_flags(
        song["title"], song.get("channel"), song.get("duration"), artist=item["sp_artist"] or song.get("artist"),
        requested_title=item["sp_title"], spotify_duration=item["sp_duration_seconds"], in_library=in_library,
    )
    suggestionsRepo.update_item_match(item_id, song, flags, in_library)
    return jsonify({"ok": True})


@bp.route("/review/<int:submission_id>/approve", methods=["POST"])
def approve(submission_id):
    submission = suggestionsRepo.get_submission(submission_id)
    if submission is None:
        abort(404)
    data = _json_body()
    audio_format = "mp3" if data.get("format") == "mp3" else "flac"
    wanted = {int(i) for i in data.get("item_ids", []) if str(i).isdigit()}
    items = {i["item_id"]: i for i in submission["items"]}
    selected = [i for i in wanted if i in items and items[i]["decision"] in ("pending", "skipped", "failed", "downloaded")]
    if not selected:
        return jsonify({"error": "Select at least one song."}), 400
    # Songs I already downloaded once may replace their own library file.
    redownload_ids = {i for i in selected if items[i]["decision"] == "downloaded"}
    if approvedDownloads.download_lock.locked():
        return jsonify({"error": "A download is already running. Wait for it to finish."}), 409

    for item_id in selected:
        suggestionsRepo.set_item_decision(item_id, "downloading")
    # Approving is the decision for the whole submission: the rest is skipped.
    for item in submission["items"]:
        if item["item_id"] not in selected and item["decision"] == "pending":
            suggestionsRepo.set_item_decision(item["item_id"], "skipped")
    suggestionsRepo.set_submission_status(submission_id, "in_review")

    socketio = current_app.extensions["socketio"]

    def progress(percent, status):
        socketio.emit("progress", {"percent": percent, "status": status})

    threading.Thread(
        target=approvedDownloads.run_approval,
        args=(submission_id, selected, audio_format, progress, redownload_ids),
        daemon=True,
    ).start()
    return jsonify({"ok": True, "count": len(selected)}), 202


@bp.route("/review/<int:submission_id>/reject", methods=["POST"])
def reject(submission_id):
    _json_body()
    submission = suggestionsRepo.get_submission(submission_id)
    if submission is None:
        abort(404)
    for item in submission["items"]:
        if item["decision"] == "pending":
            suggestionsRepo.set_item_decision(item["item_id"], "skipped")
    suggestionsRepo.set_submission_status(submission_id, "rejected")
    return jsonify({"ok": True})
