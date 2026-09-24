"""Downloads the songs I approved from friend submissions into the library
the same way the dashboard downloader lays out albums - "Album - Name/NN -
Title" - with every tag written and the cover squared, then syncs just those
album folders."""
import json
import re
import shutil
import tempfile
import threading
from pathlib import Path

import core.audioTags as audioTags
import core.checkDependencies as checkDependencies
import core.interfaceComponents as interfaceComponents
import core.linkResolver as linkResolver
import core.musicSearch as musicSearch
import core.playlistDownloader as playlistDownloader
import core.processAlbumCover as processAlbumCover
import core.songMatch as songMatch
import database.databaseConnector as databaseConnector
import database.suggestionsRepo as suggestionsRepo
import database.syncLibrary as syncLibrary

# Held for the whole of any yt-dlp download batch, so a friend-suggestion
# approval and a dashboard download never run against YouTube at once.
download_lock = threading.Lock()

SINGLES_ALBUM = "Singles"
# YouTube Music names album playlists "Album - Name", so that's the folder a
# dashboard download of the album lands in; cleanupManager keeps these copies.
ALBUM_FOLDER_PREFIX = "Album - "
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME_LENGTH = 120


def safe_name(text, fallback):
    """A single path component that is valid on Windows and POSIX."""
    name = _UNSAFE_FILENAME_RE.sub("_", (text or "").strip())
    name = name.strip(" .")[:MAX_NAME_LENGTH].strip(" .")
    return name or fallback


def _first(value):
    """yt-dlp gives some fields as lists ("artists"); the first entry or the value."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value).strip() if value not in (None, "") else None


def _info_year(info):
    for key in ("release_year", "release_date", "upload_date"):
        value = _first(info.get(key))
        if value and value[:4].isdigit():
            return value[:4]
    return None


def item_metadata(item, info):
    """
    Every tag for one approved item. What the friend picked from (album
    track list, Spotify) beats what yt-dlp found for the video (its info
    JSON), which beats the uploading channel.
    """
    info_artist = _first(info.get("artist")) or _first(info.get("artists")) or _first(info.get("creator"))
    # Without music metadata yt-dlp falls back to the uploader, which is no
    # better than the channel name itself.
    if info_artist and info_artist == item.get("channel"):
        info_artist = None
    if info_artist:
        info_artist = processAlbumCover.clean_artist(info_artist)
    artist = item.get("sp_artist") or item.get("artist") or info_artist or         songMatch.artist_from_upload(item.get("title"), item.get("channel")) or "Unknown Artist"

    info_album = _first(info.get("album"))
    album = item.get("sp_album") or item.get("album") or info_album or SINGLES_ALBUM
    # Track/disc/year describe the release yt-dlp saw; only trust them when
    # that's the same album the song is being filed under.
    same_release = bool(info_album) and info_album.lower() == album.strip().lower()

    title = item.get("sp_title") or _first(info.get("track")) or songMatch.clean_song_title(item.get("title"), artist)
    # A plain playlist's position isn't an album track number (suggestions
    # sent before list_playlist_tracks() stopped setting it still carry it).
    item_track = item.get("track_number") if item.get("source") != "yt_playlist" else None
    track_number = item_track or (same_release and info.get("track_number")) or 0
    album_artist = _first(info.get("album_artist")) or _first(info.get("album_artists"))
    if not same_release or not album_artist:
        album_artist = artist
    return {
        "artist": artist.strip(),
        "album_artist": processAlbumCover.clean_artist(album_artist),
        "album": album.strip(),
        "title": title.strip(),
        "track_number": int(track_number),
        "disc_number": int(info.get("disc_number") or 0) if same_release else 0,
        "year": _info_year(info) if same_release or album == SINGLES_ALBUM else None,
        "genre": _first(info.get("genre")) or _first(info.get("genres")),
    }


def track_number_in_album(tracks, meta, youtube_id):
    """
    The song's position in an album track list (list_playlist_tracks()
    shape), or 0 if the list isn't that album or doesn't have the song. The
    same video ID wins; otherwise the title, since a music video's ID isn't
    the one on the album.
    """
    album_key = songMatch.fold(meta["album"])
    if not tracks or songMatch.fold(tracks[0].get("album") or "") != album_key:
        return 0
    wanted_title = songMatch.normalize_title(meta["title"], meta["artist"])
    by_title = 0
    for track in tracks:
        if track["youtube_id"] == youtube_id:
            return int(track.get("track_number") or 0)
        if not by_title and songMatch.normalize_title(track.get("title"), meta["artist"]) == wanted_title:
            by_title = int(track.get("track_number") or 0)
    return by_title


def lookup_track_number(meta, youtube_id):
    """
    YouTube only numbers a song inside an album playlist, so for a song
    picked on its own, find its album on YouTube Music and take its
    position there. 0 when that can't be pinned down.
    """
    if meta["album"] == SINGLES_ALBUM:
        return 0
    try:
        tracks = musicSearch.search_album_tracks(f"{meta['album_artist']} {meta['album']}")
    except Exception as e:
        interfaceComponents.Print_Tag(f"Track number lookup failed for {youtube_id}: {e}", tag="Warning")
        return 0
    return track_number_in_album(tracks, meta, youtube_id)


def _write_tags(file_path, meta):
    """Writes the full tag set; yt-dlp's other tags (source URL, etc.) stay."""
    audio = audioTags.open_tags(file_path)
    if audio.tags is None:
        audio.add_tags()
    audio["title"] = meta["title"]
    audio["artist"] = meta["artist"]
    audio["albumartist"] = meta["album_artist"]
    audio["album"] = meta["album"]
    optional = {
        "tracknumber": str(meta["track_number"]) if meta["track_number"] else None,
        "discnumber": str(meta["disc_number"]) if meta["disc_number"] else None,
        "date": meta["year"],
        "genre": meta["genre"],
    }
    for key, value in optional.items():
        if value:
            audio[key] = value
        elif key in audio:
            # e.g. yt-dlp's upload date or playlist position, when it isn't this release's
            del audio[key]
    audio.save()


def target_path(library_folder, meta, extension):
    """
    <library>/Album - <album>/NN - <title>.ext, the layout of a dashboard
    album download. Songs with no album go to <library>/Singles.
    """
    if meta["album"] == SINGLES_ALBUM:
        album_dir = SINGLES_ALBUM
    else:
        album_dir = safe_name(ALBUM_FOLDER_PREFIX + meta["album"], SINGLES_ALBUM)
    # Always numbered, even "00": syncLibrary reads leading digits as the
    # track number, so an unnumbered "3 Libras" would sync as track 3 "Libras".
    filename = f"{meta['track_number']:02d} - {safe_name(meta['title'], 'Untitled')}{extension}"
    return Path(library_folder) / album_dir / filename


def _read_info_json(media_path):
    info_path = media_path.with_suffix(".info.json")
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    finally:
        info_path.unlink(missing_ok=True)


def _download_one(item, audio_format, library_folder, work_dir, overwrite=False):
    """
    Returns the album folder the song landed in.

    Args:
        overwrite (bool): replace an existing file at the target path (a
            re-download); otherwise an existing file is left alone and it fails.
    """
    download_fn = playlistDownloader.download_file_mp3 if audio_format == "mp3" else playlistDownloader.download_file_flac
    files = download_fn(linkResolver.music_url(item["youtube_id"]), work_dir,
                        file_template="%(id)s.%(ext)s", write_info_json=True)
    if not files or not Path(files[0]).exists():
        raise RuntimeError("yt-dlp produced no file (see the server log)")
    downloaded = Path(files[0])

    meta = item_metadata(item, _read_info_json(downloaded))
    if not meta["track_number"]:
        meta["track_number"] = lookup_track_number(meta, item["youtube_id"])
    _write_tags(downloaded, meta)
    # Same square 250px JPEG the dashboard's "process covers" step makes.
    processAlbumCover.process_album_cover(downloaded)
    destination = target_path(library_folder, meta, downloaded.suffix.lower())
    if destination.exists():
        if not overwrite:
            raise RuntimeError(f"{destination.name} is already in the library")
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(downloaded), str(destination))
    return destination.parent


def run_approval(submission_id, item_ids, audio_format, progress, redownload_ids=()):
    """
    Background job: download each approved item, record per-item results,
    sync the album folders that changed.

    Args:
        progress (callable): progress(percent, status) for the admin UI.
        redownload_ids (set): items downloaded before, whose library file
            this download may replace.
    """
    items = [suggestionsRepo.get_item(item_id) for item_id in item_ids]
    items = [i for i in items if i and i["submission_id"] == submission_id]
    total = len(items)
    library_folder = databaseConnector.get_library_folder()
    touched_folders = set()
    failures = 0

    with download_lock, tempfile.TemporaryDirectory(prefix="friend-dl-") as work_dir:
        checkDependencies.dependencies_check()
        for index, item in enumerate(items):
            progress(index / total * 100, f"Downloading {index + 1} of {total}: {item['title'][:40]}")
            try:
                touched_folders.add(_download_one(item, audio_format, library_folder, work_dir,
                                                  overwrite=item["item_id"] in redownload_ids))
                suggestionsRepo.set_item_decision(item["item_id"], "downloaded")
            except Exception as e:
                failures += 1
                interfaceComponents.Print_Tag(f"Friend download failed for {item['youtube_id']}: {e}", tag="Error")
                suggestionsRepo.set_item_decision(item["item_id"], "failed", str(e)[:300])

    progress(95, "Syncing library...")
    for folder in touched_folders:
        syncLibrary.Sync_Folder_To_Db(str(folder))
    suggestionsRepo.invalidate_library_index()

    submission = suggestionsRepo.get_submission(submission_id)
    if submission and not any(i["kept"] and i["decision"] in ("pending", "approved", "downloading")
                              for i in submission["items"]):
        suggestionsRepo.set_submission_status(submission_id, "done")
    progress(100, "complete" if not failures else f"Error: {failures} of {total} downloads failed")
