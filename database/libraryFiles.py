from pathlib import Path
import core.interfaceComponents as interfaceComponents
import core.audioTags as audioTags
import database.syncLibrary as syncLibrary

# The database doesn't store file paths, so a row's file is found the same
# way sync created the row: artist/album from the tags, track number and
# title from the file name. That also keeps working after files are moved
# or converted from FLAC to MP3 in place.
SONG_KEY_SQL = """
    SELECT art.artist_name, alb.album_name, s.track_number, s.song_title
    FROM songs s
    JOIN albums alb ON s.album_id = alb.album_id
    JOIN artists art ON alb.artist_id = art.artist_id
"""

def song_keys(cursor, where, params):
    """(artist, album, track_number, title) for each song row matching `where`."""
    cursor.execute(f"{SONG_KEY_SQL} WHERE {where}", params)
    return {(row[0], row[1], row[2] or 0, row[3]) for row in cursor.fetchall()}

def find_song_files(library_folder, keys):
    """
    Every audio file under library_folder that sync maps to one of `keys`.
    File names are checked first so only likely matches get their tags read.
    """
    keys = set(keys)
    names = {(track, title) for _, _, track, title in keys}
    matches = []
    for file_path in audioTags.find_audio_files(library_folder):
        track_num, title = syncLibrary.parse_filename(file_path)
        if (track_num, title) not in names:
            continue
        try:
            audio = audioTags.open_tags(file_path)
        except Exception as e:
            interfaceComponents.Print_Tag(f"Could not read tags of {file_path}: {e}", tag="Warning")
            continue
        if audio is not None and (*syncLibrary.read_artist_album(audio), track_num, title) in keys:
            matches.append(file_path)
    return matches

def delete_song_files(library_folder, keys):
    """
    Deletes the library files behind these song rows, then any folders that
    leaves empty (never the library folder itself). Raises OSError if a file
    can't be deleted, so the caller can keep the database rows.

    Returns:
        int: How many files were deleted.
    """
    root = Path(library_folder).resolve()
    files = find_song_files(library_folder, keys)
    for file_path in files:
        file_path.unlink()
        interfaceComponents.Print_Tag(f"Deleted file: {file_path}", tag="Cleanup")

    for folder in {f.parent.resolve() for f in files}:
        while folder != root and root in folder.parents and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    return len(files)
