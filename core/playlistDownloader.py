import core.interfaceComponents as interfaceComponents
import core.checkDependencies as checkDependencies
import subprocess

def initiate_playlist_loop():
    """
    Provides a Command Line Interface (CLI) for batching multiple URLs.
    
    Users can input several URLs one by one to create a queue. Once the user 
    types 'exit', the script iterates through the collected list and 
    processes each download sequentially.
    """
    url_list = []
    while True:
        interfaceComponents.Print_Tag("Enter URL to queue (or type 'exit' to start downloads):", tag="Input")
        user_input = input("> ").strip()
        
        # Check for various exit commands to start processing the queue
        if user_input.lower() in ['exit', 'quit', 'q', 'e']:
            if not url_list:
                interfaceComponents.Print_Tag("No URLs provided. Exiting.", tag="System")
                break
            
            interfaceComponents.Print_Tag(f"Starting batch download of {len(url_list)} items...", tag="Batch Start")
            
            # Process the queue using enumeration for progress tracking
            for index, url in enumerate(url_list, 1):
                interfaceComponents.Print_Tag(f"Item {index}/{len(url_list)}", tag="Queue")
                # Note: Assuming default output_dir here if called from CLI loop
                download_file_flac(url, "downloads") 
            
            interfaceComponents.Print_Tag("All queued downloads finished.", tag="Batch Finish")
            break
        
        # Add valid input to the list
        if user_input:
            url_list.append(user_input)
            interfaceComponents.Print_Tag(f"Added to queue. (Total: {len(url_list)})", tag="Queued")
        else:
            interfaceComponents.Print_Tag("Please enter a valid URL.", tag="Warning")

PLAYLIST_FILE_TEMPLATE = "%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"

def download_file_flac(url, output_dir, file_template=PLAYLIST_FILE_TEMPLATE):
    """
    Executes the yt-dlp binary to download and convert a specific URL.

    This function configures yt-dlp for high-quality FLAC extraction and
    sets a specific directory structure for playlists.

    Args:
        url (str): The video or playlist link.
        output_dir (str): The base directory for file storage.
        file_template (str): yt-dlp output template, relative to output_dir.
            The default names playlist items "Playlist Title/01 - Title.flac".

    Returns:
        list[str]: Absolute paths of the files yt-dlp produced (empty on failure).
    """
    output_template = f"{output_dir}/{file_template}"

    # Command Arguments:
    # -c: continue | -i: ignore errors | -w: no overwrites | -x: extract audio
    # --print after_move:filepath reports the final on-disk path for each item,
    # which callers need to stream/tag the file without re-scanning the folder.
    cmd = [
        checkDependencies.resolve_ytdlp(), "-ciw", "-x",
        "--audio-format", "flac",
        "--audio-quality", "0",
        "--embed-metadata", "--embed-thumbnail",
        "--print", "after_move:filepath",
        "-o", output_template, "--", url
    ]

    interfaceComponents.Print_Tag(f"Downloading: {url}", tag="Process")

    try:
        # check=True will raise a CalledProcessError if the command fails
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        interfaceComponents.Print_Tag("Download Complete", tag="Success")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception as e:
        # Captures network issues, missing binaries, or invalid URLs
        interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
        return []

def download_file_mp3(url, output_dir, file_template=PLAYLIST_FILE_TEMPLATE):
    """
    Same as download_file_flac, but extracts straight to MP3 (320kbps,
    48000Hz) instead of FLAC, so the result is already player-friendly
    without a separate conversion pass.

    Args:
        url (str): The video or playlist link.
        output_dir (str): The base directory for file storage.
        file_template (str): yt-dlp output template, relative to output_dir.

    Returns:
        list[str]: Absolute paths of the files yt-dlp produced (empty on failure).
    """
    output_template = f"{output_dir}/{file_template}"

    cmd = [
        checkDependencies.resolve_ytdlp(), "-ciw", "-x",
        "--audio-format", "mp3",
        "--audio-quality", "320K",
        # --audio-quality only sets bitrate. Scoped to ExtractAudio because a
        # bare "ffmpeg:" would also reach the stream-copy metadata/thumbnail steps.
        "--postprocessor-args", "ExtractAudio+ffmpeg_o:-ar 48000",
        "--embed-metadata", "--embed-thumbnail",
        "--print", "after_move:filepath",
        "-o", output_template, "--", url
    ]

    interfaceComponents.Print_Tag(f"Downloading (MP3): {url}", tag="Process")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        interfaceComponents.Print_Tag("Download Complete", tag="Success")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception as e:
        interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
        return []