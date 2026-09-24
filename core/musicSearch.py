import json
import re
import subprocess
from urllib.parse import quote_plus
import core.interfaceComponents as interfaceComponents
import core.checkDependencies as checkDependencies

YTDLP_TIMEOUT_SECONDS = 60
MAX_PLAYLIST_TRACKS = 200
# Anything longer is a full album/concert upload, not a song.
MAX_SONG_SECONDS = 15 * 60

_RELEASE_PREFIX_RE = re.compile(r"^(album|ep|single)\s+-\s+", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")


def _run_flat_playlist_json(target, playlist_end=None):
    """
    Runs yt-dlp against a search expression or URL with --flat-playlist
    --dump-json and parses each output line as its own JSON object (yt-dlp
    prints one JSON object per entry, not a JSON array).

    Args:
        target (str): A yt-dlp search expression (e.g. "ytsearch5:...") or a URL.
        playlist_end (int | None): Stop after this many entries.

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
                                errors="replace", timeout=YTDLP_TIMEOUT_SECONDS)
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


def _unique_songs(entries):
    songs, seen = [], set()
    for entry in entries:
        song = _entry_to_song(entry)
        if song and song["youtube_id"] not in seen:
            seen.add(song["youtube_id"])
            songs.append(song)
    return songs


def search_songs(query, limit=20):
    """
    Searches YouTube for individual songs matching a free-text query. Plain
    YouTube search is used over YouTube Music's because its flat results
    include channel and duration, which the YT Music song results lack.

    Args:
        query (str): e.g. "Artist Name Song Title".
        limit (int): Max number of results to request.

    Returns:
        list[dict]: [{youtube_id, title, channel, uploader, duration, url}, ...]
    """
    return _unique_songs(_run_flat_playlist_json(f"ytsearch{limit}:{query}"))


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
    An artist's top songs: a plain search for the name, kept only where the
    uploading channel is the artist's own ("A Perfect Circle",
    "Rammstein Official", "Artist - Topic"), minus full-album/concert uploads.

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
        list[dict]: search_songs() shape plus "track_number", and "album"
        when the playlist is an auto-generated album ("OLAK5uy..." ID).
    """
    entries = _run_flat_playlist_json(url, playlist_end=limit)
    tracks = []
    for entry in entries:
        song = _entry_to_song(entry)
        if not song:
            continue
        is_album = (entry.get("playlist_id") or "").startswith("OLAK5uy")
        song["album"] = _strip_release_prefix(entry.get("playlist_title")) if is_album else None
        song["track_number"] = entry.get("playlist_index")
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
    Finds the best-matching YouTube Music channel for an artist (usually the
    auto-generated "Artist - Topic" channel).

    Args:
        artist (str): Artist name.

    Returns:
        str | None: The channel/uploader URL, or None if nothing confidently matched.
    """
    entries = _run_flat_playlist_json(f"ytsearch10:{artist}")
    artist_lower = artist.strip().lower()
    for e in entries:
        uploader = (e.get("uploader") or e.get("channel") or "").strip().lower()
        if uploader == artist_lower or uploader == f"{artist_lower} - topic":
            channel_url = e.get("uploader_url") or e.get("channel_url")
            if channel_url:
                return channel_url
    return None


def list_artist_releases(channel_url):
    """
    Lists every album/playlist under an artist channel's "releases" tab,
    falling back to the "albums" tab if releases isn't available.

    Args:
        channel_url (str): The artist's channel URL, from discover_artist_channel().

    Returns:
        list[dict]: [{title, url, track_count}, ...], or [] if neither tab
        resolved - callers should ask the user for a direct URL rather than
        guessing further.
    """
    for tab in ("releases", "albums"):
        entries = _run_flat_playlist_json(f"{channel_url.rstrip('/')}/{tab}")
        if entries:
            return [
                {
                    "title": e.get("title", ""),
                    "url": e.get("url") or e.get("webpage_url", ""),
                    "track_count": e.get("playlist_count") or e.get("n_entries"),
                }
                for e in entries
            ]
    return []
