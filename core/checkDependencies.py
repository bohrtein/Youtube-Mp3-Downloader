import zipfile
import subprocess
import shutil
import platform
import sys
from pathlib import Path
import core.interfaceComponents as interfaceComponents

def dependencies_check():
    """
    Orchestrates the verification of all external binaries required for the app.
    Checks for yt-dlp, ffprobe, and ffmpeg sequentially.
    """
    check_ytdlp()
    check_ffprobe()
    check_ffmpeg()
    interfaceComponents.Print_Tag("Dependencies verified.", tag="Success")

def _venv_bin_candidate(name):
    """
    Path to `name` next to the currently-running Python interpreter, i.e.
    this venv's bin/ (or Scripts/ on Windows) directory.

    A pip-installed console script (like yt-dlp) lands there regardless of
    whether the venv was actually `source activate`d — which matters
    because a launcher that runs `.venv/bin/python app.py` directly (as
    App Hub does) does NOT put that bin/ directory on PATH, so
    shutil.which() alone would miss it even though it's installed.
    """
    exe_names = [name, f"{name}.exe"] if platform.system() == "Windows" else [name]
    for exe_name in exe_names:
        candidate = Path(sys.executable).parent / exe_name
        if candidate.exists():
            return str(candidate)
    return None

def resolve_ytdlp():
    """
    Returns the command to invoke yt-dlp with.

    Checks, in order: this venv's own bin/ (covers a pip install even when
    the launcher didn't activate the venv, e.g. App Hub's `.venv/bin/python
    app.py`), then PATH (an apt/pipx install, or one on Windows), then the
    standalone ./yt-dlp.exe this module downloads on Windows. If none of
    those exist, still returns "yt-dlp" so the caller's subprocess call
    fails loudly (FileNotFoundError) instead of silently doing nothing.
    """
    found = _venv_bin_candidate("yt-dlp") or shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if found:
        return found
    if platform.system() == "Windows" and Path("./yt-dlp.exe").exists():
        return "./yt-dlp.exe"
    return "yt-dlp"

def check_ytdlp():
    """
    Ensures a working yt-dlp is available. Prefers one already installed
    (this venv's own bin/, or PATH); on Windows, where installing via a
    package manager is less common, falls back to downloading the
    standalone yt-dlp.exe into the project root. On other platforms, a
    missing yt-dlp is reported rather than silently ignored, since there's
    no safe standalone binary to fetch for an unknown Linux/Mac environment.
    """
    interfaceComponents.Print_Tag("Verifying yt-dlp", tag="System")
    found = _venv_bin_candidate("yt-dlp") or shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if found:
        interfaceComponents.Print_Tag(f"yt-dlp verified ({found})!", tag="Success")
        return

    if platform.system() != "Windows":
        interfaceComponents.Print_Tag(
            "yt-dlp not found. Install it, e.g. `pip install yt-dlp`.",
            tag="Error"
        )
        return

    if not Path("./yt-dlp.exe").exists():
        interfaceComponents.Print_Tag("yt-dlp.exe not found.", tag="Warning")
        try:
             # yt-dlp is provided as a direct .exe, so no unzipping is required
             download_package("https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe -o yt-dlp.exe")
             interfaceComponents.Print_Tag("yt-dlp.exe downloaded.", tag="Success")
        except Exception as e:
             interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
    else:
        interfaceComponents.Print_Tag("yt-dlp.exe verified!", tag="Success")

def check_ffprobe():
    """
    Ensures a working ffprobe is available. Prefers one already on PATH
    (e.g. `apt install ffmpeg` on Linux, which provides ffprobe too); on
    Windows falls back to downloading the standalone binary from ffbinaries.
    """
    interfaceComponents.Print_Tag("Verifying ffprobe", tag="System")
    found = _venv_bin_candidate("ffprobe") or shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        interfaceComponents.Print_Tag(f"ffprobe verified ({found})!", tag="Success")
        return

    if platform.system() != "Windows":
        interfaceComponents.Print_Tag(
            "ffprobe not found. Install it, e.g. `apt install ffmpeg`.",
            tag="Error"
        )
        return

    if not Path("./ffprobe.exe").exists():
        interfaceComponents.Print_Tag("ffprobe.exe not found.", tag="Warning")
        try:
             download_package('https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffprobe-4.4.1-win-64.zip -o ffprobe.zip')
             unzip_and_cleanup("ffprobe.zip")
             interfaceComponents.Print_Tag("ffprobe.exe ready.", tag="Success")
        except Exception as e:
             interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
    else:
        interfaceComponents.Print_Tag("ffprobe.exe verified!", tag="Success")

def check_ffmpeg():
    """
    Ensures a working ffmpeg is available. Prefers one already on PATH
    (e.g. `apt install ffmpeg` on Linux); on Windows falls back to
    downloading the standalone binary from ffbinaries.
    """
    interfaceComponents.Print_Tag("Verifying ffmpeg", tag="System")
    found = _venv_bin_candidate("ffmpeg") or shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        interfaceComponents.Print_Tag(f"ffmpeg verified ({found})!", tag="Success")
        return

    if platform.system() != "Windows":
        interfaceComponents.Print_Tag(
            "ffmpeg not found. Install it, e.g. `apt install ffmpeg`.",
            tag="Error"
        )
        return

    if not Path("./ffmpeg.exe").exists():
        interfaceComponents.Print_Tag("ffmpeg.exe not found.", tag="Warning")
        try:
             download_package("https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v4.4.1/ffmpeg-4.4.1-win-64.zip -o ffmpeg.zip")
             unzip_and_cleanup("ffmpeg.zip")
             interfaceComponents.Print_Tag("ffmpeg.exe ready.", tag="Success")
        except Exception as e:
             interfaceComponents.Print_Tag(f"Error: {e}", tag="Error")
    else:
        interfaceComponents.Print_Tag("ffmpeg.exe verified!", tag="Success")

def download_package(download_link):
    """
    Invokes the system's 'curl' command to fetch files from the web.
    
    Args:
        download_link (str): The URL and output flags for the curl command.
    """
    # -L follows redirects, which is necessary for GitHub release downloads
    subprocess.run("curl -L " + download_link, check=True)

def unzip_and_cleanup(zip_name):
    """
    Extracts all contents of a zip file to the current directory and 
    removes the original archive to save space.
    
    Args:
        zip_name (str): The filename of the zip archive (e.g., 'ffmpeg.zip').
    """
    zip_path = Path(zip_name)
    if zip_path.exists():
        interfaceComponents.Print_Tag(f"Unzipping {zip_name}...", tag="Extracting")
        
        # Open and extract the zip archive
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(".")
            
        # Delete the zip file after successful extraction
        zip_path.unlink() 
        interfaceComponents.Print_Tag(f"Deleted {zip_name}", tag="Cleanup")