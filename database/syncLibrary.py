import os
import re
import io
from pathlib import Path
from PIL import Image
import database.databaseConnector as databaseConnector
import core.interfaceComponents as interfaceComponents
import core.audioTags as audioTags

def Sync_Folder_To_Db(target_dir):
    """
    Scans the local storage and synchronizes song metadata into the SQL database.

    This function performs a deep scan of FLAC/MP3 files to extract technical data,
    metadata tags, and binary cover art, then maps them into a relational 
    structure (Artists -> Albums -> Songs).
    
    Args:
        target_dir (str): The root directory where downloads are stored.
    """
    # Initialize DB connection via the custom connector
    conn = databaseConnector.connect_to_db()
    if not conn:
        interfaceComponents.Print_Tag("Database connection failed.", tag="Error")
        return

    cursor = conn.cursor()
    covers_dir = Path(__file__).resolve().parent.parent / 'static' / 'covers'
    covers_dir.mkdir(parents=True, exist_ok=True)
    path = Path(target_dir)
    for file_path in audioTags.find_audio_files(path):
        try:
            audio = audioTags.open_tags(file_path)
            
            # --- 1. TRACK & TITLE PARSING ---
            # Logic: Attempt to extract track numbers from filenames (e.g., "01 - SongTitle")
            filename_raw = file_path.stem 
            track_num = 0
            song_title = filename_raw
            
            # Regex: Matches leading digits followed by a period, dash, or space
            track_match = re.match(r'^(\d+)(?:\s*[\.\-\s]\s*)', filename_raw)
            if track_match:
                track_num = int(track_match.group(1))
                song_title = filename_raw[track_match.end():].strip()

            # --- 2. TECHNICAL METADATA ---
            # FLAC doesn't expose a simple bitrate, so average it from file size and
            # duration (same formula for MP3 keeps the two comparable).
            duration = audio.info.length
            file_size_bits = os.path.getsize(file_path) * 8
            actual_bitrate = int((file_size_bits / duration) / 1000) if duration > 0 else 0
            bitrate_str = f"{actual_bitrate}kbps"
            
            # Metadata tag extraction with fallbacks
            artist_name = audio.get("artist", ["Unknown Artist"])[0].strip()
            album_name = audio.get("album", ["Unknown Album"])[0].strip()
            
            # Date handling: Extracts the first 4 characters to standardize as a Year (int)
            raw_date = audio.get("date", audio.get("year", [None]))[0]
            release_date = int(str(raw_date)[:4]) if raw_date else None
            file_ext = file_path.suffix.replace(".", "").upper()

            # --- URL EXTRACTION ---
            # Iterates through all metadata fields to find a source link (e.g., YouTube URL)
            source_url = None
            for val in audioTags.iter_tag_text(file_path):
                url_match = re.search(r'(https?://[^\s"\'<>]+)', str(val))
                if url_match:
                    source_url = url_match.group(1)
                    break

            # --- 3. ALBUM COVER PROCESSING ---
            # Extracts the first embedded picture and resizes it for the Web Dashboard
            cover_binary = None
            cover_bytes = audioTags.get_cover_bytes(file_path)
            if cover_bytes:
                img = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
                img = img.resize((250, 250), Image.LANCZOS)
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                cover_binary = img_byte_arr.getvalue()

            # --- 4. DATABASE SYNCHRONIZATION (UPSERT LOGIC) ---
            

            # Step A: Sync Artist
            cursor.execute("SELECT artist_id FROM artists WHERE artist_name = ?", (artist_name,))
            res = cursor.fetchone()
            artist_id = res[0] if res else None
            if not artist_id:
                cursor.execute("INSERT INTO artists (artist_name) VALUES (?)", (artist_name,))
                artist_id = cursor.lastrowid

            # Step B: Sync Album
            cursor.execute("SELECT album_id FROM albums WHERE album_name = ? AND artist_id = ?", (album_name, artist_id))
            album_res = cursor.fetchone()
            cover_path = None
            if album_res:
                album_id = album_res[0]
                cover_path = covers_dir / f"{album_id}.jpg"
            else:
                cursor.execute(
                    "INSERT INTO albums (album_name, release_date, artist_id) VALUES (?, ?, ?)",
                    (album_name, release_date, artist_id)
                )
                album_id = cursor.lastrowid
                cover_path = covers_dir / f"{album_id}.jpg"

            # Save/patch the cover image file for this album (skip if one already exists)
            if cover_binary and not cover_path.exists():
                cover_path.write_bytes(cover_binary)

            # Step C: Sync Song
            # Unique constraint check: Song title + Album ID + Track Number
            cursor.execute("""
                SELECT song_id, source_url, file_type FROM songs
                WHERE song_title = ? AND album_id = ? AND track_number = ?
            """, (song_title, album_id, track_num))

            song_res = cursor.fetchone()

            if not song_res:
                # Create a new song record
                cursor.execute("""
                    INSERT INTO songs (song_title, duration_seconds, track_number, album_id, release_date, bit_rate, file_type, source_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (song_title, int(duration), track_num, album_id, release_date, bitrate_str, file_ext, source_url))
                interfaceComponents.Print_Tag(f"Synced: {song_title} (Track {track_num})", tag="DB Success")
            else:
                # If song exists but URL is missing, update the record
                db_song_id, db_source_url, db_file_type = song_res
                if source_url and not db_source_url:
                    cursor.execute("UPDATE songs SET source_url = ? WHERE song_id = ?", (source_url, db_song_id))
                    interfaceComponents.Print_Tag(f"Patched URL for: {song_title} (Track {track_num})", tag="DB Update")
                # A FLAC converted to MP3 in place keeps its title/album/track,
                # so it lands here rather than as a new row.
                if db_file_type != file_ext:
                    cursor.execute("UPDATE songs SET file_type = ?, bit_rate = ? WHERE song_id = ?", (file_ext, bitrate_str, db_song_id))
                    interfaceComponents.Print_Tag(f"Updated format to {file_ext}: {song_title} (Track {track_num})", tag="DB Update")

        except Exception as e:
            interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")

    # Finalize all transactions and close the connection
    conn.commit()
    cursor.close()
    databaseConnector.disconnect_to_db(conn)

if __name__ == "__main__":
    # Default entry point for testing outside of the Flask app
    Sync_Folder_To_Db("downloads")