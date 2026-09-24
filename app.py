import hmac
import os
import string
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, abort, url_for
from flask_socketio import SocketIO
import database.databaseConnector as databaseConnector
import database.suggestionsRepo as suggestionsRepo
import database.libraryFiles as libraryFiles
import core.approvedDownloads as approvedDownloads
import core.checkDependencies as checkDependencies
import core.interfaceComponents as interfaceComponents
import routes.friendsPublic as friendsPublic
import routes.suggestAdmin as suggestAdmin
import main

# Before Flask/Socket.IO set up their loggers, so everything they log goes
# to the same stdout the app hub's log viewer reads.
interfaceComponents.setup_logging()


class PrefixMiddleware:
    """Tells Flask it's mounted under a path prefix (set by the app hub via
    APP_PREFIX) so url_for()/redirect()/static links come out correctly
    prefixed instead of pointing at the hub's own root."""

    def __init__(self, wsgi_app, prefix=""):
        self.wsgi_app = wsgi_app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        if self.prefix:
            environ["SCRIPT_NAME"] = self.prefix
        return self.wsgi_app(environ, start_response)


# Initialize Flask application and SocketIO for real-time communication
app = Flask(__name__)
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=os.environ.get("APP_PREFIX", ""))
# Static files revalidate on every load (max-age=0 + ETag): otherwise
# browsers cache app.css/app.js by heuristic for days, and after an update
# a page can run yesterday's script against today's markup.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
socketio = SocketIO(app, cors_allowed_origins="*")

# Ensure the local SQLite database and schema exist before the first request
databaseConnector.init_db()

# --- ACCESS CONTROL ---
# The app hub sends this secret (X-Apphub-Auth) only on requests that passed
# its login; public friend pages arrive without it. Unset means the app is
# running standalone for development, bound to 127.0.0.1.
HUB_PROXY_SECRET = os.environ.get("APPHUB_PROXY_SECRET", "")
PUBLIC_BLUEPRINTS = {"friends_public"}
PUBLIC_ENDPOINTS = {"static", "healthz"}

if not HUB_PROXY_SECRET:
    interfaceComponents.Print_Tag("APPHUB_PROXY_SECRET is not set: admin routes are unprotected (standalone dev mode).", tag="Warning")

# --- DESIGN SYSTEM ---
# Behind the app hub, pages load Matrix live from the hub (/ds/1/, one copy
# shared by every app), with the copy synced into static/matrix/ as the
# fallback. Standalone, the synced copy is the only one. MX_LIVE overrides.
MATRIX_LIVE = os.environ.get("MX_LIVE", "/ds/1/" if HUB_PROXY_SECRET else "")


@app.context_processor
def matrix_design():
    return {"mx_live": MATRIX_LIVE, "mx_local": url_for("static", filename="matrix/")}


def is_hub_authenticated():
    if not HUB_PROXY_SECRET:
        return True
    return hmac.compare_digest(request.headers.get("X-Apphub-Auth", ""), HUB_PROXY_SECRET)

@app.before_request
def require_hub_login():
    """
    Everything except the friend pages, static files and the health check
    is admin-only. A 404 (not 403) so admin URLs are indistinguishable from
    ones that don't exist.
    """
    if request.endpoint in PUBLIC_ENDPOINTS or request.blueprint in PUBLIC_BLUEPRINTS:
        return
    if not is_hub_authenticated():
        abort(404)

@socketio.on('connect')
def on_socket_connect(auth=None):
    # Socket.IO requests bypass Flask's before_request hooks, so the same
    # check runs here; returning False refuses the connection.
    return is_hub_authenticated()

@app.route('/healthz')
def healthz():
    return "ok"

app.register_blueprint(friendsPublic.bp)
app.register_blueprint(suggestAdmin.bp)

# --- WEB ROUTES ---

@app.route('/')
def main_dashboard():
    """
    Renders the primary control dashboard.
    """
    return render_template(
        'main.html',
        library_folder=databaseConnector.get_library_folder(),
        pending_suggestions=suggestionsRepo.count_pending_submissions(),
    )

@app.route('/browse_folders')
def browse_folders():
    """
    Lists subfolders of the given path for the folder-picker modal.
    With no path (or a blank one), lists the available drive letters instead.
    """
    raw_path = request.args.get('path', '').strip()

    if not raw_path:
        drives = [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
        folders = [{"name": drive, "path": drive} for drive in drives]
        return jsonify({"path": None, "parent": None, "folders": folders})

    current = Path(raw_path)
    if not current.is_dir():
        return jsonify({"success": False, "message": "Not a valid directory"}), 400

    folders = []
    try:
        for entry in sorted(current.iterdir(), key=lambda p: p.name.lower()):
            try:
                if entry.is_dir():
                    folders.append({"name": entry.name, "path": str(entry)})
            except PermissionError:
                continue
    except PermissionError:
        return jsonify({"success": False, "message": "Permission denied"}), 403

    # None of the parent stays within the same drive means we've hit the drive root
    parent = str(current.parent) if current.parent != current else None
    return jsonify({"path": str(current), "parent": parent, "folders": folders})

@app.route('/set_library_folder', methods=['POST'])
def set_library_folder():
    """
    Persists the folder chosen from the folder-picker modal.
    """
    data = request.get_json(silent=True) or {}
    path = data.get('path', '').strip()

    try:
        databaseConnector.set_library_folder(path)
        return jsonify({"success": True, "path": databaseConnector.get_library_folder()})
    except NotADirectoryError as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/library')
def library_view():
    """
    Fetches all albums from the database gallery view and renders the library page.
    Sync only ever inserts, so an album's newest song_id says when music was
    last added to it - that's what the "Recently added" sort orders by.
    """
    conn = databaseConnector.connect_to_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT g.*, (SELECT MAX(s.song_id) FROM songs s WHERE s.album_id = g.album_id) AS last_song_id
        FROM album_gallery g""")
    albums = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('library.html', albums=albums)

@app.route('/album/<int:album_id>')
def album_detail(album_id):
    """
    Retrieves specific album metadata and its associated songs.
    
    Args:
        album_id (int): The unique identifier from the database.
    """
    conn = databaseConnector.connect_to_db()
    cursor = conn.cursor()

    # 1. Get Album Info (Joins artist table to get the name)
    cursor.execute("""
        SELECT alb.album_name, art.artist_name
        FROM albums alb
        JOIN artists art ON alb.artist_id = art.artist_id
        WHERE alb.album_id = ?""", (album_id,))
    album_info = cursor.fetchone()

    # 2. Get Songs ordered by track number
    cursor.execute("SELECT * FROM songs WHERE album_id = ? ORDER BY track_number", (album_id,))
    songs = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('album.html', album=album_info, songs=songs, album_id=album_id)

# --- API ENDPOINTS (DELETE OPERATIONS) ---

@app.route('/delete_album/<int:album_id>', methods=['DELETE'])
def delete_album(album_id):
    """
    Performs a cascading delete: removes the album's files from the library
    folder, then its songs, then the album record.
    """
    conn = databaseConnector.connect_to_db()
    if not conn: return {"success": False, "message": "DB Connection failed"}, 500
    
    try:
        cursor = conn.cursor()
        # Files first: if one can't be deleted the rows stay, instead of the
        # next sync quietly bringing the song back.
        keys = libraryFiles.song_keys(cursor, "s.album_id = ?", (album_id,))
        deleted_files = libraryFiles.delete_song_files(databaseConnector.get_library_folder(), keys)

        # Delete songs first to satisfy potential Foreign Key constraints
        cursor.execute("DELETE FROM songs WHERE album_id = ?", (album_id,))
        cursor.execute("DELETE FROM albums WHERE album_id = ?", (album_id,))

        conn.commit()

        cover_path = os.path.join('static', 'covers', f'{album_id}.jpg')
        if os.path.exists(cover_path):
            os.remove(cover_path)

        suggestionsRepo.invalidate_library_index()
        return {"success": True, "message": f"Album deleted ({deleted_files} files removed)"}
    except Exception as e:
        interfaceComponents.Print_Tag(f"Deleting album {album_id} failed: {e}", tag="Error")
        return {"success": False, "message": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route('/delete_song/<int:song_id>', methods=['DELETE'])
def delete_song(song_id):
    """
    Removes a single song's file from the library folder, then its record.
    """
    conn = databaseConnector.connect_to_db()
    if not conn:
        return {"success": False, "message": "Database connection failed"}, 500

    try:
        cursor = conn.cursor()
        keys = libraryFiles.song_keys(cursor, "s.song_id = ?", (song_id,))
        deleted_files = libraryFiles.delete_song_files(databaseConnector.get_library_folder(), keys)
        cursor.execute("DELETE FROM songs WHERE song_id = ?", (song_id,))
        conn.commit()
        suggestionsRepo.invalidate_library_index()
        return {"success": True, "message": f"Song deleted ({deleted_files} files removed)"}
    except Exception as e:
        interfaceComponents.Print_Tag(f"Deleting song {song_id} failed: {e}", tag="Error")
        return {"success": False, "message": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

# --- SOCKET.IO EVENTS (ASYNC BACKGROUND TASKS) ---

@socketio.on('trigger_cleanup')
def handle_cleanup():
    """
    Spawns a background thread to delete existing files without blocking the UI.
    """
    thread = threading.Thread(target=main.delete_already_exsisting_files)
    thread.start()
    
    # Notify frontend that the process has begun
    socketio.emit('progress', {'percent': 5, 'status': 'Starting cleanup on G: drive...'})

@socketio.on('start_download_batch')
def handle_download_batch(data):
    """
    Manages the sequential download of multiple URLs in a background thread.
    Emits progress updates to the frontend for each item.
    """
    urls = data.get('urls', [])
    audio_format = data.get('format', 'flac')

    def background_task():
        with approvedDownloads.download_lock:
            download_all()

    def download_all():
        total_urls = len(urls)
        checkDependencies.dependencies_check() # Ensure yt-dlp/ffmpeg are present

        for index, url in enumerate(urls):
            current_item = index + 1
            # Update UI with progress and a truncated URL
            socketio.emit('progress', {
                'percent': (index / total_urls) * 100,
                'status': f'Downloading {current_item} of {total_urls}: {url[:30]}...'
            })

            try:
                main.start_downloading(url, audio_format=audio_format)
            except Exception as e:
                interfaceComponents.Print_Tag(f"Error downloading {url}: {e}", tag="Error")
                socketio.emit('progress', {
                    'percent': (current_item/total_urls)*100,
                    'status': f'Error on item {current_item}'
                })

        socketio.emit('progress', {'percent': 100, 'status': 'complete'})

    threading.Thread(target=background_task).start()

@socketio.on('start_sync')
def run_sync_only():
    """
    Background task to sync local files with the database.
    """
    def task():
        socketio.emit('progress', {'percent': 50, 'status': 'Syncing...'})
        main.sync_to_library()
        socketio.emit('progress', {'percent': 100, 'status': 'complete'})
    threading.Thread(target=task).start()

LIBRARY_RESET_PHRASE = "RESET"

@socketio.on('start_library_reset')
def run_library_reset(data=None):
    """
    Background task that wipes the library tables (after backing up the
    database) and, unless told not to, rebuilds them from the library folder.
    The confirmation phrase is checked here too, not just in the page.
    """
    data = data or {}
    if data.get('confirm') != LIBRARY_RESET_PHRASE:
        socketio.emit('progress', {'percent': 0, 'status': 'Error: reset not confirmed'})
        return
    rescan = data.get('rescan', True)

    def task():
        # Never wipe the tables out from under a running download.
        if not approvedDownloads.download_lock.acquire(blocking=False):
            socketio.emit('progress', {'percent': 0, 'status': 'Error: a download is running, try again once it finishes'})
            return
        try:
            socketio.emit('progress', {'percent': 10, 'status': 'Backing up and clearing the library...'})
            databaseConnector.reset_library()
            suggestionsRepo.invalidate_library_index()
            if rescan:
                socketio.emit('progress', {'percent': 40, 'status': 'Rebuilding from the library folder...'})
                main.sync_to_library()
                suggestionsRepo.invalidate_library_index()
            socketio.emit('progress', {'percent': 100, 'status': 'complete'})
        except Exception as e:
            interfaceComponents.Print_Tag(f"Library reset failed: {e}", tag="Error")
            socketio.emit('progress', {'percent': 100, 'status': f'Error resetting library: {e}'})
        finally:
            approvedDownloads.download_lock.release()
    threading.Thread(target=task).start()

@socketio.on('start_mp3_convert')
def run_mp3_convert_only():
    """
    Background task to transcode existing FLAC library files to MP3
    (320kbps, 48000Hz) in place -- no re-downloading.
    """
    def task():
        socketio.emit('progress', {'percent': 50, 'status': 'Converting FLAC to MP3...'})
        main.convert_library_to_mp3()
        socketio.emit('progress', {'percent': 100, 'status': 'complete'})
    threading.Thread(target=task).start()

@socketio.on('start_covers')
def run_covers_only():
    """
    Background task to extract and process album artwork.
    """
    def task():
        socketio.emit('progress', {'percent': 50, 'status': 'Processing Covers...'})
        main.process_songs()
        socketio.emit('progress', {'percent': 100, 'status': 'complete'})
    threading.Thread(target=task).start()

if __name__ == '__main__':
    # Starts the Flask-SocketIO server
    # Bind to the port the app hub assigns via PORT, and turn off the
    # debug reloader -- it spawns its own child process, which fights with
    # the hub's own subprocess supervision (start/stop/idle-timeout).
    port = int(os.environ.get('PORT', 5000))
    # flask-socketio refuses to run the (insecure-for-the-open-internet)
    # Werkzeug dev server unless this is set explicitly. That's fine here:
    # this process only binds to 127.0.0.1, reachable exclusively through
    # the app hub's own reverse proxy, never directly from the network.
    socketio.run(app, host='127.0.0.1', port=port, debug=False, allow_unsafe_werkzeug=True)