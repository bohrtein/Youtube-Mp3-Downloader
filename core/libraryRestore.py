"""Restore missing library files from the server's SQLite catalog."""
from contextlib import closing
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import unicodedata

from core import approvedDownloads, checkDependencies, hubJobs, interfaceComponents
from core import linkResolver, musicSearch, playlistDownloader, restoreNetwork
from database import databaseConnector, libraryFiles, suggestionsRepo, syncLibrary

TRACK_DELAY_SECONDS = 5
catalog_file_lock = threading.Lock()
UNAVAILABLE_SOURCE = re.compile(
    r"video (?:is )?unavailable|private video|not available in your country|requested format is not available",
    re.IGNORECASE,
)
SMART_QUOTES = str.maketrans("‘’“”", "''\"\"")


def _catalog():
    with closing(databaseConnector.connect_to_db()) as conn:
        return conn.execute("""
            SELECT s.*, a.album_name, a.release_date AS album_year, ar.artist_name
            FROM songs s JOIN albums a ON a.album_id = s.album_id
            JOIN artists ar ON ar.artist_id = a.artist_id
            ORDER BY a.album_id, s.track_number, s.song_id
        """).fetchall()


def _key(song):
    return song["artist_name"], song["album_name"], song["track_number"] or 0, song["song_title"]


def _saved_video_id(song):
    video_id = song["youtube_id"]
    if linkResolver.is_video_id(video_id):
        return video_id
    return linkResolver.extract_video_id(song["source_url"])


def _match_text(value):
    return unicodedata.normalize("NFKC", value).translate(SMART_QUOTES).casefold().strip()


def _find_video_id(song, excluded_id=None):
    artist, album, _, title = _key(song)
    duration = song["duration_seconds"]
    matches = musicSearch.search_songs(f"{artist} {album} {title}", limit=10, proxy=restoreNetwork.vpn_proxy())
    ids = {match["youtube_id"] for match in matches
           if linkResolver.is_video_id(match["youtube_id"])
           and match["youtube_id"] != excluded_id
           and _match_text(match["title"]) == _match_text(title)
           and _match_text(match["channel"]) == _match_text(artist)
           and duration and match["duration"] and abs(duration - match["duration"]) <= 3}
    if len(ids) == 1:
        return ids.pop()
    raise ValueError("No unique YouTube source matched the catalog track")


def _download_track(song, download, staging, extension, cancel_event):
    def fetch(video_id):
        directory = staging / video_id
        directory.mkdir()
        paths = download(linkResolver.music_url(video_id), directory, file_template="audio.%(ext)s",
                         strict=True, cancel_event=cancel_event, proxy=restoreNetwork.vpn_proxy())
        audio = directory / f"audio{extension}"
        if not paths or not audio.is_file():
            raise RuntimeError("yt-dlp produced no audio file")
        return audio

    saved_id = _saved_video_id(song)
    if saved_id:
        try:
            return fetch(saved_id), None
        except subprocess.CalledProcessError as error:
            stderr = error.stderr or ""
            if (cancel_event.is_set() or restoreNetwork.is_rate_limited(stderr)
                    or not UNAVAILABLE_SOURCE.search(stderr)):
                raise
    replacement = _find_video_id(song, excluded_id=saved_id)
    return fetch(replacement), replacement


def _restore_track(song, root, staging, cancel_event, audio_format):
    artist, album, number, title = _key(song)
    folder = root / approvedDownloads.album_folder_name(album)
    saved_format = (song["file_type"] or "").lower()
    track_format = audio_format or (saved_format if saved_format in ("mp3", "m4a") else "flac")
    extension = f".{track_format}"
    filename = f"{number:02d} - {title}{extension}"
    destination = folder / filename
    if destination.parent != folder or not folder.resolve().is_relative_to(root):
        raise ValueError("Track has an invalid library path")
    if destination.exists():
        raise FileExistsError(f"A file already occupies {destination.name}")

    download = playlistDownloader.downloader_for(track_format)
    with tempfile.TemporaryDirectory(prefix="track-", dir=staging) as temp:
        audio, replacement = _download_track(song, download, Path(temp), extension, cancel_event)
        year = song["release_date"] or song["album_year"]
        metadata = {"artist": artist, "album_artist": artist, "album": album, "title": title,
                    "track_number": number, "disc_number": None, "year": str(year) if year else None,
                    "genre": None}
        approvedDownloads.write_tags(audio, metadata, preserve_optional=track_format == "m4a")
        with catalog_file_lock:
            if cancel_event.is_set():
                return None
            with closing(databaseConnector.connect_to_db()) as conn:
                if not conn.execute("SELECT 1 FROM songs WHERE song_id = ?", (song["song_id"],)).fetchone():
                    return None  # Deleted while yt-dlp was running.
                if destination.exists():
                    raise FileExistsError(f"A file already occupies {destination.name}")
                if replacement:
                    conn.execute("UPDATE songs SET source_url = ?, youtube_id = ? WHERE song_id = ?",
                                 (linkResolver.music_url(replacement), replacement, song["song_id"]))
                folder.mkdir(parents=True, exist_ok=True)
                audio.replace(destination)
                conn.commit()
    return folder


def restore_library(job, audio_format=None):
    job.update(None, "Waiting for other downloads")
    if not hubJobs.acquire_download_lock(approvedDownloads.download_lock, job.cancel_event):
        return "cancelled"
    touched = set()
    try:
        job.update(None, "Checking the library for missing audio")
        songs = _catalog()
        if not songs:
            return "failed", "The library catalog has no tracks to restore."
        root = Path(databaseConnector.get_library_folder()).resolve()
        existing = {key for key, _ in libraryFiles.iter_song_files(root, map(_key, songs))}
        missing = [song for song in songs if _key(song) not in existing]
        if not missing:
            return "done", "All catalog tracks are already on disk."
        needs_proxy = audio_format == "m4a" or any((song["file_type"] or "").lower() == "m4a" for song in missing)
        if needs_proxy and not restoreNetwork.vpn_proxy():
            return "failed", "Configure the server VPN proxy before restoring M4A tracks."
        if job.cancel_event.is_set():
            return "cancelled"
        checkDependencies.dependencies_check()
        staging = root / ".app-trash"
        if staging.resolve() != staging:
            raise ValueError("Restore staging folder must be inside the library")
        staging.mkdir(parents=True, exist_ok=True)
        return _restore_missing(job, missing, root, staging, touched, audio_format)
    finally:
        try:
            for folder in touched:
                with catalog_file_lock:
                    syncLibrary.Sync_Folder_To_Db(str(folder))
            if touched:
                suggestionsRepo.invalidate_library_index()
        finally:
            approvedDownloads.download_lock.release()


def _restore_missing(job, missing, root, staging, touched, audio_format):
    failures = restored = rotations = 0
    total = len(missing)
    for index, song in enumerate(missing):
        percent = index * 100 / total
        label = f"Restoring {index + 1} of {total} · {song['album_name']} / {song['song_title']}"
        while not job.cancel_event.is_set():
            job.update(percent, label)
            try:
                folder = _restore_track(song, root, staging, job.cancel_event, audio_format)
                if folder is not None:
                    touched.add(folder)
                    restored += 1
                break
            except Exception as exc:
                if job.cancel_event.is_set():
                    return "cancelled"
                stderr = (exc.stderr or "") if isinstance(exc, subprocess.CalledProcessError) else ""
                if not restoreNetwork.is_rate_limited(stderr):
                    failures += 1
                    reason = (f"yt-dlp exited with code {exc.returncode}"
                              if isinstance(exc, subprocess.CalledProcessError) else str(exc))
                    interfaceComponents.Print_Tag(f"{label}: {reason}", tag="Error")
                    break
                if rotations >= restoreNetwork.VPN_ROTATION_LIMIT:
                    return "failed", f"Restored {restored} of {total}. YouTube is still limiting downloads. Try again later."
                job.update(percent, "YouTube limited downloads. Switching the server VPN exit IP…", force=True)
                try:
                    restoreNetwork.rotate_vpn(job.cancel_event)
                except restoreNetwork.VPNRotationError as error:
                    return "failed", f"Restored {restored} of {total}. {error}"
                rotations += 1
                job.cancel_event.wait(TRACK_DELAY_SECONDS)
        if job.cancel_event.is_set() or (index + 1 < total and job.cancel_event.wait(TRACK_DELAY_SECONDS)):
            return "cancelled"
    if failures:
        return "failed", f"Restored {restored} of {total} missing tracks. {failures} failed. See the server log."
    return "done", f"Restored {restored} missing tracks."
