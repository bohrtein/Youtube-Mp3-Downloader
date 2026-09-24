"""Reads Spotify playlists, albums and tracks from Spotify's public embed
pages (the player widget websites embed), which list each song's title,
artists and length without an account or API key.

This isn't an official API: the Web API now needs a Premium developer
account and only returns playlists the key's owner created. If Spotify
changes the embed page this stops working; everything else in the app is
unaffected. Embed pages list at most 100 songs of a playlist."""
import json
import re
import urllib.error
import urllib.request

EMBED_URL = "https://open.spotify.com/embed/{kind}/{spotify_id}"
EMBED_PAGE_TRACK_LIMIT = 100
REQUEST_TIMEOUT_SECONDS = 15
MAX_PAGE_BYTES = 5 * 1024 * 1024
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class SpotifyError(RuntimeError):
    """Message is safe to show a friend."""


def _fetch_entity(kind, spotify_id):
    request = urllib.request.Request(
        EMBED_URL.format(kind=kind, spotify_id=spotify_id), headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            html = response.read(MAX_PAGE_BYTES).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SpotifyError("Couldn't open that Spotify link (private or deleted?).") from e
        raise SpotifyError("Spotify didn't answer. Try again later, or paste YouTube links.") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SpotifyError("Couldn't reach Spotify. Try again later.") from e
    return parse_entity(html)


def parse_entity(html):
    """The playlist/album/track described by an embed page, or SpotifyError."""
    match = _NEXT_DATA_RE.search(html)
    try:
        entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
    except (AttributeError, KeyError, TypeError, ValueError):
        entity = None
    if not isinstance(entity, dict) or not entity.get("type"):
        # A missing or private playlist still answers 200, just without an entity.
        raise SpotifyError("Couldn't open that Spotify link (private or deleted?).")
    return entity


def _duration_seconds(milliseconds):
    return round((milliseconds or 0) / 1000) or None


def _track_id(uri):
    return (uri or "").rsplit(":", 1)[-1] or None


def _list_tracks(entity, album_name, limit):
    tracks = []
    for raw in entity.get("trackList") or []:
        if raw.get("entityType", "track") != "track" or not raw.get("title"):
            continue
        tracks.append({
            "sp_track_id": _track_id(raw.get("uri")),
            "sp_title": raw["title"],
            "sp_artist": raw.get("subtitle") or "",
            "sp_album": album_name,
            "sp_duration_seconds": _duration_seconds(raw.get("duration")),
        })
    return tracks[:limit]


def playlist_tracks(playlist_id, limit):
    """
    Returns:
        (list[dict], bool): up to `limit` tracks, and whether the list may be
        cut short (the embed page never shows more than 100 songs).
    """
    entity = _fetch_entity("playlist", playlist_id)
    raw_count = len(entity.get("trackList") or [])
    tracks = _list_tracks(entity, None, limit)
    return tracks, raw_count >= EMBED_PAGE_TRACK_LIMIT or raw_count > limit


def album_tracks(album_id, limit):
    entity = _fetch_entity("album", album_id)
    raw_count = len(entity.get("trackList") or [])
    return _list_tracks(entity, entity.get("name"), limit), raw_count > limit


def single_track(track_id):
    entity = _fetch_entity("track", track_id)
    if entity.get("type") != "track" or not entity.get("name"):
        raise SpotifyError("Couldn't open that Spotify link (private or deleted?).")
    artists = [a.get("name") for a in entity.get("artists") or [] if a.get("name")]
    return [{
        "sp_track_id": entity.get("id") or track_id,
        "sp_title": entity["name"],
        "sp_artist": ", ".join(artists),
        "sp_album": None,
        "sp_duration_seconds": _duration_seconds(entity.get("duration")),
    }], False
