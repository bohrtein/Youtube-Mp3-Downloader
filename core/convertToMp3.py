import subprocess
from pathlib import Path
import core.checkDependencies as checkDependencies
import core.interfaceComponents as interfaceComponents

# 320kbps is effectively transparent for MP3, and 48kHz matches what the
# downloader now produces -- keeping converted library files at the same
# rate avoids resampling twice if they're ever re-converted.
MP3_BITRATE = "320k"
MP3_SAMPLE_RATE = "48000"

def convert_flac_to_mp3(flac_path):
    """
    Transcodes a single FLAC file to MP3 in place (same folder, same name,
    .mp3 extension), carrying over tags and embedded cover art, then
    deletes the source FLAC once the MP3 is confirmed written.

    Args:
        flac_path (Path or str): The source FLAC file.

    Returns:
        Path | None: The new MP3 path on success, None on failure.
    """
    flac_path = Path(flac_path)
    mp3_path = flac_path.with_suffix(".mp3")

    cmd = [
        checkDependencies.resolve_ffmpeg(), "-y",
        "-i", str(flac_path),
        # Map audio + any embedded art (FLAC stores cover art as an
        # attached picture, which ffmpeg exposes as a second stream).
        "-map", "0:a", "-map", "0:v?",
        "-c:a", "libmp3lame", "-b:a", MP3_BITRATE, "-ar", MP3_SAMPLE_RATE,
        "-c:v", "copy", "-id3v2_version", "3",
        str(mp3_path),
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except Exception as e:
        interfaceComponents.Print_Tag(f"Error converting {flac_path.name}: {e}", tag="Error")
        # Don't leave a half-written MP3 behind a failed conversion
        if mp3_path.exists():
            mp3_path.unlink()
        return None

    flac_path.unlink()
    return mp3_path

def convert_library_to_mp3(target_dir):
    """
    Finds every FLAC file under target_dir and converts it to MP3 in place,
    deleting each FLAC once its MP3 replacement is written.

    Args:
        target_dir (str): Root folder to scan recursively for .flac files.

    Returns:
        list[Path]: Paths of the MP3 files produced.
    """
    path = Path(target_dir)
    flac_files = list(path.rglob("*.flac"))

    if not flac_files:
        interfaceComponents.Print_Tag("No FLAC files found to convert.", tag="Warning")
        return []

    interfaceComponents.Print_Tag(f"Converting {len(flac_files)} FLAC file(s) to MP3...", tag="Process")

    converted = []
    for flac_file in flac_files:
        interfaceComponents.Print_Tag(f"Converting: {flac_file.name}", tag="Convert")
        result = convert_flac_to_mp3(flac_file)
        if result:
            converted.append(result)

    interfaceComponents.Print_Tag(f"Converted {len(converted)}/{len(flac_files)} file(s).", tag="Success")
    return converted
