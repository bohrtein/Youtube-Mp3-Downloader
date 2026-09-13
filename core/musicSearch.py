import difflib
import json
import re
import subprocess
import urllib.parse
import core.interfaceComponents as interfaceComponents

# Same binary playlistDownloader.py already shells out to. Callers should run
# checkDependencies.dependencies_check() first to make sure it's present.
YTDLP_BIN = "./yt-dlp.exe"

# Deliberately music.youtube.com, not a plain "ytsearchN:" against regular
# YouTube: a generic YouTube search (or an artist's regular/merged channel
# "releases" tab) ranks/includes whatever the label uploaded for a track -
# which for many singles is the "Official Music Video", not the plain audio
# track. YouTube Music's own search and album/browse catalog consistently
# resolve to the plain-audio version that YouTube Music itself plays.
_MUSIC_SEARCH_URL = "https://music.youtube.com/search?q={query}"
_MUSIC_BROWSE_URL = "https://music.youtube.com/browse/{browse_id}"


def _run_flat_playlist_json(target):
    """
    Runs yt-dlp against a search query or URL with --flat-playlist --dump-json
    and parses each output line as its own JSON object (yt-dlp prints one
    JSON object per entry, not a JSON array).

    Args:
        target (str): A yt-dlp search expression (e.g. "ytsearch5:...") or a URL.

    Returns:
        list[dict]: Parsed entries, or [] if yt-dlp fails or returns nothing.
    """
    cmd = [YTDLP_BIN, "--flat-playlist", "--dump-json", "--ignore-errors", target]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except Exception as e:
        interfaceComponents.Print_Tag(f"Search failed for '{target}': {e}", tag="Error")
        return []

    entries = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _music_search(query):
    """Runs a search against YouTube Music's own catalog (not plain YouTube)."""
    return _run_flat_playlist_json(_MUSIC_SEARCH_URL.format(query=urllib.parse.quote(query)))


def search_songs(query, limit=10):
    """
    Searches YouTube Music for individual songs matching a free-text query.

    Args:
        query (str): e.g. "Artist Name Song Title".
        limit (int): Max number of results to return.

    Returns:
        list[dict]: [{title, url, uploader, duration}, ...] - the plain-audio
        track entries YouTube Music's own search returns, not the "browse"
        (album/artist) entries mixed into the same results.
    """
    entries = [e for e in _music_search(query) if e.get("ie_key") == "Youtube"]
    return [
        {
            "title": e.get("title", ""),
            "url": e.get("url") or e.get("webpage_url", ""),
            "uploader": e.get("channel") or e.get("uploader", ""),
            "duration": e.get("duration"),
        }
        for e in entries[:limit]
    ]


def _resolve_release(browse_id):
    """
    Resolves a YouTube Music album "browse" search result to its canonical
    playlist: title, canonical URL, uploader and track count. This is the
    same auto-generated playlist YouTube Music itself plays an album from
    (plain audio throughout), as opposed to an artist channel's "releases"
    tab which mixes in official music videos wherever the label uploaded one.

    Args:
        browse_id (str): A YouTube Music album id (starts with "MPREb_"),
            from a search result's "id" field.

    Returns:
        dict | None: {title, url, uploader, track_count}, or None if the
        browse page didn't resolve to any tracks.
    """
    entries = _run_flat_playlist_json(_MUSIC_BROWSE_URL.format(browse_id=browse_id))
    if not entries:
        return None
    first = entries[0]
    return {
        "title": first.get("playlist_title") or first.get("playlist") or "",
        "url": first.get("playlist_webpage_url") or _MUSIC_BROWSE_URL.format(browse_id=browse_id),
        "uploader": first.get("channel") or first.get("uploader") or "",
        "track_count": first.get("playlist_count") or len(entries),
    }


_ALBUM_PREFIX_RE = re.compile(r"^album\s*-\s*", re.IGNORECASE)


def _title_similarity(title, hint):
    """Fuzzy-matches a resolved release title against a requested album name."""
    a = _ALBUM_PREFIX_RE.sub("", title).strip().lower()
    b = hint.strip().lower()
    return difflib.SequenceMatcher(None, a, b).ratio()


def _album_browse_candidates(query, artist=None, title_hint=None, limit=8):
    """
    Searches YouTube Music for album results and resolves each to its
    canonical playlist, deduping by browse id and optionally filtering to a
    matching artist/uploader and/or a requested album title.

    Args:
        query (str): Search text (artist name, or "artist album").
        artist (str | None): If given, only keep releases whose resolved
            uploader/channel contains this artist name.
        title_hint (str | None): If given, only keep releases whose resolved
            title is a reasonably close match (e.g. searching for one
            specific album shouldn't silently return an unrelated one just
            because it ranked higher in YouTube Music's search).
        limit (int): Max number of resolved candidates to return.

    Returns:
        list[dict]: [{title, url, uploader, track_count}, ...]
    """
    entries = _music_search(query)
    seen_ids = set()
    candidates = []
    artist_lower = artist.strip().lower() if artist else None
    for e in entries:
        if e.get("ie_key") != "YoutubeTab":
            continue
        browse_id = e.get("id") or ""
        if not browse_id.startswith("MPREb_") or browse_id in seen_ids:
            continue
        seen_ids.add(browse_id)

        resolved = _resolve_release(browse_id)
        if not resolved or not resolved["title"]:
            continue
        if artist_lower and artist_lower not in (resolved["uploader"] or "").strip().lower():
            continue
        if title_hint and _title_similarity(resolved["title"], title_hint) < 0.6:
            continue

        candidates.append(resolved)
        if len(candidates) >= limit:
            break
    return candidates


def search_album_candidates(artist, album, limit=8):
    """
    Searches YouTube Music for album results matching an artist + album.

    Args:
        artist (str): Artist name.
        album (str): Album name.
        limit (int): Max number of candidates to return.

    Returns:
        list[dict]: [{title, url, uploader, track_count}, ...]
    """
    return _album_browse_candidates(f"{artist} {album}", artist=artist, title_hint=album, limit=limit)


def list_artist_releases(artist, limit=30):
    """
    Lists an artist's releases straight from YouTube Music's own catalog.

    Args:
        artist (str): Artist name.
        limit (int): Max number of releases to return.

    Returns:
        list[dict]: [{title, url, track_count}, ...], or [] if nothing
        confidently matched the artist - callers should ask the user for a
        direct URL rather than guessing further.
    """
    releases = _album_browse_candidates(artist, artist=artist, limit=limit)
    return [{"title": r["title"], "url": r["url"], "track_count": r["track_count"]} for r in releases]
