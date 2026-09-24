import re
import core.songMatch as songMatch

# (flag, pattern) checked against the YouTube title. A keyword that also
# appears in the title the friend asked for (e.g. a Spotify track that
# really is "(Live)") isn't suspicious, so it isn't flagged.
_KEYWORD_FLAGS = [
    ("live", re.compile(r"\b(live|in concert|unplugged)\b", re.IGNORECASE)),
    ("cover", re.compile(r"\bcover\b", re.IGNORECASE)),
    ("remix", re.compile(r"\bremix(ed)?\b", re.IGNORECASE)),
    ("lyrics", re.compile(r"\blyrics?\b|\blyric video\b", re.IGNORECASE)),
    ("karaoke", re.compile(r"\bkaraoke\b", re.IGNORECASE)),
    ("instrumental", re.compile(r"\binstrumental\b", re.IGNORECASE)),
    ("altered", re.compile(r"\b(sped up|speed up|slowed|nightcore|8d|reverb)\b", re.IGNORECASE)),
    ("reaction", re.compile(r"\breaction\b", re.IGNORECASE)),
    ("full_album", re.compile(r"\bfull album\b", re.IGNORECASE)),
]

FLAG_LABELS = {
    "live": "live version",
    "cover": "cover",
    "remix": "remix",
    "lyrics": "lyrics video",
    "karaoke": "karaoke",
    "instrumental": "instrumental",
    "altered": "sped up / slowed",
    "reaction": "reaction video",
    "full_album": "full album upload",
    "duration_mismatch": "length differs from Spotify",
    "too_long": "over 15 minutes",
    "too_short": "under 45 seconds",
    "unofficial_uploader": "not the artist's channel",
    "in_library": "already in library",
    "maybe_in_library": "maybe already in library",
    "duplicate": "duplicate in this submission",
}

TOO_LONG_SECONDS = 15 * 60
TOO_SHORT_SECONDS = 45


def duration_mismatch(youtube_seconds, spotify_seconds):
    if not youtube_seconds or not spotify_seconds:
        return False
    return abs(youtube_seconds - spotify_seconds) > max(5, 0.05 * spotify_seconds)


def compute_flags(title, channel=None, duration=None, artist=None,
                  requested_title=None, spotify_duration=None, in_library="no", duplicate=False):
    """
    Everything suspicious about one matched song, as a list of FLAG_LABELS
    keys. Pure function: the review page recomputes this whenever a match
    changes.
    """
    flags = []
    for flag, pattern in _KEYWORD_FLAGS:
        if pattern.search(title or "") and not (requested_title and pattern.search(requested_title)):
            flags.append(flag)
    if duration_mismatch(duration, spotify_duration):
        flags.append("duration_mismatch")
    if duration and duration > TOO_LONG_SECONDS:
        flags.append("too_long")
    elif duration and duration < TOO_SHORT_SECONDS:
        flags.append("too_short")
    if artist and channel and not songMatch.artist_matches(channel, artist):
        flags.append("unofficial_uploader")
    if in_library == "yes":
        flags.append("in_library")
    elif in_library == "maybe":
        flags.append("maybe_in_library")
    if duplicate:
        flags.append("duplicate")
    return flags
