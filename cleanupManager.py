import os
import re
from pathlib import Path
from mutagen.flac import FLAC
import database.databaseConnector as databaseConnector
import mainFiles.interfaceComponents as interfaceComponents

def cleanup_duplicate_files_by_folder(target_dir):
    """
    Scans a directory for duplicate FLAC files and enforces a specific folder hierarchy.
    
    The function uses audio metadata (tags) to identify duplicates. If a duplicate is 
    found, it prioritizes keeping the version located in a folder starting with 'Album -'.
    
    Args:
        target_dir (str): The root path to scan for FLAC files.
    """
    path = Path(target_dir)
    # rglob("*.flac") recursively finds all FLAC files in subdirectories
    flac_files = list(path.rglob("*.flac"))
    
    # Dictionary to track unique songs. 
    # Key: Fingerprint string | Value: pathlib.Path object of the file
    seen_songs = {} 
    deleted_count = 0

    interfaceComponents.Print_Tag(f"Scanning {target_dir} for folder-based duplicates...", tag="Process")

    for file_path in flac_files:
        try:
            # Load FLAC metadata tags
            audio = FLAC(file_path)
            
            # Extract tags with fallbacks to avoid KeyErrors
            artist = audio.get("artist", ["Unknown"])[0].strip().lower()
            album = audio.get("album", ["Unknown"])[0].strip().lower()
            # Handles track numbers like "01" or "01/12"
            track_num = audio.get("tracknumber", ["0"])[0].split('/')[0].strip()
            title = audio.get("title", [file_path.stem])[0].strip().lower()

            # Create a unique identifier based on song properties
            fingerprint = f"{artist}|{album}|{title}|{track_num}"
            parent_folder = file_path.parent.name

            if fingerprint in seen_songs:
                existing_file = seen_songs[fingerprint]
                existing_folder = existing_file.parent.name

                # --- DUPLICATE RESOLUTION LOGIC ---
                
                # CASE 1: The current file is in a generic folder, but the existing record is in an 'Album' folder.
                # Action: Delete the current file.
                if not parent_folder.startswith("Album -") and existing_folder.startswith("Album -"):
                    os.remove(file_path)
                    deleted_count += 1
                    interfaceComponents.Print_Tag(f"Deleted duplicate from non-album folder: {file_path.name}", tag="Cleanup")
                
                # CASE 2: The current file is in an 'Album' folder, but the existing record is NOT.
                # Action: Delete the previously seen file and update the record to the current (better) path.
                elif parent_folder.startswith("Album -") and not existing_folder.startswith("Album -"):
                    os.remove(existing_file)
                    seen_songs[fingerprint] = file_path # Keep the one in the proper album folder
                    deleted_count += 1
                    interfaceComponents.Print_Tag(f"Deleted duplicate from non-album folder: {existing_file.name}", tag="Cleanup")
            else:
                # If the song hasn't been seen yet, add it to the tracking dictionary
                seen_songs[fingerprint] = file_path

        except Exception as e:
            # Log errors for corrupted files or files with missing headers
            interfaceComponents.Print_Tag(f"Error processing {file_path.name}: {e}", tag="Error")

    # Wrap up and report findings
    interfaceComponents.Print_Tag(f"Physical Cleanup: Removed {deleted_count} duplicates.", tag="Success")