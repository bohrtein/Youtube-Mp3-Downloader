---
name: youtube-music-download
description: Search YouTube Music and download a song, an album, or an artist's studio discography straight to the computer's Downloads folder - as FLAC, deduped so only one edition of each release is kept. Use when the user asks to "download this album", "get me the new X album", "download everything by Y", "grab this song off youtube/youtube music", or similar. Do NOT use this for the app's normal library-sync workflow (the Dashboard's configured library folder / MP3 player / library.db) - that's a separate, unrelated flow.
---

# YouTube Music Download

This skill drives this repo's own download engine to fetch music **onto the
computer's Downloads folder** - a separate, disposable location from the
app's normal "library folder" (the one configured on the Dashboard, which
feeds the user's MP3 player and gets synced into `library.db`). Never mix
the two up.

## Orientation

- `core/playlistDownloader.py` - the actual yt-dlp-based FLAC downloader. Already used by the rest of the app; this skill calls it too, just with a different destination folder.
- `core/checkDependencies.py` - ensures `yt-dlp.exe`/`ffmpeg.exe`/`ffprobe.exe` are present. Always gets called before a real download.
- `core/musicSearch.py` **(new, added for this skill)** - searches YouTube Music for songs, album candidates, and an artist's channel/releases. Uses ytmusicapi for song/artist search and yt-dlp for albums and playlists.
- `core/releaseDedup.py` **(new)** - normalizes release titles (so "Album", "Album (Deluxe Edition)", "Album (Extended)" are recognized as the same release) and filters out live albums/compilations.
- `core/smartDownload.py` **(new)** - ties the above together into one CLI: builds a plan (what would be downloaded, what's being skipped and why), and only downloads when told to.
- `database/databaseConnector.py`'s `get_library_folder()` / `library.db` / `database/syncLibrary.py` - the **unrelated** MP3-player library workflow. This skill never reads or writes any of that, and never needs the Flask app (`app.py`) running.

## Procedure

1. **Classify the request**: a single song, a single album, or an artist's whole discography.

2. **Build a plan first - never download blind.** Run one of:
   ```
   python -m core.smartDownload --song "Artist Song Title"
   python -m core.smartDownload --album "Artist Name" "Album Name"
   python -m core.smartDownload --artist "Artist Name"
   ```
   Without `--download`, these only print a JSON plan (`kept` = what would be fetched, `skipped` = what was set aside and why). Nothing is downloaded yet.

3. **Review the plan before doing anything else:**
   - Does `kept` look like the right song/album/artist? If the request was ambiguous (a common album/artist name, multiple plausible matches) or `plan_artist` came back with an `error` (channel/releases couldn't be confidently found), **ask the user** rather than guessing at a URL.
   - Do the `skipped` entries make sense? They should be genuine duplicate editions (deluxe/extended/remaster) or, for artist requests, live albums/compilations - not something the user actually wanted.

4. **Only once the plan looks right**, re-run the same command with `--download` added. Optionally add `--dest PATH` to override the destination; otherwise it defaults to the OS Downloads folder (`~/Downloads` / `%USERPROFILE%\Downloads`).

5. **Report back** what was downloaded (title + where), and what was skipped and why - so the user can see the "smart" filtering that happened rather than a silent black box.

## Rules

- **Never download more than one edition of the same release** (e.g. standard + deluxe + extended cut of the same album) unless the user explicitly names the specific edition they want.
- **"Download all of this artist's albums" means studio albums only** - live albums, concert recordings, and compilations ("Greatest Hits", "Best Of", anthologies) are skipped automatically, unless the user explicitly asks for those too.
- **Never touch the configured library folder or `library.db`** for this workflow - that belongs to the Dashboard/MP3-player sync flow, not to ad-hoc downloads.
- **Never guess a channel or URL when discovery is ambiguous** (`plan_artist` returning an `error`, or an album search matching an unexpected artist) - ask the user instead of downloading the wrong thing.
- Downloads are FLAC with embedded metadata/thumbnail, matching the rest of the app's existing pipeline - there's no need (or flag) to change format.

## Example

```
$ python -m core.smartDownload --album "Daft Punk" "Random Access Memories"
{
  "kind": "album",
  "kept": [{"title": "Random Access Memories", "url": "https://music.youtube.com/playlist?list=...", "uploader": "Daft Punk", "track_count": 13}],
  "skipped": [
    {"release": {"title": "Random Access Memories (10th Anniversary Edition)", ...}, "reason": "duplicate edition of the same release", "kept_instead": "Random Access Memories"}
  ]
}
```
Plan looks right → re-run with `--download` to actually fetch it into the Downloads folder.
