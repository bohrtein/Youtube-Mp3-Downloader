import hmac
import os
import shutil
import string
import threading
import uuid
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
import core.hubJobs as hubJobs

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
# Behind the app hub, pages load Matrix live from the hub (/ds/2/, one copy
# shared by every app), with the copy synced into static/matrix/ as the
# fallback. Standalone, the synced copy is the only one. MX_LIVE overrides.
MATRIX_LIVE = os.environ.get("MX_LIVE", "/ds/2/" if HUB_PROXY_SECRET else "")


DELETE_UNDO_SECONDS = 10
delete_undo = {}
delete_undo_lock = threading.Lock()


def _finish_delete(token):
    with delete_undo_lock:
        entry = delete_undo.pop(token, None)
    if not entry:
        return
    shutil.rmtree(entry["archive"], ignore_errors=True)
    if entry.get("cover"):
        try:
            Path(entry["cover"]).unlink(missing_ok=True)
        except OSError:
            pass


def _archive_delete_files(token, keys):
    root = Path(databaseConnector.get_library_folder()).resolve()
    archive = root / ".app-trash" / token
    archived = []
    try:
        for index, path in enumerate(libraryFiles.find_song_files(root, keys)):
            original = Path(path).resolve()
            if root not in original.parents:
                continue
            archive.mkdir(parents=True, exist_ok=True)
            saved = archive / f"{index}{original.suffix}"
            shutil.move(str(original), str(saved))
            archived.append((str(original), str(saved)))
        folders = set()
        for original, _saved in archived:
            folder = Path(original).parent
            while folder != root and root in folder.parents:
                folders.add(folder)
                folder = folder.parent
        for folder in sorted(folders, key=lambda item: len(item.parts), reverse=True):
            if folder.exists() and not any(folder.iterdir()):
                folder.rmdir()
        return str(archive), archived
    except Exception:
        for original, saved in archived:
            Path(original).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(saved, original)
        shutil.rmtree(archive, ignore_errors=True)
        raise


def _queue_delete_undo(entry, archive=None, files=None):
    token = uuid.uuid4().hex
    if archive is None or files is None:
        archive, files = _archive_delete_files(token, entry["keys"])
    entry.update(token=token, archive=archive, files=files)
    timer = threading.Timer(DELETE_UNDO_SECONDS, _finish_delete, args=(token,))
    timer.daemon = True
    entry["timer"] = timer
    with delete_undo_lock:
        delete_undo[token] = entry
    timer.start()
    return token


@app.route('/restore_delete/<token>', methods=['POST'])
def restore_delete(token):
    with delete_undo_lock:
        entry = delete_undo.pop(token, None)
        if entry:
            entry["timer"].cancel()
    if not entry:
        return jsonify({"success": False, "message": "Undo window expired."}), 404

    conn = databaseConnector.connect_to_db()
    cursor = conn.cursor()
    moved = []
    try:
        for original, saved in entry["files"]:
            if Path(original).exists():
                raise FileExistsError("A replacement file exists; undo would overwrite it.")
            Path(original).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(saved, original)
            moved.append((original, saved))
        if entry.get("album"):
            a = entry["album"]
            cursor.execute("INSERT INTO albums (album_id, album_name, release_date, artist_id) VALUES (?, ?, ?, ?)",
                           (a["album_id"], a["album_name"], a["release_date"], a["artist_id"]))
        for song in entry["songs"]:
            cursor.execute("""INSERT INTO songs
                (song_id, song_title, duration_seconds, track_number, album_id, release_date, bit_rate, file_type, source_url, youtube_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                           tuple(song[k] for k in ("song_id", "song_title", "duration_seconds", "track_number", "album_id",
                                                   "release_date", "bit_rate", "file_type", "source_url", "youtube_id")))
        conn.commit()
        shutil.rmtree(entry["archive"], ignore_errors=True)
        suggestionsRepo.invalidate_library_index()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        for original, saved in reversed(moved):
            try:
                Path(saved).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(original, saved)
            except OSError:
                pass
        timer = threading.Timer(DELETE_UNDO_SECONDS, _finish_delete, args=(token,))
        timer.daemon = True
        entry["timer"] = timer
        with delete_undo_lock:
            delete_undo[token] = entry
        timer.start()
        return jsonify({"success": False, "message": str(e)}), 409
    finally:
        cursor.close()
        conn.close()


@app.route('/api/downloads/<job_id>/cancel', methods=['POST'])
def cancel_download(job_id):
    if not hubJobs.cancel(job_id):
        return jsonify({"success": False, "message": "Download is no longer running."}), 404
    return jsonify({"success": True})


def run_reported_job(title, work):
    job = hubJobs.Job(title, lambda data: socketio.emit("progress", data))
    socketio.start_background_task(job.run, work)
    return job.id


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
        roots = ([f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]
                 if os.name == "nt" else ["/"])
        folders = [{"name": root, "path": root} for root in roots]
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
        cursor.execute("SELECT * FROM albums WHERE album_id = ?", (album_id,))
        album_row = cursor.fetchone()
        if album_row is None:
            return {"success": False, "message": "Album not found."}, 404
        album = dict(album_row)
        cursor.execute("SELECT * FROM songs WHERE album_id = ? ORDER BY track_number", (album_id,))
        songs = [dict(row) for row in cursor.fetchall()]
        archive, files = _archive_delete_files(uuid.uuid4().hex, keys)

        # Delete songs first to satisfy potential Foreign Key constraints
        cursor.execute("DELETE FROM songs WHERE album_id = ?", (album_id,))
        cursor.execute("DELETE FROM albums WHERE album_id = ?", (album_id,))

        conn.commit()

        cover_path = os.path.join('static', 'covers', f'{album_id}.jpg')
        undo_token = _queue_delete_undo({"kind": "album", "album": album, "songs": songs,
                                          "keys": keys, "cover": cover_path}, archive, files)

        suggestionsRepo.invalidate_library_index()
        return {"success": True, "message": f"Album deleted ({len(files)} files removed)", "undo": undo_token}
    except Exception as e:
        if 'archive' in locals():
            for original, saved in files:
                try:
                    Path(original).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(saved, original)
                except OSError:
                    pass
            shutil.rmtree(archive, ignore_errors=True)
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
        cursor.execute("SELECT * FROM songs WHERE song_id = ?", (song_id,))
        row = cursor.fetchone()
        if row is None:
            return {"success": False, "message": "Song not found."}, 404
        song = dict(row)
        keys = libraryFiles.song_keys(cursor, "s.song_id = ?", (song_id,))
        archive, files = _archive_delete_files(uuid.uuid4().hex, keys)
        cursor.execute("DELETE FROM songs WHERE song_id = ?", (song_id,))
        conn.commit()
        undo_token = _queue_delete_undo({"kind": "song", "songs": [song], "keys": keys}, archive, files)
        suggestionsRepo.invalidate_library_index()
        return {"success": True, "message": f"Song deleted ({len(files)} files removed)", "undo": undo_token}
    except Exception as e:
        if 'archive' in locals():
            for original, saved in files:
                try:
                    Path(original).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(saved, original)
                except OSError:
                    pass
            shutil.rmtree(archive, ignore_errors=True)
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
    run_reported_job("Removing duplicate files", lambda job: main.delete_already_exsisting_files())
    

@socketio.on('start_download_batch')
def handle_download_batch(data):
    data = data if isinstance(data, dict) else {}
    urls = data.get('urls', [])
    if not isinstance(urls, list) or not urls or any(not isinstance(u, str) or not u.strip() for u in urls):
        return {"error": "Paste at least one URL."}
    audio_format = 'mp3' if data.get('format') == 'mp3' else 'flac'
    job = hubJobs.Job(f"Downloading {len(urls)} items", lambda update: socketio.emit('progress', update),
                      cancellable=True)

    def download_all(job):
        if not hubJobs.acquire_download_lock(approvedDownloads.download_lock, job.cancel_event):
            return 'cancelled'
        try:
            checkDependencies.dependencies_check()
            failed = False
            for index, url in enumerate(urls):
                if job.cancel_event.is_set():
                    return 'cancelled'
                job.update(index * 100 / len(urls), f'Downloading {index + 1} of {len(urls)}: {url[:40]}')
                try:
                    main.start_downloading(url, audio_format=audio_format, cancel_event=job.cancel_event)
                except Exception as exc:
                    if job.cancel_event.is_set():
                        return 'cancelled'
                    failed = True
                    interfaceComponents.Print_Tag(f"Error downloading {url}: {exc}", tag="Error")
            return 'failed' if failed else 'done'
        finally:
            approvedDownloads.download_lock.release()

    socketio.start_background_task(job.run, download_all)
    return {"job_id": job.id}

@socketio.on('start_sync')
def run_sync_only():
    """
    Background task to sync local files with the database.
    """
    def task(job):
        job.update(None, "Syncing library files")
        main.sync_to_library()
    run_reported_job("Syncing music library", task)

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

    def task(job):
        # Never wipe the tables out from under a running download.
        if not approvedDownloads.download_lock.acquire(blocking=False):
            socketio.emit('progress', {'percent': 0, 'status': 'Error: a download is running, try again once it finishes'})
            raise RuntimeError("A download is running; reset was not started")
        try:
            job.update(10, "Backing up and clearing the library")
            databaseConnector.reset_library()
            suggestionsRepo.invalidate_library_index()
            if rescan:
                job.update(40, "Rebuilding the library index")
                main.sync_to_library()
                suggestionsRepo.invalidate_library_index()
        except Exception as e:
            interfaceComponents.Print_Tag(f"Library reset failed: {e}", tag="Error")
            socketio.emit('progress', {'percent': 100, 'status': f'Error resetting library: {e}'})
            raise
        finally:
            approvedDownloads.download_lock.release()
    run_reported_job("Resetting music library", task)

@socketio.on('start_mp3_convert')
def run_mp3_convert_only():
    """
    Background task to transcode existing FLAC library files to MP3
    (320kbps, 48000Hz) in place -- no re-downloading.
    """
    def task(job):
        job.update(None, "Converting FLAC files")
        main.convert_library_to_mp3()
    run_reported_job("Converting library to MP3", task)

@socketio.on('start_covers')
def run_covers_only():
    """
    Background task to extract and process album artwork.
    """
    def task(job):
        job.update(None, "Processing artwork")
        main.process_songs()
    run_reported_job("Processing album covers", task)

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
