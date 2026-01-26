import os
import re
import io
from pathlib import Path
from PIL import Image
from mutagen.flac import FLAC
import database.databaseConnector as databaseConnector  
import core.interfaceComponents as interfaceComponents

def Sync_Folder_To_Db(target_dir):
    """
    Scans the local storage and synchronizes song metadata into the SQL database.
    
    This function performs a deep scan of FLAC files to extract technical data, 
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
    
    # buffered=True allows us to perform multiple sub-queries while iterating
    cursor = conn.cursor(buffered=True)
    path = Path(target_dir)
    flac_files = list(path.rglob("*.flac"))

    for file_path in flac_files:
        try:
            # Load FLAC metadata object
            audio = FLAC(file_path)
            
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
            # FLAC technicals aren't always provided as a simple bitrate; we calculate 
            # the average bitrate based on file size and duration.
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
            for tag_name, values in audio.items():
                for val in values:
                    url_match = re.search(r'(https?://[^\s"\'<>]+)', str(val))
                    if url_match:
                        source_url = url_match.group(1)
                        break
                if source_url: break

            # --- 3. ALBUM COVER PROCESSING ---
            # Extracts the first embedded picture and resizes it for the Web Dashboard
            cover_binary = None
            if audio.pictures:
                img = Image.open(io.BytesIO(audio.pictures[0].data))
                img = img.resize((250, 250), Image.LANCZOS)
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                cover_binary = img_byte_arr.getvalue()

            # --- 4. DATABASE SYNCHRONIZATION (UPSERT LOGIC) ---
            

            # Step A: Sync Artist
            cursor.execute("SELECT artist_id FROM artists WHERE artist_name = %s", (artist_name,))
            res = cursor.fetchone()
            artist_id = res[0] if res else None
            if not artist_id:
                cursor.execute("INSERT INTO artists (artist_name) VALUES (%s)", (artist_name,))
                artist_id = cursor.lastrowid

            # Step B: Sync Album
            cursor.execute("SELECT album_id FROM albums WHERE album_name = %s AND artist_id = %s", (album_name, artist_id))
            album_res = cursor.fetchone()
            if album_res:
                album_id = album_res[0]
                # If the album exists but has no cover, patch it with the new binary
                if cover_binary:
                    cursor.execute("UPDATE albums SET cover_data = %s WHERE album_id = %s AND cover_data IS NULL", (cover_binary, album_id))
            else:
                cursor.execute(
                    "INSERT INTO albums (album_name, release_date, artist_id, cover_data) VALUES (%s, %s, %s, %s)", 
                    (album_name, release_date, artist_id, cover_binary)
                )
                album_id = cursor.lastrowid

            # Step C: Sync Song
            # Unique constraint check: Song title + Album ID + Track Number
            cursor.execute("""
                SELECT song_id, source_url FROM songs 
                WHERE song_title = %s AND album_id = %s AND track_number = %s
            """, (song_title, album_id, track_num))
            
            song_res = cursor.fetchone()
            
            if not song_res:
                # Create a new song record
                cursor.execute("""
                    INSERT INTO songs (song_title, duration_seconds, track_number, album_id, release_date, bit_rate, file_type, source_url) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (song_title, int(duration), track_num, album_id, release_date, bitrate_str, file_ext, source_url))
                interfaceComponents.Print_Tag(f"Synced: {song_title} (Track {track_num})", tag="DB Success")
            else:
                # If song exists but URL is missing, update the record
                db_song_id, db_source_url = song_res
                if source_url and not db_source_url:
                    cursor.execute("UPDATE songs SET source_url = %s WHERE song_id = %s", (source_url, db_song_id))
                    interfaceComponents.Print_Tag(f"Patched URL for: {song_title} (Track {track_num})", tag="DB Update")

        except Exception as e:
            interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")

    # Finalize all transactions and close the connection
    conn.commit()
    cursor.close()
    databaseConnector.disconnect_to_db(conn)

if __name__ == "__main__":
    # Default entry point for testing outside of the Flask app
    Sync_Folder_To_Db("downloads")