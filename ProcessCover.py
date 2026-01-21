import io
import sys
from pathlib import Path
from PIL import Image
from mutagen.flac import FLAC, Picture

def process_flac_cover(file_path):
    """Wipes existing images, crops/resizes cover to 250x250 JPEG."""
    try:
        audio = FLAC(file_path)

        if not audio.pictures:
            print(f"  [Skip]: No image found in {file_path.name}")
            return
        
        # Get original image data
        raw_data = audio.pictures[0].data
        img = Image.open(io.BytesIO(raw_data))
        
        # 1. Square Crop (Center-based)
        width, height = img.size
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
        print(f"  [Success]: {file_path.name} (250px JPEG)")

    except Exception as e:
        print(f"  [Error]: {file_path.name} -> {e}")

def run_processor(target_dir="downloads"):
    path = Path(target_dir)
    print(f"--- Processing FLAC Artwork in: {path.absolute()} ---")
    
    files = list(path.rglob("*.flac"))
    if not files:
        print("No FLAC files found.")
        return

    for flac_file in files:
        process_flac_cover(flac_file)

if __name__ == "__main__":
    # You can pass a specific directory or use the default "downloads"
    target = sys.argv[1] if len(sys.argv) > 1 else "downloads"
    run_processor(target)