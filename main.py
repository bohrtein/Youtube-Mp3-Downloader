import mainFiles.processAlbumCover as processAlbumCover
import mainFiles.playlistDownloader as playlistDownloader
import mainFiles.checkDependencies as checkDependencies
import mainFiles.interfaceComponents as interfaceComponents
import database.syncLibrary as syncLibrary
import mainFiles.cleanupManager as cleanupManager

# Global configuration: The root directory for all media downloads
output_dir = 'downloads'

def program_start():
    """
    The standard CLI entry point for the application.
    
    Orchestrates the full linear workflow:
    1. UI Greeting -> 2. Dependency Check -> 3. Download -> 4. Image Processing
    """
    interfaceComponents.header_start()
    checkDependencies.dependencies_check()
    playlistDownloader.initiate_playlist_loop()
    processAlbumCover.process_album_covers_loop_flac(output_dir)
    program_exit()

def delete_already_exsisting_files():
    """
    Triggers the deduplication logic to clean up the storage directory.
    Identifies and removes files based on the 'Album -' folder priority.
    """
    cleanupManager.cleanup_duplicate_files_by_folder(output_dir)
    
def start_downloading(url):
    """
    Direct interface for downloading a single URL or playlist.
    Typically called by the Flask/SocketIO background thread.
    
    Args:
        url (str): The YouTube/Media URL provided by the user.
    """
    playlistDownloader.download_file_flac(url, output_dir)

def sync_to_library():
    """
    Updates the SQL database to reflect the current state of the download folder.
    Ensures dependencies (FFmpeg/FFprobe) are present for metadata reading.
    """
    checkDependencies.dependencies_check()
    syncLibrary.Sync_Folder_To_Db(output_dir)

def process_songs():
    """
    Scans downloaded FLAC files to extract, resize, and store album 
    artwork in the database for the web UI.
    """
    checkDependencies.dependencies_check()
    processAlbumCover.process_album_covers_loop_flac(output_dir)

def program_exit():
    """
    Handles the graceful shutdown sequence of the application.
    """
    interfaceComponents.header_exit()

if __name__ == "__main__":
    # Execution begins here only if the script is run directly, 
    # not when imported by the Flask app.
    program_start()