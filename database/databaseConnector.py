import sqlite3
from pathlib import Path
import core.interfaceComponents as interfaceComponents
import core.linkResolver as linkResolver

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
    youtube_id TEXT,
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

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Friend Suggestions: a friend's token is their whole identity.
CREATE TABLE IF NOT EXISTS friends (
    friend_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    revoked_at TEXT,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    friend_id INTEGER NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_review', 'done', 'rejected')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT,
    FOREIGN KEY (friend_id) REFERENCES friends(friend_id) ON DELETE CASCADE
);

-- Both the songs a friend kept (kept = 1) and the ones they unticked (kept = 0).
CREATE TABLE IF NOT EXISTS submission_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    kept INTEGER NOT NULL,
    source TEXT NOT NULL,
    youtube_id TEXT NOT NULL,
    title TEXT NOT NULL,
    channel TEXT,
    artist TEXT,
    album TEXT,
    track_number INTEGER,
    duration_seconds INTEGER,
    orig_youtube_id TEXT,
    sp_track_id TEXT,
    sp_title TEXT,
    sp_artist TEXT,
    sp_album TEXT,
    sp_duration_seconds INTEGER,
    flags TEXT NOT NULL DEFAULT '[]',
    in_library TEXT NOT NULL DEFAULT 'no' CHECK (in_library IN ('yes', 'maybe', 'no')),
    decision TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending', 'approved', 'skipped', 'downloading', 'downloaded', 'failed')),
    error TEXT,
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_submission_items_submission ON submission_items(submission_id);

-- yt-dlp / Spotify lookups, so repeated searches never hit YouTube twice.
CREATE TABLE IF NOT EXISTS lookup_cache (
    cache_key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

-- One row per rate-limited action (friend_id NULL = server-wide budget).
CREATE TABLE IF NOT EXISTS usage_events (
    friend_id INTEGER,
    kind TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_events_lookup ON usage_events(kind, friend_id, at);
"""

DEFAULT_LIBRARY_FOLDER = Path(__file__).resolve().parent.parent / 'downloads'

def connect_to_db():
    """
    Opens a connection to the local SQLite library database.

    Returns:
        sqlite3.Connection: A connection object with row_factory set so
        results can be accessed by column name (album['album_name']),
        matching how the templates already consume rows.
    """
    try:
        # Background jobs and request threads write concurrently; wait for
        # the lock instead of failing immediately with "database is locked".
        connection = sqlite3.connect(DB_PATH, timeout=15)
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
    _migrate(connection)
    connection.commit()
    connection.close()
    interfaceComponents.Print_Tag(f"Database ready at {DB_PATH}", tag="DB Success")

def _migrate(connection):
    """
    Brings databases created by older versions up to the current SCHEMA.
    CREATE TABLE IF NOT EXISTS never adds columns to an existing table, so
    new columns are added here, guarded by PRAGMA table_info.
    """
    song_columns = {row[1] for row in connection.execute("PRAGMA table_info(songs)")}
    if "youtube_id" not in song_columns:
        connection.execute("ALTER TABLE songs ADD COLUMN youtube_id TEXT")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_songs_youtube_id ON songs(youtube_id)")

    rows = connection.execute(
        "SELECT song_id, source_url FROM songs WHERE youtube_id IS NULL AND source_url IS NOT NULL"
    ).fetchall()
    for song_id, source_url in rows:
        video_id = linkResolver.extract_video_id(source_url)
        if video_id:
            connection.execute("UPDATE songs SET youtube_id = ? WHERE song_id = ?", (video_id, song_id))

def get_library_folder():
    """
    Returns the configured library/download folder as an absolute path
    string. Falls back to <project_root>/downloads if nothing has been
    set yet - the app's original default.
    """
    connection = sqlite3.connect(DB_PATH)
    row = connection.execute("SELECT value FROM settings WHERE key = 'library_folder'").fetchone()
    connection.close()
    if row and row[0]:
        return row[0]
    return str(DEFAULT_LIBRARY_FOLDER)

def set_library_folder(path):
    """
    Persists the chosen library/download folder.

    Args:
        path (str): An existing directory path.

    Raises:
        NotADirectoryError: If the given path is not an existing directory.
    """
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")

    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        "INSERT INTO settings (key, value) VALUES ('library_folder', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(resolved),)
    )
    connection.commit()
    connection.close()

def disconnect_to_db(connection):
    """
    Safely closes the given SQLite connection.

    Args:
        connection: The SQLite connection object to be closed.
    """
    if connection:
        connection.close()
