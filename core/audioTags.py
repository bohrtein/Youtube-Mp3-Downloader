from pathlib import Path
import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC, ID3NoHeaderError

AUDIO_EXTENSIONS = (".flac", ".mp3")

def find_audio_files(target_dir):
    """Every FLAC and MP3 file under target_dir, recursively."""
    path = Path(target_dir)
    return [f for ext in AUDIO_EXTENSIONS for f in path.rglob(f"*{ext}")]

def open_tags(file_path):
    """
    Opens a file with a dict-like tag interface using the same keys
    ("artist", "album", "title", "tracknumber", "date") for FLAC and MP3.
    """
    return mutagen.File(file_path, easy=True)

def iter_tag_text(file_path):
    """
    Yields the text of every raw tag on the file. Unlike open_tags(), this
    includes fields the easy interface hides -- e.g. the comment/purl frames
    where yt-dlp stores the source URL in MP3s.
    """
    audio = mutagen.File(file_path)
    if audio is None or audio.tags is None:
        return
    if isinstance(audio, FLAC):
        for _, value in audio.tags:
            yield value
    else:
        for frame in audio.tags.values():
            if not isinstance(frame, APIC):
                yield str(frame)

def get_cover_bytes(file_path):
    """Raw bytes of the first embedded cover image, or None."""
    if Path(file_path).suffix.lower() == ".flac":
        pictures = FLAC(file_path).pictures
        return pictures[0].data if pictures else None
    try:
        frames = ID3(file_path).getall("APIC")
    except ID3NoHeaderError:
        return None
    return frames[0].data if frames else None

def set_cover_jpeg(file_path, jpeg_bytes, size):
    """Replaces all embedded art with a single front-cover JPEG."""
    if Path(file_path).suffix.lower() == ".flac":
        audio = FLAC(file_path)
        audio.clear_pictures()
        picture = Picture()
        picture.data = jpeg_bytes
        # type 3 = Cover (front); depth 24 = standard color
        picture.type, picture.mime, picture.width, picture.height, picture.depth = 3, "image/jpeg", size, size, 24
        audio.add_picture(picture)
        audio.save()
        return
    try:
        tags = ID3(file_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg_bytes))
    # v2.3 is what most portable players actually read reliably
    tags.save(file_path, v2_version=3)
