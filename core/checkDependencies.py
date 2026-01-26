import zipfile  
import subprocess
from pathlib import Path
import core.interfaceComponents as interfaceComponents

def dependencies_check():
    """
    Orchestrates the verification of all external binaries required for the app.
    Checks for yt-dlp, ffprobe, and ffmpeg sequentially.
    """
    check_ytdlp()
    check_ffprobe()
    check_ffmpeg()
    interfaceComponents.Print_Tag("Dependencies verified.", tag="Success")

def check_ytdlp():
    """
    Ensures yt-dlp.exe is present in the root directory.
    Downloads the standalone executable directly from GitHub if missing.
    """
    interfaceComponents.Print_Tag("Verifying yt-dlp.exe", tag="System")
    if not Path("./yt-dlp.exe").exists():
        interfaceComponents.Print_Tag("yt-dlp.exe not found.", tag="Warning")
        try:
             # yt-dlp is provided as a direct .exe, so no unzipping is required
             download_package("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe -o yt-dlp.exe")
             interfaceComponents.Print_Tag("yt-dlp.exe downloaded.", tag="Success")
        except Exception as e:
             interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
    else:
        interfaceComponents.Print_Tag("yt-dlp.exe verified!", tag="Success")

def check_ffprobe():
    """
    Ensures ffprobe.exe is present. 
    Downloads the zipped binary from ffbinaries and extracts it if missing.
    """
    interfaceComponents.Print_Tag("Verifying ffprobe.exe", tag="System")
    if not Path("./ffprobe.exe").exists():
        interfaceComponents.Print_Tag("ffprobe.exe not found.", tag="Warning")
        try:
             download_package('https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffprobe-4.4.1-win-64.zip -o ffprobe.zip')
             unzip_and_cleanup("ffprobe.zip")
             interfaceComponents.Print_Tag("ffprobe.exe ready.", tag="Success")
        except Exception as e:
             interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
    else:
        interfaceComponents.Print_Tag("ffprobe.exe verified!", tag="Success")

def check_ffmpeg():
    """
    Ensures ffmpeg.exe is present. 
    Downloads the zipped binary from ffbinaries and extracts it if missing.
    """
    interfaceComponents.Print_Tag("Verifying ffmpeg.exe", tag="System")
    if not Path("./ffmpeg.exe").exists():
        interfaceComponents.Print_Tag("ffmpeg.exe not found.", tag="Warning")
        try:
             download_package("https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip -o ffmpeg.zip")
             unzip_and_cleanup("ffmpeg.zip")
             interfaceComponents.Print_Tag("ffmpeg.exe ready.", tag="Success")
        except Exception as e:
             interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
    else:
        interfaceComponents.Print_Tag("ffmpeg.exe verified!", tag="Success")

def download_package(download_link):
    """
    Invokes the system's 'curl' command to fetch files from the web.
    
    Args:
        download_link (str): The URL and output flags for the curl command.
    """
    # -L follows redirects, which is necessary for GitHub release downloads
    subprocess.run("curl -L " + download_link, check=True)

def unzip_and_cleanup(zip_name):
    """
    Extracts all contents of a zip file to the current directory and 
    removes the original archive to save space.
    
    Args:
        zip_name (str): The filename of the zip archive (e.g., 'ffmpeg.zip').
    """
    zip_path = Path(zip_name)
    if zip_path.exists():
        interfaceComponents.Print_Tag(f"Unzipping {zip_name}...", tag="Extracting")
        
        # Open and extract the zip archive
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(".")
            
        # Delete the zip file after successful extraction
        zip_path.unlink() 
        interfaceComponents.Print_Tag(f"Deleted {zip_name}", tag="Cleanup")