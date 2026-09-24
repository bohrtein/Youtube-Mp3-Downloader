import re
from urllib.parse import urlparse, parse_qs

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
SPOTIFY_HOSTS = {"open.spotify.com"}
MAX_LINK_LENGTH = 300

_VIDEO_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
_VIDEO_ID_ONLY_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,64}$")
_BROWSE_ID_RE = re.compile(r"^MPREb_[A-Za-z0-9_-]{5,40}$")
_SPOTIFY_PATH_RE = re.compile(r"^/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(playlist|album|track)/([A-Za-z0-9]{22})/?$")


class LinkError(ValueError):
    """A pasted link we won't resolve; the message is safe to show a friend."""


def is_youtube_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in YOUTUBE_HOSTS


def extract_video_id(url):
    """The 11-character video ID of a YouTube/YouTube Music video URL, or None."""
    if not url or not is_youtube_url(url):
        return None
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def is_video_id(value):
    return bool(value) and bool(_VIDEO_ID_ONLY_RE.match(value))


def video_url(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def music_url(video_id):
    """The YouTube Music watch URL, which gets yt-dlp's music metadata and formats."""
    return f"https://music.youtube.com/watch?v={video_id}"


def parse_link(raw):
    """
    Classifies a pasted link and rebuilds it from its extracted ID, so the
    friend's original string never reaches yt-dlp or Spotify.

    Returns:
        dict: {"kind": "video"|"playlist"|"album"|"spotify_playlist"|
        "spotify_album"|"spotify_track", "id": str, "url": canonical URL}

    Raises:
        LinkError: for anything that isn't a supported YouTube/Spotify link.
    """
    raw = (raw or "").strip()
    if not raw:
        raise LinkError("Paste a link first.")
    if len(raw) > MAX_LINK_LENGTH:
        raise LinkError("That link is too long.")
    try:
        parsed = urlparse(raw if "://" in raw else "https://" + raw)
        host = (parsed.hostname or "").lower()
    except ValueError:
        raise LinkError("That doesn't look like a link.")
    if parsed.scheme not in ("http", "https"):
        raise LinkError("That doesn't look like a link.")

    if host in YOUTUBE_HOSTS:
        video_id = extract_video_id(parsed.geturl())
        if video_id:
            return {"kind": "video", "id": video_id, "url": video_url(video_id)}
        list_id = (parse_qs(parsed.query).get("list") or [""])[0]
        if parsed.path.rstrip("/") == "/playlist" and _PLAYLIST_ID_RE.match(list_id):
            return {"kind": "playlist", "id": list_id, "url": f"https://www.youtube.com/playlist?list={list_id}"}
        if host == "music.youtube.com" and parsed.path.startswith("/browse/"):
            browse_id = parsed.path[len("/browse/"):].strip("/")
            if _BROWSE_ID_RE.match(browse_id):
                return {"kind": "album", "id": browse_id, "url": f"https://music.youtube.com/browse/{browse_id}"}
        raise LinkError("Paste a YouTube song or playlist link.")

    if host in SPOTIFY_HOSTS:
        match = _SPOTIFY_PATH_RE.match(parsed.path)
        if match:
            kind, spotify_id = match.groups()
            return {"kind": f"spotify_{kind}", "id": spotify_id, "url": f"https://open.spotify.com/{kind}/{spotify_id}"}
        raise LinkError("Paste a Spotify playlist, album or track link.")

    raise LinkError("Only YouTube, YouTube Music and Spotify links work here.")
