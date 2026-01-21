import sys
import subprocess
from pathlib import Path

def download_playlist(url, output_dir="downloads"):
    output_template = f"{output_dir}/%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"

    cmd = [
        "./yt-dlp",
        "-ciw",
        "-x",
        #"--cookies-from-browser","firefox",
        "--audio-format", "flac",
        "--audio-quality", "0",
        "--embed-metadata",
        "--embed-thumbnail",
        "-o", output_template,
        url
    ]

    print(f"--- Downloading FLAC from: {url} ---")
    try:
        subprocess.run(cmd, check=True)
        print("\n--- Download Complete ---")
    except subprocess.CalledProcessError as e:
        print(f"Error during download: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python downloader.py <playlist_url>")
        sys.exit(1)

    download_playlist(sys.argv[1])