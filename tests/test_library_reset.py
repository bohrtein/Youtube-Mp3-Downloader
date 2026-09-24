import sqlite3

import database.databaseConnector as databaseConnector
import database.suggestionsRepo as suggestionsRepo


def add_song(conn, artist="Tool", album="Lateralus", title="Schism"):
    artist_id = conn.execute("INSERT INTO artists (artist_name) VALUES (?)", (artist,)).lastrowid
    album_id = conn.execute("INSERT INTO albums (album_name, artist_id) VALUES (?, ?)", (album, artist_id)).lastrowid
    conn.execute("INSERT INTO songs (song_title, album_id) VALUES (?, ?)", (title, album_id))
    return album_id


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_reset_library_empties_only_the_library(tmp_path, monkeypatch):
    covers = tmp_path / "covers"
    covers.mkdir()
    monkeypatch.setattr(databaseConnector, "COVERS_DIR", covers)

    conn = sqlite3.connect(databaseConnector.DB_PATH)
    album_id = add_song(conn)
    conn.execute("INSERT INTO settings (key, value) VALUES ('library_folder', 'E:\\')")
    conn.commit()
    conn.close()
    (covers / f"{album_id}.jpg").write_bytes(b"jpeg")
    friend = suggestionsRepo.create_friend("Keeps Their Link")

    backup_path = databaseConnector.reset_library()

    conn = sqlite3.connect(databaseConnector.DB_PATH)
    for table in ("songs", "albums", "artists"):
        assert count(conn, table) == 0, table
    assert count(conn, "settings") == 1
    assert count(conn, "friends") == 1
    assert suggestionsRepo.get_active_friend_by_token(friend["token"]) is not None
    assert not list(covers.glob("*.jpg"))

    # Ids restart at 1, so a rebuilt album can't pick up a stale cover filename.
    assert add_song(conn) == 1
    conn.close()

    backup = sqlite3.connect(backup_path)
    assert count(backup, "songs") == 1
    backup.close()
