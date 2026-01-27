🎵 YouTube FLAC Downloader

A web-based tool to download high-quality music from YouTube and manage a local digital library.
🚀 Two Ways to Use

    Download Only: You do not need MySQL. You can simply run the app to download and process FLAC files directly to your folder.

    Local Library: To use the "Library" and "Album" views on the website, SQL is mandatory. This saves your music metadata so you can browse your collection anytime.

🛠️ Quick Start

    Install Requirements:
    Bash

    pip install flask flask-socketio mysql-connector-python mutagen pillow python-dotenv

    Database (Optional): If you want the Library feature, create a .env file with your DB credentials and run the script in sqlFiles/database.sql.

    Launch:
    Bash

    python app.py

    Open http://127.0.0.1:5000 in your browser.

📂 File Layout

    app.py: Runs the website interface.

    main.py: Handles the download and sync logic.

    core/: Scripts for yt-dlp, FFmpeg, and image resizing.

    downloads/: Where your music is saved.

📝 Features

    Auto-Cleanup: Automatically resizes album art and cleans artist tags.

    Self-Healing: Downloads yt-dlp and ffmpeg automatically on first run.

    Real-time: Watch download progress live on the dashboard.

Developed by bohrtein
