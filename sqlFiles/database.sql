-- SQLite schema for the local music library.
-- Reference only: app.py calls database/databaseConnector.py's init_db()
-- automatically on startup, which runs the equivalent of this file against
-- library.db (created at the project root) - no manual setup required.

CREATE TABLE IF NOT EXISTS artists (
    artist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_name TEXT NOT NULL UNIQUE,
    bio TEXT
);

CREATE TABLE IF NOT EXISTS albums (
    album_id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_name TEXT NOT NULL,
    release_date INTEGER,
    artist_id INTEGER,
    FOREIGN KEY (artist_id) REFERENCES artists(artist_id) ON DELETE CASCADE,
    UNIQUE (album_name, artist_id)
);

CREATE TABLE IF NOT EXISTS songs (
    song_id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_title TEXT NOT NULL,
    duration_seconds INTEGER,
    track_number INTEGER,
    album_id INTEGER,
    release_date INTEGER,
    bit_rate TEXT,
    file_type TEXT,
    source_url TEXT,
    FOREIGN KEY (album_id) REFERENCES albums(album_id) ON DELETE CASCADE,
    UNIQUE (song_title, album_id)
);

CREATE VIEW IF NOT EXISTS album_gallery AS
SELECT
    alb.album_id,
    alb.album_name,
    art.artist_name,
    alb.release_date
FROM albums alb
JOIN artists art ON alb.artist_id = art.artist_id
ORDER BY alb.release_date DESC;

-- Album covers are NOT stored in this database. They live on disk at
-- static/covers/<album_id>.jpg and are served directly by Flask's static
-- file handler.
