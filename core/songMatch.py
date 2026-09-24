import re
import unicodedata

_BRACKETS_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_FEAT_RE = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
_TRACK_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*[\.\-\)]\s*")
_CHANNEL_SUFFIX_RE = re.compile(r"\s*(-\s*topic|vevo|official|music|band)\s*$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")


def fold(text):
    """Lowercase ASCII letters/digits only: 'Sigur Rós' -> 'sigurros'."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM_RE.sub("", ascii_only.lower())


def normalize_artist(name):
    """'A Perfect Circle - Topic' / 'RammsteinVEVO' / 'Rammstein Official' -> the bare folded name."""
    name = name or ""
    previous = None
    while previous != name:
        previous = name
        name = _CHANNEL_SUFFIX_RE.sub("", name)
    return fold(name)


_VERSION_SUFFIX_RE = re.compile(
    r"\s+-\s+[^-]*\b(remaster(ed)?|version|edit|mono|stereo|mix|live|acoustic|demo|bonus|anniversary|recorded)\b[^-]*$",
    re.IGNORECASE,
)


def strip_version_suffix(title):
    """Spotify's edition suffixes: 'Dreams - 2004 Remaster' -> 'Dreams'."""
    return _VERSION_SUFFIX_RE.sub("", title or "").strip() or (title or "")


def normalize_title(title, artist=None):
    """
    Reduces a video or track title to the song name so different uploads
    compare equal: 'A Perfect Circle - Judith (Official Music Video)' and
    'Judith' both become 'judith' (given the artist).
    """
    title = strip_version_suffix(_BRACKETS_RE.sub(" ", title or "").strip())
    title = _FEAT_RE.sub("", title)
    title = _TRACK_NUMBER_RE.sub("", title)
    artist_key = normalize_artist(artist) if artist else ""
    if " - " in title and artist_key:
        left, right = title.split(" - ", 1)
        if normalize_artist(left) == artist_key:
            title = right
        elif normalize_artist(right) == artist_key:
            title = left
    return fold(title)


_VIDEO_NOISE_RE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|explicit|clip)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def clean_song_title(title, artist=None):
    """
    A video title made fit for a filename/tag, keeping its real spelling:
    'A Perfect Circle - Judith (Official Music Video)' -> 'Judith'.
    """
    original = (title or "").strip()
    cleaned = _VIDEO_NOISE_RE.sub("", original).strip()
    if artist and " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        if normalize_artist(left) == normalize_artist(artist):
            cleaned = right.strip()
    return cleaned or original


_CHANNEL_NOISE_RE = re.compile(r"(\s*-\s*topic|\s*official(\s+channel)?|vevo)\s*$", re.IGNORECASE)


def clean_channel_name(channel):
    """'Rammstein Official' / 'RammsteinVEVO' / 'Rammstein - Topic' -> 'Rammstein'."""
    name, previous = (channel or "").strip(), None
    while previous != name:
        previous = name
        name = _CHANNEL_NOISE_RE.sub("", name).strip()
    return name or (channel or "").strip()


def artist_from_upload(title, channel):
    """
    Best artist name for an upload without music metadata: the 'Artist' in an
    'Artist - Song' title when it matches the channel, else the channel
    without its Official/VEVO/Topic decoration.
    """
    if " - " in (title or ""):
        left = title.split(" - ", 1)[0].strip()
        if left and artist_matches(channel, left):
            return left
    return clean_channel_name(channel)


_ARTIST_LIST_SPLIT_RE = re.compile(r",\s*|\s+&\s+|\s+(?:feat\.?|ft\.?|featuring)\s+", re.IGNORECASE)


def artist_matches(channel_or_artist, artist):
    """
    True if a channel/artist string belongs to artist (either contains the
    other). A credit list like 'Miley Cyrus, Someone' matches any one of them.
    """
    a = normalize_artist(channel_or_artist)
    if not a:
        return False
    names = {normalize_artist(artist)}
    names.update(n for n in (normalize_artist(p) for p in _ARTIST_LIST_SPLIT_RE.split(artist or "")) if len(n) >= 3)
    return any(b and (a in b or b in a) for b in names)
