"""SQL for the Friend Suggestions feature: friends, submissions, the lookup
cache and rate-limit events. Every function opens and closes its own
connection, so it's safe to call from request threads and background jobs."""
import json
import secrets
import threading
import time
from contextlib import contextmanager
import database.databaseConnector as databaseConnector
import core.songMatch as songMatch

TOKEN_BYTES = 24


@contextmanager
def _db():
    conn = databaseConnector.connect_to_db()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _rows(cursor):
    return [dict(row) for row in cursor.fetchall()]


# --- settings -------------------------------------------------------------

def suggestions_enabled():
    with _db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'suggestions_enabled'").fetchone()
    return row is None or row["value"] != "0"


def set_suggestions_enabled(enabled):
    with _db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('suggestions_enabled', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("1" if enabled else "0",),
        )


# --- friends --------------------------------------------------------------

def create_friend(name):
    token = secrets.token_urlsafe(TOKEN_BYTES)
    with _db() as conn:
        cursor = conn.execute("INSERT INTO friends (name, token) VALUES (?, ?)", (name, token))
        return {"friend_id": cursor.lastrowid, "name": name, "token": token}


def list_friends():
    with _db() as conn:
        return _rows(conn.execute("""
            SELECT f.*,
                   (SELECT COUNT(*) FROM submissions s
                     WHERE s.friend_id = f.friend_id AND s.status IN ('pending', 'in_review')) AS open_submissions,
                   (SELECT COUNT(*) FROM submissions s WHERE s.friend_id = f.friend_id) AS total_submissions
            FROM friends f
            ORDER BY f.revoked_at IS NOT NULL, f.name COLLATE NOCASE
        """))


def get_active_friend_by_token(token):
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM friends WHERE token = ? AND revoked_at IS NULL", (token,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE friends SET last_seen_at = datetime('now') WHERE friend_id = ?", (row["friend_id"],))
        return dict(row)


def revoke_friend(friend_id):
    with _db() as conn:
        conn.execute(
            "UPDATE friends SET revoked_at = datetime('now') WHERE friend_id = ? AND revoked_at IS NULL",
            (friend_id,),
        )


def rotate_friend_token(friend_id):
    """New link for the same friend (old link stops working); also un-revokes."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    with _db() as conn:
        conn.execute("UPDATE friends SET token = ?, revoked_at = NULL WHERE friend_id = ?", (token, friend_id))
    return token


# --- lookup cache ---------------------------------------------------------

def cache_get(key, max_age_seconds):
    with _db() as conn:
        row = conn.execute("SELECT payload, fetched_at FROM lookup_cache WHERE cache_key = ?", (key,)).fetchone()
    if row is None or time.time() - row["fetched_at"] > max_age_seconds:
        return None
    return json.loads(row["payload"])


def cache_set(key, payload):
    with _db() as conn:
        conn.execute(
            "INSERT INTO lookup_cache (cache_key, payload, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at",
            (key, json.dumps(payload), time.time()),
        )


def cache_set_many(pairs):
    now = time.time()
    with _db() as conn:
        conn.executemany(
            "INSERT INTO lookup_cache (cache_key, payload, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload, fetched_at = excluded.fetched_at",
            [(key, json.dumps(payload), now) for key, payload in pairs],
        )


def cache_prune(max_age_seconds):
    with _db() as conn:
        conn.execute("DELETE FROM lookup_cache WHERE fetched_at < ?", (time.time() - max_age_seconds,))


# --- rate-limit events ----------------------------------------------------

_usage_lock = threading.Lock()


def try_consume(friend_id, kind, limits, cost=1):
    """
    Records `cost` events of `kind` if doing so keeps every (window_seconds,
    max_events) limit; otherwise records nothing.

    Returns:
        int: 0 if allowed, else seconds until the tightest limit frees up.
    """
    now = time.time()
    friend_clause = "friend_id IS ?" if friend_id is None else "friend_id = ?"
    with _usage_lock, _db() as conn:
        longest = max(window for window, _ in limits)
        conn.execute("DELETE FROM usage_events WHERE at < ?", (now - max(longest, 86400),))
        retry_after = 0
        for window, max_events in limits:
            rows = conn.execute(
                f"SELECT at FROM usage_events WHERE kind = ? AND {friend_clause} AND at >= ? ORDER BY at",
                (kind, friend_id, now - window),
            ).fetchall()
            if len(rows) + cost > max_events:
                # The oldest events that must age out before cost more fit.
                overflow = len(rows) + cost - max_events
                oldest_needed = rows[min(overflow, len(rows)) - 1]["at"] if rows else now
                retry_after = max(retry_after, int(oldest_needed + window - now) + 1)
        if retry_after:
            return retry_after
        conn.executemany(
            "INSERT INTO usage_events (friend_id, kind, at) VALUES (?, ?, ?)",
            [(friend_id, kind, now)] * cost,
        )
        return 0


# --- library lookups ------------------------------------------------------

_library_index = {"built": 0.0, "ids": set(), "titles": {}}
_library_index_lock = threading.Lock()
LIBRARY_INDEX_TTL_SECONDS = 60


def _library_index_snapshot():
    with _library_index_lock:
        if time.time() - _library_index["built"] > LIBRARY_INDEX_TTL_SECONDS:
            ids, titles = set(), {}
            with _db() as conn:
                for row in conn.execute("""
                    SELECT s.song_title, s.youtube_id, art.artist_name
                    FROM songs s
                    JOIN albums alb ON s.album_id = alb.album_id
                    JOIN artists art ON alb.artist_id = art.artist_id
                """):
                    if row["youtube_id"]:
                        ids.add(row["youtube_id"])
                    key = songMatch.normalize_title(row["song_title"], row["artist_name"])
                    if key:
                        titles.setdefault(key, set()).add(songMatch.normalize_artist(row["artist_name"]))
            _library_index.update(built=time.time(), ids=ids, titles=titles)
        return _library_index["ids"], _library_index["titles"]


def invalidate_library_index():
    with _library_index_lock:
        _library_index["built"] = 0.0


def library_status(song):
    """
    'yes' if this exact video is in the library, 'maybe' if a song with the
    same (normalized) title by the same artist is, else 'no'. The same
    song usually has several uploads, so an ID-only check misses a lot.
    """
    ids, titles = _library_index_snapshot()
    if song.get("youtube_id") in ids:
        return "yes"
    artist = song.get("artist") or song.get("channel")
    if not artist:
        return "no"
    title_key = songMatch.normalize_title(song.get("title"), artist)
    artist_key = songMatch.normalize_artist(artist)
    for library_artist in titles.get(title_key, ()):
        if library_artist and artist_key and (library_artist in artist_key or artist_key in library_artist):
            return "maybe"
    return "no"


def public_library():
    """Albums with their tracks for the friends' read-only library view -
    names and durations only: no file paths, IDs or source links."""
    with _db() as conn:
        albums = _rows(conn.execute("SELECT album_id, album_name, artist_name, release_date FROM album_gallery"))
        songs = conn.execute(
            "SELECT album_id, song_title, track_number, duration_seconds FROM songs ORDER BY album_id, track_number"
        ).fetchall()
    by_album = {}
    for song in songs:
        by_album.setdefault(song["album_id"], []).append({
            "title": song["song_title"],
            "track_number": song["track_number"],
            "duration": song["duration_seconds"],
        })
    for album in albums:
        album["songs"] = by_album.get(album["album_id"], [])
    return albums


# --- submissions ----------------------------------------------------------

ITEM_FIELDS = (
    "kept", "source", "youtube_id", "title", "channel", "artist", "album", "track_number",
    "duration_seconds", "sp_track_id", "sp_title", "sp_artist", "sp_album", "sp_duration_seconds",
    "flags", "in_library",
)


def count_open_submissions(friend_id):
    with _db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM submissions WHERE friend_id = ? AND status IN ('pending', 'in_review')",
            (friend_id,),
        ).fetchone()[0]


def create_submission(friend_id, message, items):
    """items: dicts with ITEM_FIELDS keys (flags as a list)."""
    with _db() as conn:
        cursor = conn.execute("INSERT INTO submissions (friend_id, message) VALUES (?, ?)", (friend_id, message))
        submission_id = cursor.lastrowid
        placeholders = ", ".join("?" for _ in ITEM_FIELDS)
        conn.executemany(
            f"INSERT INTO submission_items (submission_id, position, {', '.join(ITEM_FIELDS)}) "
            f"VALUES (?, ?, {placeholders})",
            [
                (submission_id, position, *[
                    json.dumps(item.get(field) or []) if field == "flags" else item.get(field)
                    for field in ITEM_FIELDS
                ])
                for position, item in enumerate(items)
            ],
        )
        return submission_id


def _decode_item(row):
    item = dict(row)
    item["flags"] = json.loads(item["flags"] or "[]")
    return item


def list_submissions(statuses=None):
    query = """
        SELECT s.*, f.name AS friend_name, f.revoked_at AS friend_revoked_at,
               SUM(i.kept = 1) AS kept_count, SUM(i.kept = 0) AS unticked_count,
               SUM(i.decision = 'downloaded') AS downloaded_count,
               SUM(i.kept = 1 AND i.flags != '[]') AS flagged_count
        FROM submissions s
        JOIN friends f ON f.friend_id = s.friend_id
        LEFT JOIN submission_items i ON i.submission_id = s.submission_id
    """
    params = []
    if statuses:
        query += f" WHERE s.status IN ({', '.join('?' for _ in statuses)})"
        params = list(statuses)
    query += " GROUP BY s.submission_id ORDER BY s.created_at DESC, s.submission_id DESC"
    with _db() as conn:
        return _rows(conn.execute(query, params))


def list_friend_submissions(friend_id, limit=20):
    """What a friend may see about their own submissions: counts and status only."""
    with _db() as conn:
        return _rows(conn.execute("""
            SELECT s.submission_id, s.status, s.created_at,
                   SUM(i.kept = 1) AS kept_count,
                   SUM(i.decision = 'downloaded') AS downloaded_count
            FROM submissions s
            LEFT JOIN submission_items i ON i.submission_id = s.submission_id
            WHERE s.friend_id = ?
            GROUP BY s.submission_id
            ORDER BY s.created_at DESC, s.submission_id DESC
            LIMIT ?
        """, (friend_id, limit)))


def get_submission(submission_id):
    with _db() as conn:
        row = conn.execute("""
            SELECT s.*, f.name AS friend_name FROM submissions s
            JOIN friends f ON f.friend_id = s.friend_id
            WHERE s.submission_id = ?
        """, (submission_id,)).fetchone()
        if row is None:
            return None
        submission = dict(row)
        submission["items"] = [
            _decode_item(r) for r in conn.execute(
                "SELECT * FROM submission_items WHERE submission_id = ? ORDER BY position", (submission_id,)
            ).fetchall()
        ]
    return submission


def get_item(item_id):
    with _db() as conn:
        row = conn.execute("SELECT * FROM submission_items WHERE item_id = ?", (item_id,)).fetchone()
    return _decode_item(row) if row else None


def update_item_match(item_id, song, flags, in_library):
    """Replaces an item's matched video, remembering the original once."""
    with _db() as conn:
        conn.execute("""
            UPDATE submission_items
            SET orig_youtube_id = COALESCE(orig_youtube_id, youtube_id),
                youtube_id = ?, title = ?, channel = ?, artist = ?, album = ?, track_number = ?,
                duration_seconds = ?, flags = ?, in_library = ?, error = NULL,
                decision = CASE WHEN decision IN ('downloaded', 'downloading') THEN decision ELSE 'pending' END
            WHERE item_id = ?
        """, (song["youtube_id"], song["title"], song.get("channel"), song.get("artist"), song.get("album"),
              song.get("track_number"), song.get("duration"), json.dumps(flags), in_library, item_id))


def set_item_decision(item_id, decision, error=None):
    with _db() as conn:
        conn.execute("UPDATE submission_items SET decision = ?, error = ? WHERE item_id = ?", (decision, error, item_id))


def set_submission_status(submission_id, status):
    with _db() as conn:
        conn.execute(
            "UPDATE submissions SET status = ?, "
            "reviewed_at = CASE WHEN ? IN ('done', 'rejected') THEN datetime('now') ELSE reviewed_at END "
            "WHERE submission_id = ?",
            (status, status, submission_id),
        )


def count_pending_submissions():
    with _db() as conn:
        return conn.execute("SELECT COUNT(*) FROM submissions WHERE status IN ('pending', 'in_review')").fetchone()[0]
