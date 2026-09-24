import logging
import os
import subprocess
import sys
import threading

logger = logging.getLogger("ytmp3")

def setup_logging():
    """
    Sends every log line (Print_Tag, Flask, Werkzeug, Socket.IO, uncaught
    thread errors) to stdout, which is what the app hub's Developer Tools
    log viewer reads (logs/<slug>.log). Safe to call more than once.
    """
    # Under the hub stdout/stderr are pipes, which Python block-buffers:
    # lines would show up in the viewer late, or never if the process dies.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)

    # The viewer shows raw text, so no ANSI colours in uncaught tracebacks.
    if not sys.stderr.isatty():
        os.environ["PYTHON_COLORS"] = "0"

    root = logging.getLogger()
    if root.handlers:
        return
    # The hub stamps every line itself; standalone runs need their own time.
    fmt = "%(levelname)-7s %(message)s" if os.environ.get("APP_PREFIX") else "%(asctime)s %(levelname)-7s %(message)s"
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format=fmt)

    # Background tasks (downloads, sync, covers) run in threads; make their
    # crashes land in the log as errors with the thread they came from.
    def log_thread_crash(args):
        if args.exc_type is SystemExit:
            return
        logger.error(f"Uncaught error in thread {args.thread.name if args.thread else '?'}",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = log_thread_crash

def _level_for(tag):
    tag = tag.lower()
    if "error" in tag:
        return logging.ERROR
    if "warning" in tag:
        return logging.WARNING
    return logging.INFO

def Print_Tag(message, tag="System") -> None:
    """
    Outputs a consistently formatted log message to the terminal.

    The tag is encased in brackets and centered within a fixed 14-character
    width to ensure that messages align vertically regardless of tag length.
    Tags containing "Error" log at ERROR and include the traceback of the
    exception being handled (plus a failed command's stderr); "Warning"
    tags log at WARNING.

    Args:
        message (str): The primary text to be displayed.
        tag (str): The category label (e.g., 'Success', 'Error', 'Process').
                   Defaults to 'System'.
    """
    if not logging.getLogger().handlers:
        setup_logging()

    level = _level_for(tag)
    exc = sys.exc_info()[1] if level >= logging.ERROR else None
    # A failed yt-dlp/ffmpeg only says "returned non-zero exit status 1";
    # the actual reason is in the stderr it printed.
    if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
        stderr = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
        message = f"{message}\n{stderr.strip()[-1500:]}"

    # Using f-string alignment: ^14 means "center within 14 spaces"
    formatted_tag = f"[{tag:^14}]"
    logger.log(level, f"{formatted_tag} {message}", exc_info=exc)

class interfaceComponents:
    """
    A container class for managing UI state and shared interface references.
    """
    def __init__(self):
        # Placeholder for potential future extension or specific print tracking
        self.print001 = None
        
def header_start():
    """
    Prints the application title card to the console. 
    Used during script initialization to provide visual context to the user.
    """
    print("=======================================")    
    print("YouTube Playlist Downloader (FLAC/MP3)")
    print("=======================================") 

def header_exit():
    """
    Displays a graceful exit message and credit.
    
    Includes a blocking input() call to prevent the terminal window 
    from closing instantly if the script is run as an executable.
    """
    print("Thank you for using the program")
    print("Made by bohrtein")
    input("Press Enter to close...")