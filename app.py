import os
import string
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import database.databaseConnector as databaseConnector
import core.checkDependencies as checkDependencies
import main


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
socketio = SocketIO(app, cors_allowed_origins="*")

# Ensure the local SQLite database and schema exist before the first request
databaseConnector.init_db()

# --- WEB ROUTES ---

@app.route('/')
def main_dashboard():
    """
    Renders the primary control dashboard.
    """
    return render_template('main.html', library_folder=databaseConnector.get_library_folder())

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
    """
    conn = databaseConnector.connect_to_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM album_gallery")
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
    Performs a cascading delete: removes songs before removing the album record.
    """
    conn = databaseConnector.connect_to_db()
    if not conn: return {"success": False, "message": "DB Connection failed"}, 500
    
    try:
        cursor = conn.cursor()
        # Delete songs first to satisfy potential Foreign Key constraints
        cursor.execute("DELETE FROM songs WHERE album_id = ?", (album_id,))
        cursor.execute("DELETE FROM albums WHERE album_id = ?", (album_id,))

        conn.commit()

        cover_path = os.path.join('static', 'covers', f'{album_id}.jpg')
        if os.path.exists(cover_path):
            os.remove(cover_path)

        return {"success": True, "message": "Album deleted successfully"}
    except Exception as e:
        return {"success": False, "message": str(e)}, 500
    finally:
        cursor.close()
        conn.close()

@app.route('/delete_song/<int:song_id>', methods=['DELETE'])
def delete_song(song_id):
    """
    Removes a single song record from the database.
    """
    conn = databaseConnector.connect_to_db()
    if not conn:
        return {"success": False, "message": "Database connection failed"}, 500

    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM songs WHERE song_id = ?", (song_id,))
        conn.commit()
        return {"success": True, "message": "Song removed from database"}
    except Exception as e:
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

    def background_task():
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
                main.start_downloading(url)
            except Exception as e:
                print(f"Error downloading {url}: {e}")
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