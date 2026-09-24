import json
import re
import subprocess
from urllib.parse import quote_plus
from ytmusicapi import YTMusic
import core.interfaceComponents as interfaceComponents
import core.checkDependencies as checkDependencies

YTDLP_TIMEOUT_SECONDS = 60
# yt-dlp pages through a playlist 100 entries per request, so a big one
# needs far longer than a search.
PLAYLIST_TIMEOUT_SECONDS = 300
MAX_PLAYLIST_TRACKS = 5000
# Anything longer is a full album/concert upload, not a song.
MAX_SONG_SECONDS = 15 * 60

_RELEASE_PREFIX_RE = re.compile(r"^(album|ep|single)\s+-\s+", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")
_CHANNEL_ID_RE = re.compile(r"/channel/(UC[0-9A-Za-z_-]{22})")

_ytmusic_client = None


def _ytmusic():
    """One shared, signed-out YouTube Music client."""
    global _ytmusic_client
    if _ytmusic_client is None:
        _ytmusic_client = YTMusic()
    return _ytmusic_client


def _ytmusic_search(query, search_filter, limit):
    """YouTube Music search results of one type ("songs", "artists"), or [] on failure."""
    try:
        return _ytmusic().search(query, filter=search_filter, limit=limit)[:limit]
    except Exception as e:
        interfaceComponents.Print_Tag(f"YouTube Music search failed for '{query}': {e}", tag="Error")
        return []


def _run_flat_playlist_json(target, playlist_end=None, timeout=YTDLP_TIMEOUT_SECONDS):
    """
    Runs yt-dlp against a search expression or URL with --flat-playlist
    --dump-json and parses each output line as its own JSON object (yt-dlp
    prints one JSON object per entry, not a JSON array).

    Args:
        target (str): A yt-dlp search expression (e.g. "ytsearch5:...") or a URL.
        playlist_end (int | None): Stop after this many entries.
        timeout (int): Seconds before yt-dlp is killed.

    Returns:
        list[dict]: Parsed entries, or [] if yt-dlp fails or returns nothing.
    """
    cmd = [checkDependencies.resolve_ytdlp(), "--flat-playlist", "--dump-json", "--ignore-errors"]
    if playlist_end:
        cmd += ["--playlist-end", str(playlist_end)]
    # "--" stops option parsing, so a target starting with "-" can never be
    # read as a yt-dlp option.
    cmd += ["--", target]
    try:
        # No check=True: with --ignore-errors yt-dlp exits non-zero when any
        # single entry fails, even though the rest were printed fine.
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout)
    except Exception as e:
        interfaceComponents.Print_Tag(f"Search failed for '{target}': {e}", tag="Error")
        return []

    entries = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not entries and result.returncode != 0:
        interfaceComponents.Print_Tag(f"Search failed for '{target}': {result.stderr.strip()[-300:]}", tag="Error")
    return entries


def _normalize(text):
    return _NON_ALNUM_RE.sub("", (text or "").lower())


def _strip_release_prefix(title):
    """'Album - Mer De Noms' -> 'Mer De Noms' (YouTube's auto-generated album playlist titles)."""
    return _RELEASE_PREFIX_RE.sub("", title or "").strip()


def _entry_to_song(entry):
    """
    Maps a flat yt-dlp video entry to the song shape every caller uses, or
    None for entries that aren't single videos (channels, playlists).
    """
    video_id = entry.get("id") or ""
    # Flat playlist entries carry ie_key; a fully extracted video only extractor_key.
    if (entry.get("ie_key") or entry.get("extractor_key")) != "Youtube" or len(video_id) != 11:
        return None
    channel = entry.get("channel") or entry.get("uploader") or ""
    return {
        "youtube_id": video_id,
        "title": entry.get("title") or "",
        "channel": channel,
        "uploader": channel,
        "duration": entry.get("duration"),
        "url": entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
    }


def _ytmusic_song(result):
    """
    Maps a YouTube Music song result to the song shape every caller uses.
    Songs there are the artist's own audio uploads, so the credited artists
    stand in for the channel.
    """
    video_id = result.get("videoId") or ""
    if len(video_id) != 11:
        return None
    artists = ", ".join(a["name"] for a in result.get("artists") or [] if a.get("name"))
    return {
        "youtube_id": video_id,
        "title": result.get("title") or "",
        "channel": artists,
        "uploader": artists,
        "duration": result.get("duration_seconds"),
        "url": f"https://music.youtube.com/watch?v={video_id}",
    }


def search_songs(query, limit=20):
    """
    Searches YouTube Music's songs for a free-text query. Only songs, not
    videos, so every result is an official audio track.

    Args:
        query (str): e.g. "Artist Name Song Title".
        limit (int): Max number of results to request.

    Returns:
        list[dict]: [{youtube_id, title, channel, uploader, duration, url}, ...]
    """
    songs, seen = [], set()
    for result in _ytmusic_search(query, "songs", limit):
        song = _ytmusic_song(result)
        if song and song["youtube_id"] not in seen:
            seen.add(song["youtube_id"])
            songs.append(song)
    return songs


def get_video(video_id):
    """
    Full metadata for one video, including the music fields YouTube attaches
    to official uploads (artist, album, track number) when it has them.

    Returns:
        dict | None: search_songs() shape plus "artist", "album", "track_number".
    """
    entries = _run_flat_playlist_json(f"https://www.youtube.com/watch?v={video_id}")
    song = _entry_to_song(entries[0]) if entries else None
    if song:
        entry = entries[0]
        song["artist"] = entry.get("artist") or entry.get("creator") or None
        song["album"] = entry.get("album") or None
        song["track_number"] = entry.get("track_number")
    return song


def search_artist_songs(artist, limit=30):
    """
    An artist's top songs: a YouTube Music song search for the name, kept
    only where the artist is credited, minus full-album/concert uploads.

    Returns:
        list[dict]: Same shape as search_songs().
    """
    artist_key = _normalize(artist)
    if not artist_key:
        return []
    return [
        song for song in search_songs(artist, limit=limit)
        if artist_key in _normalize(song["channel"]) and (song["duration"] or 0) <= MAX_SONG_SECONDS
    ]


def list_playlist_tracks(url, limit=MAX_PLAYLIST_TRACKS):
    """
    Expands a playlist or album URL (YouTube, YouTube Music, or a YT Music
    /browse/ album link) into its individual tracks.

    Returns:
        list[dict]: search_songs() shape plus "album" and "track_number",
        both None unless the playlist is an auto-generated album
        ("OLAK5uy..." ID) - in any other playlist the position is just
        where someone put the song, not its number on its album.
    """
    entries = _run_flat_playlist_json(url, playlist_end=limit, timeout=PLAYLIST_TIMEOUT_SECONDS)
    tracks = []
    for entry in entries:
        song = _entry_to_song(entry)
        if not song:
            continue
        is_album = (entry.get("playlist_id") or "").startswith("OLAK5uy")
        song["album"] = _strip_release_prefix(entry.get("playlist_title")) if is_album else None
        song["track_number"] = entry.get("playlist_index") if is_album else None
        tracks.append(song)
    return tracks


def _search_ytmusic_albums(query, limit):
    """YT Music /browse/ URLs of the albums matching query, best match first."""
    entries = _run_flat_playlist_json(f"https://music.youtube.com/search?q={quote_plus(query)}#albums", playlist_end=limit)
    return [e["url"] for e in entries if e.get("url")]


def search_album_tracks(query):
    """
    Finds the best-matching album on YouTube Music and returns its tracks.

    Args:
        query (str): Album name, optionally with the artist ("Artist Album").

    Returns:
        list[dict]: list_playlist_tracks() shape, or [] if nothing matched.
    """
    album_urls = _search_ytmusic_albums(query, limit=1)
    return list_playlist_tracks(album_urls[0]) if album_urls else []


def search_album_candidates(artist, album, limit=3):
    """
    Searches YouTube Music for albums matching an artist + album. YT Music's
    flat album results carry only an ID, so each candidate is peeked at (one
    track) to learn its title, track count and canonical playlist URL.

    Args:
        artist (str): Artist name.
        album (str): Album name.
        limit (int): Max number of candidates to return.

    Returns:
        list[dict]: [{title, url, uploader, track_count}, ...]
    """
    candidates = []
    for browse_url in _search_ytmusic_albums(f"{artist} {album}", limit=limit):
        first = _run_flat_playlist_json(browse_url, playlist_end=1)
        if not first:
            continue
        entry = first[0]
        candidates.append({
            "title": _strip_release_prefix(entry.get("playlist_title")),
            "url": entry.get("playlist_webpage_url") or browse_url,
            "uploader": entry.get("channel") or entry.get("uploader") or "",
            "track_count": entry.get("playlist_count"),
        })
    return candidates


def discover_artist_channel(artist):
    """
    Finds the YouTube Music artist page whose name matches exactly.

    Args:
        artist (str): Artist name.

    Returns:
        str | None: The artist's channel URL, or None if nothing confidently matched.
    """
    artist_key = _normalize(artist)
    for result in _ytmusic_search(artist, "artists", 10):
        if artist_key and _normalize(result.get("artist")) == artist_key and result.get("browseId"):
            return f"https://music.youtube.com/channel/{result['browseId']}"
    return None


def list_artist_releases(channel_url):
    """
    Lists every album on a YouTube Music artist page.

    Args:
        channel_url (str): The artist's channel URL, from discover_artist_channel().

    Returns:
        list[dict]: [{title, url, track_count}, ...] (track_count is always
        None - the artist page doesn't say), or [] if the page couldn't be
        read - callers should ask the user for a direct URL rather than
        guessing further.
    """
    match = _CHANNEL_ID_RE.search(channel_url or "")
    if not match:
        return []
    try:
        shelf = _ytmusic().get_artist(match.group(1)).get("albums") or {}
        albums = shelf.get("results") or []
        # The page shows about ten; "params" means there are more behind "More".
        if shelf.get("params"):
            albums = _ytmusic().get_artist_albums(shelf["browseId"], shelf["params"])
    except Exception as e:
        interfaceComponents.Print_Tag(f"Couldn't read the YouTube Music artist page {channel_url}: {e}", tag="Error")
        return []
    releases = []
    for album in albums:
        # The artist page calls it audioPlaylistId, the full album list playlistId.
        playlist_id = album.get("audioPlaylistId") or album.get("playlistId")
        if playlist_id:
            releases.append({
                "title": album.get("title", ""),
                "url": f"https://music.youtube.com/playlist?list={playlist_id}",
                "track_count": None,
            })
    return releases
