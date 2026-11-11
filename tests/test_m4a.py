import io
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from core import approvedDownloads, audioTags, playlistDownloader, restoreNetwork
from database import databaseConnector, syncLibrary


def test_m4a_download_selects_native_audio_and_uses_vpn(monkeypatch, tmp_path):
    monkeypatch.delenv("LIBRARY_RESTORE_VPN_PROXY", raising=False)
    with pytest.raises(restoreNetwork.VPNRotationError):
        playlistDownloader.download_file_m4a("video", tmp_path)

    monkeypatch.setenv("LIBRARY_RESTORE_VPN_PROXY", "http://localhost:8888")
    monkeypatch.setattr(playlistDownloader.checkDependencies, "ytdlp_command", lambda: ["yt-dlp"])

    def run(command, _):
        assert command[command.index("--proxy") + 1] == "http://localhost:8888"
        assert command[command.index("-f") + 1] == "bestaudio[ext=m4a][acodec^=mp4a]"
        assert "-x" not in command and "--audio-format" not in command
        assert "--embed-metadata" in command and "--embed-thumbnail" in command
        assert command[command.index("--convert-thumbnails") + 1] == "jpg"
        return "track.m4a\n"

    monkeypatch.setattr(playlistDownloader, "_run_download", run)
    assert playlistDownloader.download_file_m4a("video", tmp_path) == ["track.m4a"]


def test_m4a_tags_cover_and_source_survive_library_sync(tmp_path, monkeypatch):
    bundled = Path(__file__).resolve().parents[1] / "ffmpeg.exe"
    ffmpeg = shutil.which("ffmpeg") or (str(bundled) if bundled.is_file() else None)
    if ffmpeg is None:
        pytest.skip("ffmpeg is required to generate the M4A fixture")
    folder = tmp_path / "library"
    folder.mkdir()
    track = folder / "01 - Song.m4a"
    source = "https://music.youtube.com/watch?v=Cp31A_iqoDw"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "aac", "-metadata", f"comment={source}", str(track)], check=True)

    def audio_hash():
        return subprocess.check_output([ffmpeg, "-v", "error", "-i", str(track), "-map", "0:a",
                                        "-c:a", "copy", "-f", "hash", "-"])

    original = audio_hash()
    approvedDownloads.write_tags(track, {
        "artist": "Artist", "album_artist": "Artist", "album": "Album", "title": "Song",
        "track_number": 1, "disc_number": 1, "year": "2020", "genre": "Rock",
    })
    cover = io.BytesIO()
    Image.new("RGB", (32, 32), "blue").save(cover, format="JPEG")
    audioTags.set_cover_jpeg(track, cover.getvalue(), 32)
    assert audioTags.get_cover_bytes(track) == cover.getvalue()
    assert audio_hash() == original
    monkeypatch.setattr(syncLibrary, "__file__", str(tmp_path / "database" / "syncLibrary.py"))
    syncLibrary.Sync_Folder_To_Db(str(folder))
    with databaseConnector.connect_to_db() as conn:
        record = conn.execute("SELECT song_title, track_number, file_type, source_url FROM songs").fetchone()
    assert tuple(record) == ("Song", 1, "M4A", source)
    assert (tmp_path / "static" / "covers" / "1.jpg").is_file()
