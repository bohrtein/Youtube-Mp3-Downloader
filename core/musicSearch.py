import json
import subprocess
import core.interfaceComponents as interfaceComponents

# Same binary playlistDownloader.py already shells out to. Callers should run
# checkDependencies.dependencies_check() first to make sure it's present.
YTDLP_BIN = "./yt-dlp.exe"


def _run_flat_playlist_json(target):
    """
    Runs yt-dlp against a search query or URL with --flat-playlist --dump-json
    and parses each output line as its own JSON object (yt-dlp prints one
    JSON object per entry, not a JSON array).

    Args:
        target (str): A yt-dlp search expression (e.g. "ytmsearch5:...") or a URL.

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


def search_songs(query, limit=10):
    """
    Searches YouTube Music for individual songs matching a free-text query.

    Args:
        query (str): e.g. "Artist Name Song Title".
        limit (int): Max number of results to request.

    Returns:
        list[dict]: [{title, url, uploader, duration}, ...]
    """
    entries = _run_flat_playlist_json(f"ytmsearch{limit}:{query}")
    return [
        {
            "title": e.get("title", ""),
            "url": e.get("url") or e.get("webpage_url", ""),
            "uploader": e.get("uploader", ""),
            "duration": e.get("duration"),
        }
        for e in entries
    ]


def search_album_candidates(artist, album, limit=8):
    """
    Searches YouTube Music for album/playlist results matching an artist + album.

    Args:
        artist (str): Artist name.
        album (str): Album name.
        limit (int): Max number of results to request.

    Returns:
        list[dict]: [{title, url, uploader, track_count}, ...] - only entries
        that look like playlists (albums), not standalone songs.
    """
    query = f"{artist} {album}"
    entries = _run_flat_playlist_json(f"ytmsearch{limit}:{query}")
    candidates = []
    for e in entries:
        url = e.get("url") or e.get("webpage_url", "")
        if "list=" not in url and e.get("_type") != "playlist":
            continue
        candidates.append({
            "title": e.get("title", ""),
            "url": url,
            "uploader": e.get("uploader", ""),
            "track_count": e.get("playlist_count") or e.get("n_entries"),
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
    entries = _run_flat_playlist_json(f"ytmsearch10:{artist}")
    artist_lower = artist.strip().lower()
    for e in entries:
        uploader = (e.get("uploader") or "").strip().lower()
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
