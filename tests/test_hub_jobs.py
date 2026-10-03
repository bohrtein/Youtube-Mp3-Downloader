import json
import subprocess
import threading

import pytest

from core import hubJobs, playlistDownloader
from conftest import ADMIN_HEADERS


def test_reporting_is_optional_and_best_effort(monkeypatch):
    monkeypatch.delenv("APPHUB_URL", raising=False)
    calls = []
    def unavailable(req, timeout):
        calls.append((req, timeout))
        raise OSError("Hub offline")
    monkeypatch.setattr(hubJobs.urllib.request, "urlopen", unavailable)
    hubJobs.report("test", state="running")
    assert not calls
    monkeypatch.setenv("APPHUB_URL", "http://hub/")
    monkeypatch.setenv("APPHUB_PROXY_SECRET", "secret")
    hubJobs.report("test", state="running", progress=None, open="library")
    req, timeout = calls[0]
    assert req.full_url == "http://hub/api/jobs" and timeout == 2
    assert req.get_header("X-apphub-auth") == "secret"
    assert json.loads(req.data) == {"id": "test", "state": "running", "open": "library"}


@pytest.mark.parametrize("outcome", ["done", "failed", "cancelled"])
def test_job_lifecycle_is_terminal_and_throttled(monkeypatch, outcome):
    reports, events = [], []
    monkeypatch.setattr(hubJobs, "report", lambda job_id, **fields: reports.append(fields))
    job = hubJobs.Job("Sample download", events.append, cancellable=True)
    def work(job):
        job.update(10, "Track 1")
        job.update(20, "Track 2")
        if outcome == "failed":
            raise RuntimeError("Download failed")
        if outcome == "cancelled":
            assert hubJobs.cancel(job.id)
    job.run(work)
    assert reports[0]["state"] == "running"
    assert reports[1]["progress"] == 10
    assert reports[-1]["state"] == outcome
    assert reports[0]["cancel"] == f"api/downloads/{job.id}/cancel"
    assert events[-1]["state"] == outcome
    assert not hubJobs.cancel(job.id)
    count = len(reports)
    job.update(50, "Stale worker", force=True)
    assert len(reports) == count


def test_cancel_queued_job_does_not_wait_for_download_lock(monkeypatch, client):
    monkeypatch.setattr(hubJobs, "report", lambda *a, **k: None)
    lock = threading.Lock()
    lock.acquire()
    job = hubJobs.Job("Queued download", lambda data: None, cancellable=True)
    response = client.post(f"/api/downloads/{job.id}/cancel", headers=ADMIN_HEADERS)
    assert response.get_json()["success"]
    assert not hubJobs.acquire_download_lock(lock, job.cancel_event)
    job.run(lambda job: "cancelled")
    lock.release()
    assert client.post(f"/api/downloads/{job.id}/cancel", headers=ADMIN_HEADERS).status_code == 404


def test_cancel_active_download_terminates_subprocess(monkeypatch):
    event = threading.Event()
    class Process:
        returncode = 0
        terminated = False
        def communicate(self, timeout=None):
            if not self.terminated:
                event.set()
                raise subprocess.TimeoutExpired("yt-dlp", timeout)
            return "", ""
        def terminate(self):
            self.terminated = True
    process = Process()
    monkeypatch.setattr(playlistDownloader.subprocess, "Popen", lambda *a, **k: process)
    with pytest.raises(RuntimeError, match="cancelled"):
        playlistDownloader._run_download(["yt-dlp"], event)
    assert process.terminated


def test_dashboard_job_reports_download_failure(monkeypatch, client):
    import app
    reports, workers = [], []
    monkeypatch.setattr(hubJobs, "report", lambda job_id, **fields: reports.append(fields))
    monkeypatch.setattr(app.socketio, "start_background_task", lambda fn, *args: workers.append((fn, args)))
    monkeypatch.setattr(app.checkDependencies, "dependencies_check", lambda: None)
    def fail(*args, **kwargs):
        raise RuntimeError("No audio")
    monkeypatch.setattr(app.main, "start_downloading", fail)
    sock = app.socketio.test_client(app.app, headers=ADMIN_HEADERS)
    result = sock.emit("start_download_batch", {"urls": ["https://youtu.be/example"]}, callback=True)
    fn, args = workers.pop()
    fn(*args)
    assert result["job_id"]
    assert reports[-1]["state"] == "failed"
    sock.disconnect()


def test_approval_cancel_keeps_unfinished_songs_retryable(monkeypatch, client, friend):
    import app
    from core import approvedDownloads
    from database import suggestionsRepo
    submission = suggestionsRepo.create_submission(friend["friend_id"], "", [
        {"youtube_id": "Cp31A_iqoDw", "title": "Sample", "kept": 1,
         "source": "yt_search", "in_library": "no"},
    ])
    items = suggestionsRepo.get_submission(submission)["items"]
    workers, reports = [], []
    monkeypatch.setattr(app.socketio, "start_background_task", lambda fn, *args: workers.append((fn, args)))
    monkeypatch.setattr(hubJobs, "report", lambda job_id, **fields: reports.append(fields))
    result = client.post(f"/review/{submission}/approve", headers=ADMIN_HEADERS,
                         json={"item_ids": [items[0]["item_id"]]}).get_json()
    assert result["job_id"]
    assert reports[0]["open"] == f"review/{submission}"
    assert client.post(f"/api/downloads/{result['job_id']}/cancel", headers=ADMIN_HEADERS).status_code == 200
    fn, args = workers.pop()
    fn(*args)
    assert reports[-1]["state"] == "cancelled"
    assert suggestionsRepo.get_item(items[0]["item_id"])["decision"] == "failed"
    assert not approvedDownloads.download_lock.locked()
