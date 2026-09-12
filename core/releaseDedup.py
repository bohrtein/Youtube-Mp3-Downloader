import re

# Parenthesized/bracketed edition qualifiers to strip when comparing release
# titles, e.g. "Album (Deluxe Edition)" and "Album [Extended]" both become "Album".
_EDITION_QUALIFIER_RE = re.compile(
    r"""[\(\[]\s*(
        deluxe|extended|remaster(ed)?|anniversary|special|expanded|
        bonus\ track|super\ deluxe|collector'?s|explicit|clean|
        international|platinum|edition|version
    )[^\)\]]*[\)\]]""",
    re.IGNORECASE | re.VERBOSE,
)

# Trailing suffixes yt-dlp/YouTube Music sometimes appends outside brackets.
_TRAILING_SUFFIX_RE = re.compile(r"\s*-\s*(single|ep)\s*$", re.IGNORECASE)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_release_title(title):
    """
    Strips edition qualifiers and extra whitespace so different pressings of
    the same release compare equal, e.g. "Album (Deluxe Edition)" and
    "Album (Extended)" both normalize to "album".
    """
    normalized = _EDITION_QUALIFIER_RE.sub("", title)
    normalized = _TRAILING_SUFFIX_RE.sub("", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip().lower()
    return normalized


# Heuristics for filtering out live albums and compilations when a request
# is for an artist's studio discography.
_NON_STUDIO_RE = re.compile(
    r"""\b(
        live|unplugged|concert|in\ concert|at\ the\ |
        session(s)?|compilation|greatest\ hits|best\ of|
        anthology|collection|b-sides
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)


def is_studio_album(title):
    """
    Rejects titles that look like live albums or compilations rather than a
    studio release. Heuristic and title-based - callers should still let the
    user override when the request explicitly asks for one of these.
    """
    return not _NON_STUDIO_RE.search(title)


def dedupe_releases(releases):
    """
    Groups releases by normalized title and keeps exactly one per group.

    Args:
        releases: list of dicts, each with at least a "title" key (and
            optionally "track_count" used as a tiebreaker).

    Returns:
        (kept, skipped) where kept is a list of release dicts and skipped is
        a list of (release, reason, kept_instead) tuples explaining why each
        duplicate was dropped.
    """
    groups = {}
    order = []
    for release in releases:
        key = normalize_release_title(release["title"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(release)

    kept = []
    skipped = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            kept.append(group[0])
            continue

        # Prefer the plain/standard-named entry (title survives normalization
        # unchanged, i.e. it carried no edition qualifier).
        plain = [r for r in group if r["title"].strip().lower() == key]
        if plain:
            chosen = plain[0]
        else:
            # Otherwise prefer the release with the most tracks, then the first seen.
            chosen = max(group, key=lambda r: r.get("track_count") or 0)

        kept.append(chosen)
        for release in group:
            if release is not chosen:
                skipped.append((release, "duplicate edition of the same release", chosen))

    return kept, skipped
