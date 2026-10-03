"""Best-effort App Hub reporting and cancellable background job lifecycles."""
import json
import os
import threading
import time
import urllib.request
import uuid

from core import interfaceComponents

_jobs = {}
_jobs_lock = threading.Lock()


def report(job_id, **fields):
    hub_url = os.environ.get("APPHUB_URL")
    if not hub_url:
        return
    try:
        body = json.dumps({"id": job_id, **{k: v for k, v in fields.items() if v is not None}}).encode()
        req = urllib.request.Request(
            hub_url.rstrip("/") + "/api/jobs", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "X-Apphub-Auth": os.environ.get("APPHUB_PROXY_SECRET", "")},
        )
        with urllib.request.urlopen(req, timeout=2):
            pass
    except Exception:
        pass  # Reporting must never break the underlying task.


def cancel(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    return bool(job and job.request_cancel())


class Job:
    def __init__(self, title, emit, open_path="library", cancellable=False):
        self.id = "download-" + uuid.uuid4().hex
        self.title = title
        self.emit = emit
        self.open_path = open_path
        self.cancellable = cancellable
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._state = "running"
        self._percent = None
        self._detail = "Queued"
        self._last_report = 0
        with _jobs_lock:
            _jobs[self.id] = self
        self.update(None, "Queued", force=True)

    def _publish(self, force=False):
        now = time.monotonic()
        if force or now - self._last_report >= 10:
            report(self.id, title=self.title, state=self._state, progress=self._percent,
                   detail=self._detail, open=self.open_path,
                   cancel=f"api/downloads/{self.id}/cancel" if self.cancellable else None)
            self._last_report = now
        self.emit({"job_id": self.id, "title": self.title, "state": self._state,
                   "percent": self._percent, "status": self._detail,
                   "cancellable": self.cancellable and self._state == "running"})

    def update(self, percent, detail, force=False):
        with self._lock:
            if self._state != "running":
                return
            force = force or (self._percent is None and percent is not None)
            self._percent = max(0, min(100, percent)) if percent is not None else None
            self._detail = detail
            self._publish(force)

    def request_cancel(self):
        with self._lock:
            if self._state != "running" or not self.cancellable:
                return False
            self.cancel_event.set()
            self._detail = "Cancelling…"
            self._publish(force=True)
            return True

    def run(self, work):
        def heartbeat():
            while not self._stop.wait(30):
                with self._lock:
                    if self._state == "running":
                        self._publish(force=True)

        threading.Thread(target=heartbeat, daemon=True).start()
        try:
            result = work(self)
            state = result if result in ("done", "failed", "cancelled") else "done"
        except Exception as exc:
            interfaceComponents.Print_Tag(f"{self.title}: {exc}", tag="Error")
            state = "failed"
        finally:
            self._stop.set()
        with self._lock:
            self._state = "cancelled" if self.cancel_event.is_set() else state
            self._percent = 100 if self._state == "done" else self._percent
            self._detail = {"done": "Complete", "failed": "Task failed — check the server log",
                            "cancelled": "Download cancelled"}[self._state]
            self._publish(force=True)
        with _jobs_lock:
            _jobs.pop(self.id, None)


def acquire_download_lock(lock, cancel_event):
    """Queued jobs can cancel without waiting for the active download."""
    while not cancel_event.is_set():
        if lock.acquire(timeout=0.25):
            if cancel_event.is_set():
                lock.release()
                return False
            return True
    return False
