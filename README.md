# 🎵 YouTube FLAC/MP3 Downloader

A web-based tool to download high-quality music from YouTube and manage a local digital library.
This program specifically designed to download music to fioo snowsky echo mini

## Database

No server, no setup. The "Library" and "Album" views are backed by a local SQLite file, `library.db`, created automatically at the project root the first time you run the app. Album covers are saved alongside it as plain JPEG files in `static/covers/`.

## Screenshots

### Dashboard
Pick your library folder with the built-in folder browser, then download, sync, deduplicate, or process covers — all from one page.
![Dashboard](docs/screenshots/dashboard.png)

### Library
Every synced album, browsable and searchable.
![Library](docs/screenshots/library.png)

### Album
Track list with duration, bitrate, and a link back to the original source video.
![Album detail](docs/screenshots/album.png)

## 🛠️ Quick Start

### 1. Install Requirements
```bash
pip install -r requirements.txt
```
### 2. Launch the App
```bash
python app.py
```
Once running, open your browser to: http://127.0.0.1:5000

### 3. Set Your Library Folder
On the Dashboard, click **Change** next to "Library Folder" and browse to wherever your music should live. This is saved automatically and used right away — no restart needed, and no more hardcoded `downloads/` folder.

----
## 🌐 The Interface Layer
These files handle everything the user sees in their browser.

#### app.py
The heart of the web server. It routes user requests (like clicking "Download") to the backend, uses SocketIO to send live updates back to your screen without refreshing the page, and exposes the folder-browser endpoints (`/browse_folders`, `/set_library_folder`) behind the Dashboard's folder picker.

#### templates/
Contains the HTML structure for your pages (main, library, and album).

#### static/matrix.css, static/matrix.js, static/app.css
The "Matrix" design system (phosphor-on-black terminal look, digital rain background, liquid glass panels) plus this app's own page-specific layout built on top of it.

----
## ⚙️ The Backend Engine
Located mostly in core/, these scripts do the heavy lifting.

#### main.py
The "Boss" script. It coordinates between the web server and the individual processing tasks, always reading the current library folder from the database so a change takes effect immediately.

#### playlistDownloader.py
Controls yt-dlp.exe. It manages the download queue and ensures files are saved with the correct naming convention. Downloads FLAC by default, or MP3 (320kbps / 48kHz) when the Dashboard's MP3 toggle is on.

#### convertToMp3.py
Transcodes the FLAC files already in your library to MP3 (320kbps / 48kHz) with ffmpeg — no re-downloading — keeping tags and cover art, deleting each FLAC once its MP3 is written, then re-syncing the database. MP3 is much cheaper for a portable player to decode than FLAC, so it goes easier on the battery.

#### audioTags.py
Reads and writes tags and cover art the same way for FLAC and MP3, so sync, covers, and dedupe work on both formats.

#### checkDependencies.py
A safety script that runs at startup. If it doesn't see ffmpeg or yt-dlp in your folder, it uses curl to download them for you automatically.

#### processAlbumCover.py
The "Artist" script. It extracts the cover art from the music file, crops it into a perfect square, resizes it to 250x250, and cleans up the "Artist" tags so your library looks professional.

#### cleanupManager.py
The "Janitor." It scans for duplicate songs and makes sure you don't have multiple copies of the same track cluttering your drive. When the same track exists as both FLAC and MP3, it keeps the MP3.


## 🗄️ The Storage & Data Layer

These files manage how your music is saved and remembered.

#### database/databaseConnector.py
Opens the local SQLite file (library.db) and creates the schema automatically if it doesn't exist yet. Also stores app settings — currently just your chosen library folder — in a small `settings` table.

#### database/syncLibrary.py
The "Librarian." It looks at the files in your library folder and writes their information (title, bitrate, duration) into the SQL tables, saving cover art as a JPEG in static/covers/.

#### sqlFiles/database.sql
The blueprint, kept for reference. This is the schema databaseConnector.py builds automatically in library.db.

#### static/covers/
Where processed 250x250 album cover JPEGs live, one per album (`<album_id>.jpg`).

#### downloads/
The default library folder where your music lives if you haven't picked a different one on the Dashboard. Organized by Playlist Name / Track Number - Title.flac (or .mp3).

## 🔑 Configuration
#### .gitignore
A list that tells Git to ignore temporary files, library.db, generated covers, and your actual music downloads so your GitHub repository stays small and clean.

## 🤝 Friend Suggestions

Friends get a personal link (`/suggest/<token>/`) where they can search (Song / Artist / Album), paste YouTube, YouTube Music or Spotify links, browse the library read-only, fill a basket, untick what they don't want, and send it. Nothing downloads until you approve it on **Suggestions** (dashboard top bar). There you see who sent what, what they kept and what they unticked, and flags such as live/cover/lyrics versions, length mismatches against Spotify, non-official uploaders and songs already in the library. You can fix a match, then download the songs you pick into `Artist/Album/NN - Title` in your library folder. Manage links on **Friends**.

- `routes/friendsPublic.py`: the only public pages. Unknown or revoked tokens return 404, pages send a strict CSP and `no-referrer`, and a submission can only contain songs the server actually showed that friend.
- `routes/suggestAdmin.py`: friends, review, fix match, approve/reject.
- `core/lookupJobs.py`: friend searches run one at a time in the background (the page polls). Results are cached in `lookup_cache`, per-friend limits (30 searches/hour, 10 links/hour, 5 submissions/day, at most 3 waiting) and a server-wide budget of 300 yt-dlp calls/day are stored in `usage_events`, and yt-dlp calls are spaced 2 s apart.
- `core/approvedDownloads.py`: downloads approved songs, writes artist/album/title/track tags, moves them into place and syncs just those folders.
- `core/spotifyClient.py`: reads Spotify playlists, albums and tracks from Spotify's public embed pages, with no account or API key. The official Web API now needs a Premium developer account and only returns playlists the key's owner made. This is unofficial: if Spotify changes the embed page, Spotify links stop working until it's updated, and only the first 100 songs of a playlist come through. Each song is then matched on YouTube.

### Server setup (behind the App Hub)

Admin routes return 404 unless the request came through the App Hub login (the hub sends a per-process secret in `X-Apphub-Auth`). The hub must be a version with `public_paths` support. In `apps/youtube-mp3-downloader/app.toml` on the server:

```toml
health_path = "/healthz"
idle_timeout_minutes = 60          # approval downloads run in the background
public_paths = ["/suggest/", "/static/"]
```

Friends reach the app through Tailscale Funnel on its own port, exposing only the public paths:

```bash
tailscale funnel --bg --https=8443 --set-path /app/youtube-mp3-downloader/suggest http://127.0.0.1:8000/app/youtube-mp3-downloader/suggest
tailscale funnel --bg --https=8443 --set-path /app/youtube-mp3-downloader/static http://127.0.0.1:8000/app/youtube-mp3-downloader/static
```

Then put `https://<server>.<tailnet>.ts.net:8443` into **Friends → public address** so the copied links point there.

### Tests

```bash
pip install pytest
python -m pytest tests
```

## 🤖 Agent Skill: YouTube Music Download

`.claude/skills/youtube-music-download/SKILL.md` teaches an agent (e.g. Claude Code)
to search YouTube Music and download a song, an album, or an artist's studio
discography straight to the computer's Downloads folder - completely separate
from the library folder/`library.db` above. It's backed by three new modules:

- `core/musicSearch.py` - searches YouTube Music for songs, album candidates, and an artist's releases (yt-dlp wrappers, no scraping).
- `core/releaseDedup.py` - normalizes release titles so duplicate editions (deluxe/extended/remaster) collapse to one, and filters out live albums/compilations.
- `core/smartDownload.py` - the CLI that ties it together: `python -m core.smartDownload --song/--album/--artist ...` prints a plan first, and only downloads once told to with `--download`.

Developed by bohrtein
