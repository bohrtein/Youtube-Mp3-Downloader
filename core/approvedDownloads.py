"""Downloads the songs I approved from friend submissions into the library
as Artist/Album/NN - Title, then syncs just those album folders."""
import re
import shutil
import tempfile
import threading
from pathlib import Path

import core.audioTags as audioTags
import core.checkDependencies as checkDependencies
import core.interfaceComponents as interfaceComponents
import core.linkResolver as linkResolver
import core.playlistDownloader as playlistDownloader
import core.songMatch as songMatch
import database.databaseConnector as databaseConnector
import database.suggestionsRepo as suggestionsRepo
import database.syncLibrary as syncLibrary

# Held for the whole of any yt-dlp download batch, so a friend-suggestion
# approval and a dashboard download never run against YouTube at once.
download_lock = threading.Lock()

SINGLES_ALBUM = "Singles"
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME_LENGTH = 120


def safe_name(text, fallback):
    """A single path component that is valid on Windows and POSIX."""
    name = _UNSAFE_FILENAME_RE.sub("_", (text or "").strip())
    name = name.strip(" .")[:MAX_NAME_LENGTH].strip(" .")
    return name or fallback


def item_metadata(item, embedded):
    """
    Artist/album/title/track for one approved item. What the friend picked
    from (album track list, Spotify) beats what yt-dlp embedded, which beats
    the uploading channel.
    """
    embedded_artist = (embedded.get("artist") or [None])[0]
    embedded_album = (embedded.get("album") or [None])[0]
    # Without music metadata yt-dlp tags the uploader as the artist, which
    # is no better than the channel name itself.
    if embedded_artist and embedded_artist == item.get("channel"):
        embedded_artist = None
    artist = item.get("sp_artist") or item.get("artist") or embedded_artist or \
        songMatch.artist_from_upload(item.get("title"), item.get("channel")) or "Unknown Artist"
    album = item.get("sp_album") or item.get("album") or embedded_album or SINGLES_ALBUM
    title = item.get("sp_title") or songMatch.clean_song_title(item.get("title"), artist)
    track_number = item.get("track_number") or 0
    return {"artist": artist.strip(), "album": album.strip(), "title": title.strip(), "track_number": int(track_number)}


def _write_tags(file_path, meta):
    audio = audioTags.open_tags(file_path)
    if audio.tags is None:
        audio.add_tags()
    audio["artist"] = meta["artist"]
    audio["album"] = meta["album"]
    audio["title"] = meta["title"]
    if meta["track_number"]:
        audio["tracknumber"] = str(meta["track_number"])
    audio.save()


def target_path(library_folder, meta, extension):
    artist_dir = safe_name(meta["artist"], "Unknown Artist")
    album_dir = safe_name(meta["album"], SINGLES_ALBUM)
    # Always numbered, even "00": syncLibrary reads leading digits as the
    # track number, so an unnumbered "3 Libras" would sync as track 3 "Libras".
    filename = f"{meta['track_number']:02d} - {safe_name(meta['title'], 'Untitled')}{extension}"
    return Path(library_folder) / artist_dir / album_dir / filename


def _download_one(item, audio_format, library_folder, work_dir):
    """Returns the album folder the song landed in."""
    download_fn = playlistDownloader.download_file_mp3 if audio_format == "mp3" else playlistDownloader.download_file_flac
    files = download_fn(linkResolver.video_url(item["youtube_id"]), work_dir, file_template="%(id)s.%(ext)s")
    if not files or not Path(files[0]).exists():
        raise RuntimeError("yt-dlp produced no file (see the server log)")
    downloaded = Path(files[0])

    embedded = audioTags.open_tags(downloaded)
    meta = item_metadata(item, embedded.tags if embedded is not None and embedded.tags is not None else {})
    _write_tags(downloaded, meta)
    destination = target_path(library_folder, meta, downloaded.suffix.lower())
    if destination.exists():
        raise RuntimeError(f"{destination.name} is already in the library")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(downloaded), str(destination))
    return destination.parent


def run_approval(submission_id, item_ids, audio_format, progress):
    """
    Background job: download each approved item, record per-item results,
    sync the album folders that changed.

    Args:
        progress (callable): progress(percent, status) for the admin UI.
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
                touched_folders.add(_download_one(item, audio_format, library_folder, work_dir))
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
