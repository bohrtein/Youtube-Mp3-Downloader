"""Reads public Spotify playlists/albums/tracks with the Client Credentials
flow: server-side only, friends never sign in to Spotify. Credentials come
from SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in the environment (on the
server: the [env] table of this app's app.toml in the app hub)."""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
REQUEST_TIMEOUT_SECONDS = 15
MAX_RETRY_AFTER_SECONDS = 10

_token = {"value": None, "expires_at": 0.0}
_token_lock = threading.Lock()


class SpotifyError(RuntimeError):
    """Message is safe to show a friend."""


def configured():
    return bool(os.environ.get("SPOTIFY_CLIENT_ID") and os.environ.get("SPOTIFY_CLIENT_SECRET"))


def _access_token():
    with _token_lock:
        if _token["value"] and time.time() < _token["expires_at"] - 60:
            return _token["value"]
        credentials = f"{os.environ['SPOTIFY_CLIENT_ID']}:{os.environ['SPOTIFY_CLIENT_SECRET']}"
        request = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={
                "Authorization": "Basic " + base64.b64encode(credentials.encode()).decode(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as e:
            raise SpotifyError("Spotify links aren't working right now.") from e
        _token.update(value=payload["access_token"], expires_at=time.time() + int(payload.get("expires_in", 3600)))
        return _token["value"]


def _api_get(path_or_url, params=None, _retried=False):
    url = path_or_url if path_or_url.startswith("https://") else API_URL + path_or_url
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {_access_token()}"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        if e.code == 429 and not _retried:
            wait = int(e.headers.get("Retry-After", "1") or 1)
            if wait <= MAX_RETRY_AFTER_SECONDS:
                time.sleep(wait)
                return _api_get(path_or_url, params, _retried=True)
            raise SpotifyError("Spotify is rate-limiting this server. Try again later.") from e
        if e.code == 401 and not _retried:
            with _token_lock:
                _token["value"] = None
            return _api_get(path_or_url, params, _retried=True)
        if e.code in (403, 404):
            raise SpotifyError(
                "Spotify won't share that one (private, or made by Spotify itself). "
                "Paste YouTube links instead."
            ) from e
        raise SpotifyError("Spotify returned an error. Try again later.") from e
    except urllib.error.URLError as e:
        raise SpotifyError("Couldn't reach Spotify. Try again later.") from e


def _track(raw, album_name=None):
    """Spotify track JSON -> {sp_track_id, sp_title, sp_artist, sp_album, sp_duration_seconds}."""
    if not raw or raw.get("type", "track") != "track" or not raw.get("name"):
        return None
    artists = [a.get("name") for a in raw.get("artists") or [] if a.get("name")]
    return {
        "sp_track_id": raw.get("id"),
        "sp_title": raw["name"],
        "sp_artist": ", ".join(artists[:1]) if artists else "",
        "sp_album": album_name or (raw.get("album") or {}).get("name"),
        "sp_duration_seconds": round((raw.get("duration_ms") or 0) / 1000) or None,
    }


def playlist_tracks(playlist_id, limit):
    """
    Up to `limit` tracks of a public, user-made playlist. Episodes and local
    files are skipped.

    Returns:
        (list[dict], bool): tracks, and whether the playlist had more than limit.
    """
    tracks, truncated = [], False
    page = _api_get(f"/playlists/{playlist_id}/tracks", {"limit": 100})
    while page:
        for entry in page.get("items") or []:
            track = _track(entry.get("track") or entry.get("item"))
            if track:
                if len(tracks) >= limit:
                    return tracks, True
                tracks.append(track)
        page = _api_get(page["next"]) if page.get("next") else None
    return tracks, truncated


def album_tracks(album_id, limit):
    album = _api_get(f"/albums/{album_id}")
    name = album.get("name")
    tracks, page = [], album.get("tracks")
    while page:
        for raw in page.get("items") or []:
            track = _track(raw, album_name=name)
            if track:
                if len(tracks) >= limit:
                    return tracks, True
                tracks.append(track)
        page = _api_get(page["next"]) if page.get("next") else None
    return tracks, False


def single_track(track_id):
    track = _track(_api_get(f"/tracks/{track_id}"))
    return ([track] if track else []), False
