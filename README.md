Markdown

# 🎵 YouTube FLAC Downloader

A web-based tool to download high-quality music from YouTube and manage a local digital library.
This program specifically designed to download music to fioo snowsky echo mini

## SQL

1.  You **do not** need MySQL. You can simply run the app to download and process FLAC files directly to your storage folder.
2.  To use the "Library" and "Album" views on the website, **SQL is mandatory**. This saves your music metadata so you can browse and manage your collection through the UI.

---
### Local Library Screenshot
<img width="2559" height="1439" alt="Screenshot 2026-01-26 231516" src="https://github.com/user-attachments/assets/b75112ae-ffc4-42f5-88be-ca0b9f3a8500" />

## 🛠️ Quick Start

### 1. Install Requirements
```bash
pip install flask flask-socketio mysql-connector-python mutagen pillow python-dotenv
```
### 2. Database Setup (Optional)

If you want the Library features, create a .env file in the root directory:
```bash
DB_HOST=localhost
DB_USER=root
DB_PASS=your_password
DB_NAME=your_db_name
```
Then, execute the script found in sqlFiles/database.sql on your MySQL server.
### 3. Launch the App
```bash
python app.py
```
Once running, open your browser to: http://127.0.0.1:5000

----
## 🌐 The Interface Layer
These files handle everything the user sees in their browser.

#### app.py
The heart of the web server. It routes user requests (like clicking "Download") to the backend and uses SocketIO to send live updates back to your screen without refreshing the page.

#### templates/
Contains the HTML structure for your pages (main, library, and album).

#### Static/style.css
The design file that makes the website look clean and organized.d sync tasks.

----
## ⚙️ The Backend Engine
Located mostly in mainFiles/, these scripts do the heavy lifting.

#### main.py
The "Boss" script. It coordinates between the web server and the individual processing tasks.

#### playlistDownloader.py
Controls yt-dlp.exe. It manages the download queue and ensures files are saved with the correct naming convention.

#### checkDependencies.py
A safety script that runs at startup. If it doesn't see ffmpeg or yt-dlp in your folder, it uses curl to download them for you automatically.

#### processAlbumCover.py
The "Artist" script. It extracts the cover art from the music file, crops it into a perfect square, resizes it to 250x250, and cleans up the "Artist" tags so your library looks professional.

#### cleanupManager.py
The "Janitor." It scans for duplicate songs and makes sure you don't have multiple copies of the same track cluttering your drive.


## 🗄️ The Storage & Data Layer

These files manage how your music is saved and remembered.

#### database/databaseConnector.py
Handles the handshake between Python and your MySQL server. It reads your .env file to log in securely.

#### database/syncLibrary.py
The "Librarian." It looks at the files in your downloads/ folder and writes their information (title, bitrate, duration, and cover art) into the SQL tables.

#### sqlFiles/database.sql
The blueprint. This contains the code to build the artists, albums, and songs tables in MySQL.

#### downloads/
The physical folder where your music lives. Organized by Playlist Name / Track Number - Title.flac.

## 🔑 Configuration
#### .env
A private text file where you keep your database password. Never upload this to GitHub!

#### .gitignore
A list that tells Git to ignore temporary files, your .env, and your actual music downloads so your GitHub repository stays small and clean.

Developed by bohrtein


