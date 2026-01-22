import io
import sys
import subprocess
import zipfile  # Needed for unzipping
from pathlib import Path
from PIL import Image
from mutagen.flac import FLAC, Picture

def startProgram000():
    """Main entry point that orchestrates the program flow."""
    startHeader100()
    checkDependencies101()
    initiatePlaylistDownloader102()
    processAlbumCovers103()
    exit104()

def print001(message, tag="System"):
    """Custom print function with centered 14-character tags."""
    formatted_tag = f"[{tag:^14}]"
    print(f"{formatted_tag} {message}")

def startHeader100():
    """Displays the visual ASCII header at launch."""
    print("=======================================")
    print("   YouTube Playlist Downloader (FLAC)  ")
    print("=======================================") 

def checkDependencies101():
    """Triggers individual checks for required tools and handles unzipping."""
    checkYtdlp200()
    checkFfprobe201()
    checkFfmpeg202()
    print001("Dependencies verified.", tag="Success")

def initiatePlaylistDownloader102():
    """Collects URLs into an array and downloads them on 'exit'."""
    url_list = []
    while True:
        print001("Enter URL to queue (or type 'exit' to start downloads):", tag="Input")
        user_input = input("> ").strip()
        
        if user_input.lower() in ['exit', 'quit', 'q', 'e']:
            if not url_list:
                print001("No URLs provided. Exiting.", tag="System")
                break
            
            print001(f"Starting batch download of {len(url_list)} items...", tag="Batch Start")
            for index, url in enumerate(url_list, 1):
                print001(f"Item {index}/{len(url_list)}", tag="Queue")
                downloadPlaylist204(url)
            
            print001("All queued downloads finished.", tag="Batch Finish")
            break
        
        if user_input:
            url_list.append(user_input)
            print001(f"Added to queue. (Total: {len(url_list)})", tag="Queued")
        else:
            print001("Please enter a valid URL.", tag="Warning")

def processAlbumCovers103(target_dir="downloads"):
    """Standardizes FLAC artwork to 250x250 JPEG."""
    path = Path(target_dir)
    print001(f"Processing FLAC Artwork in: {path.absolute()}", tag="System")
    files = list(path.rglob("*.flac"))
    if not files:
        print001("No FLAC files found to process.", tag="Warning")
        return
    for flac_file in files:
        processFlacCover205(flac_file)

def exit104():
    """Handles final message."""
    print("Thank you for using the program")
    print("Made by bohrtein")
    input("Press Enter to close...")

def checkYtdlp200():
    """Verifies yt-dlp.exe (No unzip needed for this .exe)."""
    print001("Verifying yt-dlp.exe", tag="System")
    if not Path("./yt-dlp.exe").exists():
        print001("yt-dlp.exe not found.", tag="Warning")
        try:
             donwnloadPackage300("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe -o yt-dlp.exe")
             print001("yt-dlp.exe downloaded.", tag="Success")
        except Exception as e:
             print001(f"Error: {e}", tag="Error")
    else:
        print001("yt-dlp.exe verified!", tag="Success")

def checkFfprobe201():
    """Verifies ffprobe.exe; downloads and unzips if missing."""
    print001("Verifying ffprobe.exe", tag="System")
    if not Path("./ffprobe.exe").exists():
        print001("ffprobe.exe not found.", tag="Warning")
        try:
             donwnloadPackage300('https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffprobe-4.4.1-win-64.zip -o ffprobe.zip')
             unzipAndCleanup301("ffprobe.zip")
             print001("ffprobe.exe ready.", tag="Success")
        except Exception as e:
             print001(f"Error: {e}", tag="Error")
    else:
        print001("ffprobe.exe verified!", tag="Success")

def checkFfmpeg202():
    """Verifies ffmpeg.exe; downloads and unzips if missing."""
    print001("Verifying ffmpeg.exe", tag="System")
    if not Path("./ffmpeg.exe").exists():
        print001("ffmpeg.exe not found.", tag="Warning")
        try:
             donwnloadPackage300("https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip -o ffmpeg.zip")
             unzipAndCleanup301("ffmpeg.zip")
             print001("ffmpeg.exe ready.", tag="Success")
        except Exception as e:
             print001(f"Error: {e}", tag="Error")
    else:
        print001("ffmpeg.exe verified!", tag="Success")

def downloadPlaylist204(url, output_dir="downloads"):
    """Downloads audio via yt-dlp."""
    output_template = f"{output_dir}/%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"
    cmd = ["./yt-dlp.exe", "-ciw", "-x", "--audio-format", "flac", "--audio-quality", "0", 
           "--embed-metadata", "--embed-thumbnail", "-o", output_template, url]
    print001(f"Downloading: {url}", tag="Process")
    try:
        subprocess.run(cmd, check=True)
        print001("Download Complete", tag="Success")
    except Exception as e:
        print001(f"Error: {e}", tag="Error")

def processFlacCover205(file_path):
    """Crops and resizes FLAC artwork."""
    try:
        audio = FLAC(file_path)
        if not audio.pictures: return
        img = Image.open(io.BytesIO(audio.pictures[0].data))
        if img.size == (250, 250): return
        
        print001(f"Resizing {file_path.name}", tag="Processing")
        min_dim = min(img.size)
        left = (img.width - min_dim) / 2
        top = (img.height - min_dim) / 2
        img = img.crop((left, top, left + min_dim, top + min_dim)).resize((250, 250), Image.LANCZOS)
        
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG')
        audio.clear_pictures()
        picture = Picture()
        picture.data = img_byte_arr.getvalue()
        picture.type, picture.mime, picture.width, picture.height, picture.depth = 3, "image/jpeg", 250, 250, 24
        audio.add_picture(picture)
        audio.save()
    except Exception as e:
        print001(f"Artwork Error: {e}", tag="Error")

def donwnloadPackage300(downloadLink):
    """Utility to run curl."""
    subprocess.run("curl -L " + downloadLink, check=True)

def unzipAndCleanup301(zip_name):
    """
    New function: Unzips the specified file and deletes the .zip archive.
    """
    zip_path = Path(zip_name)
    if zip_path.exists():
        print001(f"Unzipping {zip_name}...", tag="Extracting")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(".")
        zip_path.unlink() # This deletes the .zip file
        print001(f"Deleted {zip_name}", tag="Cleanup")

if __name__ == "__main__":
    startProgram000()