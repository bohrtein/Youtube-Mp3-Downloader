import re
from urllib.parse import urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}

_VIDEO_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")


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
