# Deployment topology

This matters for every change to this repo — read it before assuming a fix is "live."

- **This working copy (`C:\youtubemp3` on this dev machine) is not the server.** It's a
  separate machine from the one actually running the app. Edits here have zero effect on
  what the user's browser hits until they're deployed.
- **Deploy flow is manual and one-way:** edit/commit here → push to GitHub
  (bohrtein/Youtube-Mp3-Downloader) → the user separately pulls that same repo onto their
  server and runs it there themselves (`git pull` + restart the Flask process). Nothing
  here triggers that pull or restart automatically.
- **The server is reached at `http://192.168.2.111:8000/app/youtube-mp3-downloader/`**
  (LAN IP, behind a reverse proxy with path prefix `/app/youtube-mp3-downloader/` — see
  `PrefixMiddleware` / `APP_PREFIX` in `app.py`). The user's browser (on their own separate
  "main computer") talks to that server over the LAN/SSH tunnel — not to this dev machine.
- **Practical consequence:** after pushing a fix, it is NOT verified working until the user
  confirms they've pulled + restarted on the server *and* re-tested from their own browser
  against `192.168.2.111`. Testing/running things locally on this dev machine (e.g. `python
  app.py`, hitting `localhost`) does not represent what the user actually experiences —
  their browser, their downloads folder, and the real server process are all on machines
  this session cannot directly see or control. When debugging a "doesn't work" report,
  always ask what got run on the server side (pull + restart) before assuming the code
  itself is still wrong.
