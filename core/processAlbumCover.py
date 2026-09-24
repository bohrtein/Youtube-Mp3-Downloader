import io
from pathlib import Path
from PIL import Image
import core.interfaceComponents as interfaceComponents
import core.audioTags as audioTags

COVER_SIZE = 250

def process_album_covers_loop(target_dir):
    """
    Iterates through the download directory to standardize FLAC/MP3 files.

    This function performs two main tasks:
    1. Metadata Cleaning: Strips secondary artists from the artist tag.
    2. Artwork Standardizing: Replaces existing covers with 250x250 square JPEGs.

    Args:
        target_dir (str): Root directory containing the album subfolders.
    """
    path = Path(target_dir)
    interfaceComponents.Print_Tag(f"Processing audio files in: {path.absolute()}", tag="System")

    files = audioTags.find_audio_files(path)
    if not files:
        interfaceComponents.Print_Tag("No FLAC/MP3 files found to process.", tag="Warning")
        return

    for audio_file in files:
        try:
            # 1. Open file and clean Artist data
            audio = audioTags.open_tags(audio_file)
            raw_artist = audio.get("artist", [""])[0]

            # Logic: If multiple artists are listed (separated by commas), keep only the first.
            if "," in raw_artist:
                cleaned = clean_artist(raw_artist)
                audio["artist"] = cleaned
                audio.save() # Commit the text change before processing imagery
                interfaceComponents.Print_Tag(f"Cleaned Artist: {cleaned}", tag="Metadata")

            # 2. Proceed to image manipulation logic
            process_album_cover(audio_file)

        except Exception as e:
            interfaceComponents.Print_Tag(f"Error in file {audio_file.name}: {e}", tag="Error")


def clean_artist(raw_artist):
    """
    Trims the artist string to the primary artist only.

    Example: "Artist A, Artist B" -> "Artist A"
    """
    if not raw_artist:
        return "Unknown Artist"
    return raw_artist.split(',')[0].strip()

def process_album_cover(file_path):
    """
    Extracts, crops to a square, and resizes the embedded artwork.

    The resulting image is converted to a JPEG and re-embedded into the
    file, ensuring the web UI has consistent image dimensions.
    """
    try:
        cover_bytes = audioTags.get_cover_bytes(file_path)
        if not cover_bytes:
            interfaceComponents.Print_Tag(f"No image found in {file_path.name}", tag="Skipping")
            return

        img = Image.open(io.BytesIO(cover_bytes))

        # Performance optimization: Skip if the image is already processed
        if img.size == (COVER_SIZE, COVER_SIZE):
            interfaceComponents.Print_Tag(f"{file_path.name}", tag="Skipping")
            return

        interfaceComponents.Print_Tag(f"Resizing {file_path.name}", tag="Processing")

        # --- SQUARE CROP CALCULATION ---
        # Determines the shortest side to create a centered square crop
        min_dim = min(img.size)
        left = (img.width - min_dim) / 2
        top = (img.height - min_dim) / 2

        # Perform crop and resize using high-quality LANCZOS filtering.
        # RGB conversion: yt-dlp can embed PNG/WebP art with alpha, which JPEG can't hold.
        img = img.convert("RGB").crop((left, top, left + min_dim, top + min_dim)).resize((COVER_SIZE, COVER_SIZE), Image.LANCZOS)

        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG')

        audioTags.set_cover_jpeg(file_path, img_byte_arr.getvalue(), COVER_SIZE)
    except Exception as e:
        interfaceComponents.Print_Tag(f"Artwork Error: {e}", tag="Error")
