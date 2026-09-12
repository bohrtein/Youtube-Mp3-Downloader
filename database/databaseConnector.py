import sqlite3
from pathlib import Path
import core.interfaceComponents as interfaceComponents

# Single-file SQLite database at the project root - no server, no .env setup
DB_PATH = Path(__file__).resolve().parent.parent / 'library.db'

SCHEMA = """
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
"""

def connect_to_db():
    """
    Opens a connection to the local SQLite library database.

    Returns:
        sqlite3.Connection: A connection object with row_factory set so
        results can be accessed by column name (album['album_name']),
        matching how the templates already consume rows.
    """
    try:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except sqlite3.Error as e:
        interfaceComponents.Print_Tag(f"Connection failed: {e}", tag="DB Error")
        return None

def init_db():
    """
    Creates the database file and schema on first run. Safe to call on
    every app startup - all statements are idempotent (IF NOT EXISTS).
    """
    connection = sqlite3.connect(DB_PATH)
    connection.executescript(SCHEMA)
    connection.commit()
    connection.close()
    interfaceComponents.Print_Tag(f"Database ready at {DB_PATH}", tag="DB Success")

def disconnect_to_db(connection):
    """
    Safely closes the given SQLite connection.

    Args:
        connection: The SQLite connection object to be closed.
    """
    if connection:
        connection.close()
