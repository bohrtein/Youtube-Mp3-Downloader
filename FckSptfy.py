import io
import sys
import subprocess
from pathlib import Path
from PIL import Image
from mutagen.flac import FLAC, Picture





def startProgram000():
    startHeader100()
    checkDependencies101()
    initiatePlaylistDownloader102()
    processAlbumCovers103()
    Exit104()

def startHeader100():
    print("=======================================")
    print("   YouTube Playlist Downloader (FLAC)  ")
    print("=======================================")

def checkDependencies101():
    """Checks if yt-dlp.exe exists in the current directory."""
    if not Path("./yt-dlp.exe").exists():
        print("[Warning]: yt-dlp.exe not found in the current folder.")
    else:
        print("[System]: Dependencies verified.")

def initiatePlaylistDownloader102():
    while True:
        print("\nEnter URL to download (or type 'exit' to quit):")
        user_input = input("> ").strip()
        
        if user_input.lower() in ['exit', 'quit', 'q','e']:
            print("Exiting downloader.")
            break
        
        if user_input:
           downloadPlaylist204(user_input)
        else:
            print("Please enter a valid URL.")

def processAlbumCovers103(target_dir="downloads"):
    path = Path(target_dir)
    print(f"\n--- Processing FLAC Artwork in: {path.absolute()} ---")
    
    files = list(path.rglob("*.flac"))
    if not files:
        print("No FLAC files found to process.")
        return

    for flac_file in files:
        processFlacCover205(flac_file)

def Exit104():
    print("\nThank you for using the program")
    print("Made by bohrtein")
    input("Press Enter to close...")

def downloadPlaylist204(url, output_dir="downloads"):
    # Reference the local yt-dlp.exe
    output_template = f"{output_dir}/%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"

    cmd = [
        "./yt-dlp.exe",
        "-ciw",
        "-x",
        "--audio-format", "flac",
        "--audio-quality", "0",
        "--embed-metadata",
        "--embed-thumbnail",
        "-o", output_template,
        url
    ]
    print(f"\n--- Downloading FLAC from: {url} ---")
    try:
        subprocess.run(cmd, check=True)
        print("\n--- Download Complete ---")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error during download: {e}")
        return False
    
def processFlacCover205(file_path):
    """Checks if cover is 250x250; if not, crops/resizes to 250x250 JPEG."""
    try:
        audio = FLAC(file_path)

        if not audio.pictures:
            print(f"  [Skipping]: No image found in {file_path.name}")
            return
        
        # Get original image data
        raw_data = audio.pictures[0].data
        img = Image.open(io.BytesIO(raw_data))
        width, height = img.size

        # --- NEW IF CHECK ---
        # If it's already exactly 250x250, skip processing
        if width == 250 and height == 250:
            print(f"  [Skipping]: {file_path.name}")
            return

        print(f"  [Processing]: {file_path.name} ({width}x{height} -> 250x250)")
        
        # 1. Square Crop (Center-based)
        min_dim = min(width, height)
        left = (width - min_dim) / 2
        top = (height - min_dim) / 2
        right = (width + min_dim) / 2
        bottom = (height + min_dim) / 2
        img = img.crop((left, top, right, bottom))
        
        # 2. Resize to 250x250
        img = img.resize((250, 250), Image.LANCZOS)

        # 3. Save to JPEG bytes
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', optimize=True)

        # 4. Clear old and add new clean Picture block
        audio.clear_pictures()
        picture = Picture()
        picture.data = img_byte_arr.getvalue()
        picture.type = 3 # Front Cover
        picture.mime = "image/jpeg"
        picture.width = 250
        picture.height = 250
        picture.depth = 24

        audio.add_picture(picture)
        audio.save()
        print(f"  [Success]: {file_path.name} updated to 250px JPEG")

    except Exception as e:
        print(f"  [Error]: {file_path.name} -> {e}")

if __name__ == "__main__":
    startProgram000()