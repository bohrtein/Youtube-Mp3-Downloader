Markdown

# 🎵 YouTube FLAC Downloader

A web-based tool to download high-quality music from YouTube and manage a local digital library.

## 🚀 Two Ways to Use

1.  **Download Only:** You **do not** need MySQL. You can simply run the app to download and process FLAC files directly to your storage folder.
2.  **Local Library:** To use the "Library" and "Album" views on the website, **SQL is mandatory**. This saves your music metadata so you can browse and manage your collection through the UI.

---

## 🛠️ Quick Start

### 1. Install Requirements
```bash
pip install flask flask-socketio mysql-connector-python mutagen pillow python-dotenv

2. Database Setup (Optional)

If you want the Library features, create a .env file in the root directory:
Kod snippet'i

DB_HOST=localhost
DB_USER=root
DB_PASS=your_password
DB_NAME=your_db_name

Then, execute the script found in sqlFiles/database.sql on your MySQL server.
3. Launch the App
Bash

python app.py

Once running, open your browser to: http://127.0.0.1:5000
📂 Project Structure

    app.py: The main Flask server and web interface.

    main.py: The backend orchestrator for downloads and sync tasks.

    mainFiles/: Core logic for yt-dlp, FFmpeg management, and image processing.

    database/: Logic for SQL connections and library synchronization.

    downloads/: The default directory where your music is organized.

📝 Key Features

    Auto-Cleanup: Automatically resizes album art to 250x250 and cleans artist tags (removes "feat." for cleaner sorting).

    Self-Healing: On the first run, the app automatically detects and downloads yt-dlp.exe and ffmpeg.exe if they are missing.

    Real-time Tracking: Watch your download queue progress live via the web dashboard.

    Smart Deduplication: Prioritizes keeping files inside proper "Album" folders to keep your library organized.

Developed by bohrtein
