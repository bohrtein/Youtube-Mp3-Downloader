from pathlib import Path
import core.processAlbumCover as processAlbumCover
import core.playlistDownloader as playlistDownloader
import core.checkDependencies as checkDependencies
import core.interfaceComponents as interfaceComponents
import database.syncLibrary as syncLibrary
import core.cleanupManager as cleanupManager
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
    processAlbumCover.process_album_covers_loop_flac(databaseConnector.get_library_folder())
    program_exit()

def delete_already_exsisting_files():
    """
    Triggers the deduplication logic to clean up the storage directory.
    Identifies and removes files based on the 'Album -' folder priority.
    """
    cleanupManager.cleanup_duplicate_files_by_folder(databaseConnector.get_library_folder())

def start_downloading(url):
    """
    Direct interface for downloading a single URL or playlist.
    Typically called by the Flask/SocketIO background thread.

    Args:
        url (str): The YouTube/Media URL provided by the user.
    """
    file_paths = playlistDownloader.download_file_flac(url, databaseConnector.get_library_folder())
    if not file_paths:
        # See download_for_device: without this, a failed download (missing
        # yt-dlp, blocked video, etc.) is swallowed and the batch just
        # reports "complete" with nothing actually downloaded.
        raise RuntimeError(f"No file was downloaded for {url} — check the server log for the actual yt-dlp error.")

def download_for_device(url, staging_dir):
    """
    Downloads a URL into a temporary staging directory instead of the library
    folder, for the "download to my device" flow. Runs the same cover
    standardization and DB sync as the library flow, against that staging
    directory, so the track shows up in the library view even though the
    file itself never lands in the configured library folder.

    Args:
        url (str): The YouTube/Media URL provided by the user.
        staging_dir (str): Short-lived directory the file is downloaded into.

    Returns:
        list[str]: Absolute paths of the downloaded files, for the caller to
        stream back to the browser and then delete.
    """
    file_paths = playlistDownloader.download_file_flac(url, staging_dir)
    if not file_paths:
        # download_file_flac already printed the real reason (missing
        # yt-dlp, network failure, blocked video, etc.) via Print_Tag; raise
        # here so the caller's error handling actually surfaces a failure
        # instead of silently reporting "complete" with nothing downloaded.
        raise RuntimeError(f"No file was downloaded for {url} — check the server log for the actual yt-dlp error.")
    for file_path in file_paths:
        processAlbumCover.process_album_cover_flac(Path(file_path))
    syncLibrary.Sync_Folder_To_Db(staging_dir)
    return file_paths

def sync_to_library():
    """
    Updates the SQL database to reflect the current state of the download folder.
    Ensures dependencies (FFmpeg/FFprobe) are present for metadata reading.
    """
    checkDependencies.dependencies_check()
    syncLibrary.Sync_Folder_To_Db(databaseConnector.get_library_folder())

def process_songs():
    """
    Scans downloaded FLAC files to extract, resize, and store album
    artwork in the database for the web UI.
    """
    checkDependencies.dependencies_check()
    processAlbumCover.process_album_covers_loop_flac(databaseConnector.get_library_folder())

def program_exit():
    """
    Handles the graceful shutdown sequence of the application.
    """
    interfaceComponents.header_exit()

if __name__ == "__main__":
    # Execution begins here only if the script is run directly, 
    # not when imported by the Flask app.
    program_start()