import sqlite3

import pytest

import core.audioTags as audioTags
import database.databaseConnector as databaseConnector
from conftest import ADMIN_HEADERS
from helpers import add_library_song


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A library folder whose files are tagged by their folder: <artist>/<album>/<file>."""
    root = tmp_path / "music"
    root.mkdir()
    databaseConnector.set_library_folder(str(root))
    monkeypatch.setattr(audioTags, "open_tags", lambda path: {
        "artist": [path.parent.parent.name], "album": [path.parent.name],
    })

    def add_file(artist, album, name):
        path = root / artist / album / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
        return path
    return root, add_file


def ids(title):
    conn = sqlite3.connect(databaseConnector.DB_PATH)
    row = conn.execute("SELECT song_id, album_id FROM songs WHERE song_title = ?", (title,)).fetchone()
    conn.close()
    return row


def test_delete_song_removes_its_file_only(client, library):
    root, add_file = library
    add_library_song("Schism", "Tool", "Lateralus")
    add_library_song("Parabola", "Tool", "Lateralus")
    schism = add_file("Tool", "Lateralus", "01 - Schism.flac")
    parabola = add_file("Tool", "Lateralus", "01 - Parabola.mp3")
    same_name_other_album = add_file("Tool", "Aenima", "01 - Schism.flac")

    response = client.delete(f"/delete_song/{ids('Schism')[0]}", headers=ADMIN_HEADERS)

    assert response.get_json()["success"]
    assert not schism.exists()
    assert parabola.exists()
    assert same_name_other_album.exists()
    assert ids("Schism") is None


def test_delete_album_removes_files_and_empty_folders(client, library):
    root, add_file = library
    add_library_song("Schism", "Tool", "Lateralus")
    add_library_song("Parabola", "Tool", "Lateralus")
    add_file("Tool", "Lateralus", "01 - Schism.flac")
    add_file("Tool", "Lateralus", "01 - Parabola.flac")

    response = client.delete(f"/delete_album/{ids('Schism')[1]}", headers=ADMIN_HEADERS)

    assert response.get_json()["success"]
    assert not (root / "Tool").exists()
    assert root.exists()
    assert ids("Schism") is None and ids("Parabola") is None


def test_rows_stay_when_a_file_cannot_be_deleted(client, library, monkeypatch):
    root, add_file = library
    add_library_song("Schism", "Tool", "Lateralus")
    add_file("Tool", "Lateralus", "01 - Schism.flac")

    def locked(self, *args, **kwargs):
        raise PermissionError("file is in use")
    monkeypatch.setattr("pathlib.Path.unlink", locked)

    response = client.delete(f"/delete_song/{ids('Schism')[0]}", headers=ADMIN_HEADERS)

    assert response.status_code == 500
    assert ids("Schism") is not None
