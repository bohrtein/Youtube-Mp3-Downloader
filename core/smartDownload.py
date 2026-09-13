import argparse
import json
from pathlib import Path

import core.checkDependencies as checkDependencies
import core.musicSearch as musicSearch
import core.playlistDownloader as playlistDownloader
import core.releaseDedup as releaseDedup
import core.interfaceComponents as interfaceComponents


def get_default_download_folder():
    """
    Returns the repo's own downloads/ folder (gitignored scratch space),
    not the OS Downloads folder. Deliberately independent from
    database.databaseConnector.get_library_folder() - that setting (and
    library.db) belong to the MP3-player sync workflow and this skill never
    touches either.
    """
    return str(Path(__file__).resolve().parent.parent / "downloads")


def plan_song(query):
    """
    Builds a download plan for a single song request.

    Args:
        query (str): Free-text search, e.g. "Artist Song Title".

    Returns:
        dict: {"kind": "song", "kept": [...], "skipped": []}
    """
    results = musicSearch.search_songs(query, limit=5)
    kept = results[:1]
    skipped = [
        {"release": r, "reason": "not the top match for this song"}
        for r in results[1:]
    ]
    return {"kind": "song", "kept": kept, "skipped": skipped}


def plan_album(artist, album):
    """
    Builds a download plan for a single album request, deduping multiple
    editions (deluxe/extended/etc.) of the same album down to one.

    Args:
        artist (str): Artist name.
        album (str): Album name.

    Returns:
        dict: {"kind": "album", "kept": [...], "skipped": [...]}
    """
    candidates = musicSearch.search_album_candidates(artist, album)

    skipped = []
    studio_candidates = []
    for r in candidates:
        if releaseDedup.is_studio_album(r["title"]):
            studio_candidates.append(r)
        else:
            skipped.append({"release": r, "reason": "live/compilation version, not the studio album"})

    kept, dedup_skipped_pairs = releaseDedup.dedupe_releases(studio_candidates)
    for r, reason, chosen in dedup_skipped_pairs:
        skipped.append({"release": r, "reason": reason, "kept_instead": chosen.get("title")})

    # kept may still contain distinct releases (e.g. an unrelated search hit) -
    # take the top-ranked match and note the rest as not selected, so the
    # agent reviewing the plan can see exactly what was set aside and why.
    top = kept[:1]
    for r in kept[1:]:
        skipped.append({"release": r, "reason": "not the top match for this album"})

    return {"kind": "album", "kept": top, "skipped": skipped}


def plan_artist(artist):
    """
    Builds a download plan for an artist's full studio discography: live
    albums/compilations are filtered out, and multiple editions of the same
    studio album are deduped down to one.

    Args:
        artist (str): Artist name.

    Returns:
        dict: {"kind": "artist", "kept": [...], "skipped": [...]}, or
        {"kind": "artist", "kept": [], "skipped": [], "error": "..."} if the
        artist's channel/releases couldn't be confidently discovered.
    """
    releases = musicSearch.list_artist_releases(artist)
    if not releases:
        return {
            "kind": "artist", "kept": [], "skipped": [],
            "error": f"Could not confidently find '{artist}' on YouTube Music. "
                     "Ask the user for the exact artist name or a direct album URL.",
        }

    skipped = []
    studio_releases = []
    for r in releases:
        if releaseDedup.is_studio_album(r["title"]):
            studio_releases.append(r)
        else:
            skipped.append({"release": r, "reason": "live album or compilation, not a studio album"})

    kept, dedup_skipped_pairs = releaseDedup.dedupe_releases(studio_releases)
    for r, reason, chosen in dedup_skipped_pairs:
        skipped.append({"release": r, "reason": reason, "kept_instead": chosen.get("title")})

    return {"kind": "artist", "kept": kept, "skipped": skipped}


def execute_plan(plan, dest=None):
    """
    Downloads every item in plan["kept"] as FLAC via the existing
    playlistDownloader pipeline.

    Args:
        plan (dict): A plan returned by plan_song/plan_album/plan_artist.
        dest (str | None): Target folder; defaults to get_default_download_folder().

    Returns:
        list[str]: Titles that were downloaded.
    """
    target_dir = dest or get_default_download_folder()
    Path(target_dir).mkdir(parents=True, exist_ok=True)

    checkDependencies.dependencies_check()

    downloaded = []
    for item in plan["kept"]:
        interfaceComponents.Print_Tag(f"Downloading: {item['title']}", tag="SmartDL")
        playlistDownloader.download_file_flac(item["url"], target_dir)
        downloaded.append(item["title"])
    return downloaded


def _main():
    parser = argparse.ArgumentParser(
        description="Search YouTube Music and download smartly to a folder "
                    "(default: the OS Downloads folder). Prints a plan by "
                    "default; pass --download to actually fetch."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--song", metavar="QUERY", help="Search for a single song.")
    group.add_argument("--album", nargs=2, metavar=("ARTIST", "ALBUM"), help="Search for one album.")
    group.add_argument("--artist", metavar="NAME", help="Search for an artist's full studio discography.")
    parser.add_argument("--dest", metavar="PATH", help="Destination folder (default: OS Downloads folder).")
    parser.add_argument("--download", action="store_true", help="Actually download; otherwise only prints the plan.")
    args = parser.parse_args()

    if args.song:
        plan = plan_song(args.song)
    elif args.album:
        plan = plan_album(args.album[0], args.album[1])
    else:
        plan = plan_artist(args.artist)

    print(json.dumps(plan, indent=2))

    if args.download:
        if plan.get("error"):
            interfaceComponents.Print_Tag("Refusing to download: plan has an unresolved error.", tag="Error")
            return
        execute_plan(plan, dest=args.dest)


if __name__ == "__main__":
    _main()
