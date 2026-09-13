import core.interfaceComponents as interfaceComponents
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

def download_file_flac(url, output_dir):
    """
    Executes the yt-dlp binary to download and convert a specific URL.
    
    This function configures yt-dlp for high-quality FLAC extraction and 
    sets a specific directory structure for playlists.
    
    Args:
        url (str): The video or playlist link.
        output_dir (str): The base directory for file storage.
    """
    # Define the file naming and folder hierarchy logic:
    # Subfolders are named after the Playlist title.
    # Files are prefixed with their position in the playlist (01 - Title.flac).
    output_template = f"{output_dir}/%(playlist_title)s/%(playlist_index)02d - %(title)s.%(ext)s"
    
    # Command Arguments:
    # -c: continue | -i: ignore errors | -w: no overwrites | -x: extract audio
    cmd = [
        "./yt-dlp.exe", "-ciw", "-x", 
        "--audio-format", "flac", 
        "--audio-quality", "0", 
        "--embed-metadata", "--embed-thumbnail", 
        "-o", output_template, url
    ]
    
    interfaceComponents.Print_Tag(f"Downloading: {url}", tag="Process")
    
    try:
        # check=True will raise a CalledProcessError if the command fails
        subprocess.run(cmd, check=True)
        interfaceComponents.Print_Tag("Download Complete", tag="Success")
    except Exception as e:
        # Captures network issues, missing binaries, or invalid URLs
        interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")