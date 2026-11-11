from pathlib import Path
import subprocess
import threading

import pytest

import app
from core import libraryRestore, restoreNetwork
from database import databaseConnector
from conftest import ADMIN_HEADERS
from helpers import add_library_song


@pytest.mark.parametrize("audio_format,extensions", [(None, (".flac", ".mp3")), ("m4a", (".m4a", ".m4a"))])
def test_restore_retries_limited_track_and_skips_completed_files(tmp_path, monkeypatch, audio_format, extensions):
    add_library_song("First", "Artist", "Album", "Cp31A_iqoDw")
    add_library_song("Second", "Artist", "Album", "GLvohMXgcBo")
    with databaseConnector.connect_to_db() as conn:
        conn.execute("UPDATE songs SET file_type = 'MP3' WHERE song_title = 'Second'")
    databaseConnector.set_library_folder(str(tmp_path))
    calls = []
    tags = {}

    def download(extension, url, directory, **kwargs):
        assert kwargs["strict"]
        assert kwargs["proxy"] == "http://127.0.0.1:8888"
        calls.append((extension, url))
        if len(calls) == 2:
            raise subprocess.CalledProcessError(1, "yt-dlp", stderr="HTTP Error 429: Too Many Requests")
        file = Path(directory) / f"audio{extension}"
        file.write_bytes(b"audio")
        return [str(file)]

    def rotate(_):
        calls.append("rotate")

    def write_tags(_, metadata, **kwargs):
        tags[metadata["title"]] = {"artist": [metadata["artist"]], "album": [metadata["album"]]}

    monkeypatch.setenv("LIBRARY_RESTORE_VPN_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setattr(libraryRestore, "TRACK_DELAY_SECONDS", 0)
    monkeypatch.setattr(libraryRestore.checkDependencies, "dependencies_check", lambda: None)
    monkeypatch.setattr(libraryRestore.playlistDownloader, "download_file_flac", lambda *a, **kw: download(".flac", *a, **kw))
    monkeypatch.setattr(libraryRestore.playlistDownloader, "download_file_mp3", lambda *a, **kw: download(".mp3", *a, **kw))
    monkeypatch.setattr(libraryRestore.playlistDownloader, "download_file_m4a", lambda *a, **kw: download(".m4a", *a, **kw))
    monkeypatch.setattr(libraryRestore.approvedDownloads, "write_tags", write_tags)
    monkeypatch.setattr(libraryRestore.libraryFiles.audioTags, "open_tags", lambda file: tags[file.stem[5:]])
    monkeypatch.setattr(libraryRestore.syncLibrary, "Sync_Folder_To_Db", lambda _: None)
    monkeypatch.setattr(restoreNetwork, "rotate_vpn", rotate)

    class Job:
        cancel_event = threading.Event()

        def update(self, *args, **kwargs):
            pass

    first, second = extensions
    assert libraryRestore.restore_library(Job(), audio_format) == ("done", "Restored 2 missing tracks.")
    assert calls == [
        (first, "https://music.youtube.com/watch?v=Cp31A_iqoDw"),
        (second, "https://music.youtube.com/watch?v=GLvohMXgcBo"),
        "rotate",
        (second, "https://music.youtube.com/watch?v=GLvohMXgcBo"),
    ]
    assert sorted(path.name for path in tmp_path.glob("Artist - Album*/*")) == [f"01 - First{first}", f"01 - Second{second}"]
    assert libraryRestore.restore_library(Job()) == ("done", "All catalog tracks are already on disk.")
    assert len(calls) == 4


def test_restore_route_is_private_and_prevents_duplicate_jobs(client, monkeypatch):
    workers = []
    monkeypatch.setattr(app, "restore_status", None)
    monkeypatch.setattr(app.socketio, "start_background_task", lambda fn, *args: workers.append((fn, args)))
    path = "/api/library/restore"
    assert client.post(path, json={}).status_code == 404
    assert client.post(path, headers=ADMIN_HEADERS).status_code == 415
    start = client.post(path, json={}, headers=ADMIN_HEADERS)
    assert start.status_code == 202
    duplicate = client.post(path, json={}, headers=ADMIN_HEADERS)
    assert duplicate.status_code == 409
    assert duplicate.get_json()["job_id"] == start.get_json()["job_id"]
    worker, args = workers.pop()
    worker(*args)
    state = client.get(path, headers=ADMIN_HEADERS).get_json()
    assert state["state"] == "failed"
    assert state["status"] == "The library catalog has no tracks to restore."


def test_library_button_uses_app_prefix(client):
    add_library_song("First", "Artist", "Album")
    response = client.get("/library", headers=ADMIN_HEADERS,
                          environ_overrides={"SCRIPT_NAME": "/app/youtube-mp3-downloader"})
    assert response.status_code == 200
    assert b"Restore missing tracks</button>" in response.data
    assert b'"/app/youtube-mp3-downloader/api/library/restore"' in response.data


def test_restore_replaces_unavailable_saved_source(tmp_path, monkeypatch):
    stale_id = "UpTmMSXm9rw"
    replacement_id = "JvAZ7ewSsLg"
    add_library_song("Electric Red", "Meshuggah", "Obzen", stale_id)
    databaseConnector.set_library_folder(str(tmp_path))
    monkeypatch.setenv("LIBRARY_RESTORE_VPN_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setattr(libraryRestore.approvedDownloads, "write_tags", lambda *args, **kwargs: None)
    attempts = []

    def find(query, *, limit, proxy):
        assert query == "Meshuggah Obzen Electric Red"
        assert proxy == "http://127.0.0.1:8888"
        return [
            {"youtube_id": stale_id, "title": "Electric Red", "channel": "Meshuggah", "duration": 200},
            {"youtube_id": replacement_id, "title": "Electric Red", "channel": "Meshuggah", "duration": 201},
            {"youtube_id": "Cp31A_iqoDw", "title": "Electric Red (Live)", "channel": "Meshuggah", "duration": 200},
        ]

    def download(url, directory, **kwargs):
        attempts.append(url.rsplit("=", 1)[-1])
        audio = directory / "audio.m4a"
        if attempts[-1] == stale_id:
            audio.write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, "yt-dlp", stderr="ERROR: [youtube] Video unavailable")
        assert not audio.exists()
        audio.write_bytes(b"restored")
        return [str(audio)]

    monkeypatch.setattr(libraryRestore.musicSearch, "search_songs", find)
    monkeypatch.setattr(libraryRestore.playlistDownloader, "download_file_m4a", download)
    staging = tmp_path / ".app-trash"
    staging.mkdir()
    album = libraryRestore._restore_track(libraryRestore._catalog()[0], tmp_path, staging, threading.Event(), "m4a")
    assert attempts == [stale_id, replacement_id]
    assert (album / "01 - Electric Red.m4a").read_bytes() == b"restored"
    assert libraryRestore._catalog()[0]["youtube_id"] == replacement_id
