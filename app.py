import threading
from flask import Flask, render_template, Response
from flask_socketio import SocketIO 
import database.databaseConnector as databaseConnector
import mainFiles.checkDependencies as checkDependencies
import main

# Initialize Flask application and SocketIO for real-time communication
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- WEB ROUTES ---

@app.route('/')
def main_dashboard():
    """
    Renders the primary control dashboard.
    """
    return render_template('main.html')

@app.route('/library')
def library_view():
    """
    Fetches all albums from the database gallery view and renders the library page.
    """
    conn = databaseConnector.connect_to_db()
    # dictionary=True allows accessing columns by name (e.g., album['album_name'])
    cursor = conn.cursor(dictionary=True, buffered=True)
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
    cursor = conn.cursor(dictionary=True, buffered=True)
    
    # 1. Get Album Info (Joins artist table to get the name)
    cursor.execute("""
        SELECT alb.album_name, art.artist_name 
        FROM albums alb 
        JOIN artists art ON alb.artist_id = art.artist_id 
        WHERE alb.album_id = %s""", (album_id,))
    album_info = cursor.fetchone()
    
    # 2. Get Songs ordered by track number
    cursor.execute("SELECT * FROM songs WHERE album_id = %s ORDER BY track_number", (album_id,))
    songs = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('album.html', album=album_info, songs=songs, album_id=album_id)

@app.route('/cover/<int:album_id>')
def get_cover(album_id):
    """
    Streams the raw BLOB image data from the database as a JPEG response.
    """
    conn = databaseConnector.connect_to_db()
    cursor = conn.cursor(buffered=True)
    cursor.execute("SELECT cover_data FROM albums WHERE album_id = %s", (album_id,))
    res = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if res and res[0]:
        return Response(res[0], mimetype='image/jpeg')
    return "" 

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
        cursor.execute("DELETE FROM songs WHERE album_id = %s", (album_id,))
        cursor.execute("DELETE FROM albums WHERE album_id = %s", (album_id,))
        
        conn.commit()
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
        cursor.execute("DELETE FROM songs WHERE song_id = %s", (song_id,))
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
    socketio.run(app, debug=True)