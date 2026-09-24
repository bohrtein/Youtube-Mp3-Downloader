import core.processAlbumCover as processAlbumCover
import core.playlistDownloader as playlistDownloader
import core.checkDependencies as checkDependencies
import core.interfaceComponents as interfaceComponents
import database.syncLibrary as syncLibrary
import core.cleanupManager as cleanupManager
import core.convertToMp3 as convertToMp3
import database.databaseConnector as databaseConnector

def program_start():
    """
    The standard CLI entry point for the application.

    Orchestrates the full linear workflow:
    1. UI Greeting -> 2. Dependency Check -> 3. Download -> 4. Image Processing
    """
    interfaceComponents.header_start()
    checkDependencies.dependencies_check()
    playlistDownloader.initiate_playlist_loop()
    processAlbumCover.process_album_covers_loop(databaseConnector.get_library_folder())
    program_exit()

def delete_already_exsisting_files():
    """
    Triggers the deduplication logic to clean up the storage directory.
    Identifies and removes files based on the 'Album -' folder priority.
    """
    cleanupManager.cleanup_duplicate_files_by_folder(databaseConnector.get_library_folder())

def start_downloading(url, audio_format="flac"):
    """
    Direct interface for downloading a single URL or playlist.
    Typically called by the Flask/SocketIO background thread.

    Args:
        url (str): The YouTube/Media URL provided by the user.
        audio_format (str): "flac" (default, lossless) or "mp3" (320kbps/48kHz,
            for players where FLAC decoding drains the battery faster).
    """
    download_fn = playlistDownloader.download_file_mp3 if audio_format == "mp3" else playlistDownloader.download_file_flac
    file_paths = download_fn(url, databaseConnector.get_library_folder())
    if not file_paths:
        # download_file_flac already printed the real reason (missing
        # yt-dlp, network failure, blocked video, etc.) via Print_Tag; raise
        # here so the caller's error handling actually surfaces a failure
        # instead of silently reporting "complete" with nothing downloaded.
        raise RuntimeError(f"No file was downloaded for {url} — check the server log for the actual yt-dlp error.")

def sync_to_library():
    """
    Updates the SQL database to reflect the current state of the download folder.
    Ensures dependencies (FFmpeg/FFprobe) are present for metadata reading.
    """
    checkDependencies.dependencies_check()
    syncLibrary.Sync_Folder_To_Db(databaseConnector.get_library_folder())

def convert_library_to_mp3():
    """
    Transcodes every FLAC file in the library folder to MP3 (320kbps,
    48000Hz) in place, deleting each FLAC once its MP3 replacement is
    written. Does not re-download anything. Re-syncs the database afterwards
    so existing song rows pick up the new MP3 file type/bitrate.
    """
    checkDependencies.dependencies_check()
    convertToMp3.convert_library_to_mp3(databaseConnector.get_library_folder())
    syncLibrary.Sync_Folder_To_Db(databaseConnector.get_library_folder())

def process_songs():
    """
    Scans downloaded FLAC/MP3 files to extract, resize, and store album
    artwork in the database for the web UI.
    """
    checkDependencies.dependencies_check()
    processAlbumCover.process_album_covers_loop(databaseConnector.get_library_folder())

def program_exit():
    """
    Handles the graceful shutdown sequence of the application.
    """
    interfaceComponents.header_exit()

if __name__ == "__main__":
    # Execution begins here only if the script is run directly, 
    # not when imported by the Flask app.
    program_start()