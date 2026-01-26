import io
from pathlib import Path
from PIL import Image
from mutagen.flac import FLAC, Picture
import core.interfaceComponents as interfaceComponents

def process_album_covers_loop_flac(target_dir):
    """
    Iterates through the download directory to standardize FLAC files.
    
    This function performs two main tasks:
    1. Metadata Cleaning: Strips secondary artists from the artist tag.
    2. Artwork Standardizing: Replaces existing covers with 250x250 square JPEGs.
    
    Args:
        target_dir (str): Root directory containing the FLAC subfolders.
    """
    path = Path(target_dir)
    interfaceComponents.Print_Tag(f"Processing FLAC files in: {path.absolute()}", tag="System")
    
    files = list(path.rglob("*.flac"))
    if not files:
        interfaceComponents.Print_Tag("No FLAC files found to process.", tag="Warning")
        return

    for flac_file in files:
        try:
            # 1. Open file and clean Artist data
            audio = FLAC(flac_file)
            raw_artist = audio.get("artist", [""])[0]
            
            # Logic: If multiple artists are listed (separated by commas), keep only the first.
            if "," in raw_artist:
                cleaned = clean_artist(raw_artist)
                audio["artist"] = cleaned
                audio.save() # Commit the text change before processing imagery
                interfaceComponents.Print_Tag(f"Cleaned Artist: {cleaned}", tag="Metadata")
            
            # 2. Proceed to image manipulation logic
            process_album_cover_flac(flac_file)
            
        except Exception as e:
            interfaceComponents.Print_Tag(f"Error in file {flac_file.name}: {e}", tag="Error")
        
    
def clean_artist(raw_artist):
    """
    Trims the artist string to the primary artist only.
    
    Example: "Artist A, Artist B" -> "Artist A"
    """
    if not raw_artist:
        return "Unknown Artist"
    return raw_artist.split(',')[0].strip()

def process_album_cover_flac(file_path):
    """
    Extracts, crops to a square, and resizes the embedded FLAC artwork.
    
    The resulting image is converted to a JPEG and re-embedded into the FLAC 
    metadata block, ensuring the web UI has consistent image dimensions.
    """
    try:
        audio = FLAC(file_path)
        if not audio.pictures:
            interfaceComponents.Print_Tag(f"No image found in {file_path.name}", tag="Skipping")
            return
            
        # Load image data into memory using PIL
        img = Image.open(io.BytesIO(audio.pictures[0].data))
        
        # Performance optimization: Skip if the image is already processed
        if img.size == (250, 250):
            interfaceComponents.Print_Tag(f"{file_path.name}", tag="Skipping")
            return
        
        interfaceComponents.Print_Tag(f"Resizing {file_path.name}", tag="Processing")
        
        # --- SQUARE CROP CALCULATION ---
        # Determines the shortest side to create a centered square crop
        
        min_dim = min(img.size)
        left = (img.width - min_dim) / 2
        top = (img.height - min_dim) / 2
        
        # Perform crop and resize using high-quality LANCZOS filtering
        img = img.crop((left, top, left + min_dim, top + min_dim)).resize((250, 250), Image.LANCZOS)
        
        # Save processed image back into a byte buffer as JPEG
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG')
        
        # Update FLAC metadata block
        audio.clear_pictures()
        picture = Picture()
        picture.data = img_byte_arr.getvalue()
        # type 3 = Cover (front); mime = image/jpeg; depth 24 = Standard Color
        picture.type, picture.mime, picture.width, picture.height, picture.depth = 3, "image/jpeg", 250, 250, 24
        
        audio.add_picture(picture)
        audio.save()
    except Exception as e:
        interfaceComponents.Print_Tag(f"Artwork Error: {e}", tag="Error")