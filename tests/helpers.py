def add_library_song(title, artist, album, youtube_id=None):
    import database.databaseConnector as databaseConnector
    conn = databaseConnector.connect_to_db()
    conn.execute("INSERT OR IGNORE INTO artists (artist_name) VALUES (?)", (artist,))
    artist_id = conn.execute("SELECT artist_id FROM artists WHERE artist_name = ?", (artist,)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO albums (album_name, artist_id) VALUES (?, ?)", (album, artist_id))
    album_id = conn.execute("SELECT album_id FROM albums WHERE album_name = ? AND artist_id = ?", (album, artist_id)).fetchone()[0]
    conn.execute(
        "INSERT INTO songs (song_title, album_id, track_number, duration_seconds, youtube_id, source_url) VALUES (?, ?, 1, 200, ?, ?)",
        (title, album_id, youtube_id, f"https://www.youtube.com/watch?v={youtube_id}" if youtube_id else None),
    )
    conn.commit()
    conn.close()
