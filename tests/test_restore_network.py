import io
import json
import subprocess
import threading
from urllib.error import URLError

import pytest

from core import restoreNetwork


@pytest.mark.parametrize("message", [
    "ERROR: unable to download video data: HTTP Error 429: Too Many Requests",
    "The current session has been rate-limited by YouTube for up to an hour.",
    "ERROR: [youtube] Sign in to confirm you’re not a bot.",
    "ERROR: [youtube] This content isn't available, try again later",
])
def test_detects_youtube_rate_limits(message):
    assert restoreNetwork.is_rate_limited(message)


def test_private_video_and_generic_forbidden_do_not_trigger_rotation():
    assert not restoreNetwork.is_rate_limited("ERROR: [youtube] Private video")
    assert not restoreNetwork.is_rate_limited("ERROR: unable to download video data: HTTP Error 403: Forbidden")


def test_vpn_rotation_executes_the_configured_path_once(tmp_path, monkeypatch):
    executable = tmp_path / "VPN rotate"
    monkeypatch.setenv("LIBRARY_RESTORE_VPN_ROTATE", str(executable))
    monkeypatch.setenv("LIBRARY_RESTORE_GLUETUN_URL", "http://127.0.0.1:8011")
    invocations = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **options: invocations.append((argv, options)))
    cancelled = threading.Event()

    restoreNetwork.rotate_vpn(cancelled)
    cancelled.set()
    restoreNetwork.rotate_vpn(cancelled)

    [(argv, options)] = invocations
    assert argv == [str(executable)]
    assert options["timeout"] == restoreNetwork.VPN_ROTATION_TIMEOUT
    assert options["check"] is True


def test_missing_or_timed_out_hook_has_an_actionable_error(tmp_path, monkeypatch):
    monkeypatch.delenv("LIBRARY_RESTORE_VPN_ROTATE", raising=False)
    monkeypatch.delenv("LIBRARY_RESTORE_GLUETUN_URL", raising=False)
    cancel_event = threading.Event()
    with pytest.raises(restoreNetwork.VPNRotationError, match="LIBRARY_RESTORE_VPN_ROTATE"):
        restoreNetwork.rotate_vpn(cancel_event)

    monkeypatch.setenv("LIBRARY_RESTORE_VPN_ROTATE", str(tmp_path / "rotate"))

    def time_out(argv, **options):
        raise subprocess.TimeoutExpired(argv, options["timeout"])

    monkeypatch.setattr(subprocess, "run", time_out)
    with pytest.raises(restoreNetwork.VPNRotationError, match="timed out"):
        restoreNetwork.rotate_vpn(cancel_event)


@pytest.fixture
def gluetun(monkeypatch):
    monkeypatch.delenv("LIBRARY_RESTORE_VPN_ROTATE", raising=False)
    monkeypatch.setenv("LIBRARY_RESTORE_GLUETUN_URL", "http://127.0.0.1:8011")
    monkeypatch.setenv("LIBRARY_RESTORE_GLUETUN_API_KEY", "test-key")
    monkeypatch.setenv("LIBRARY_RESTORE_VPN_PROXY", "http://127.0.0.1:8888")
    return threading.Event()


def test_gluetun_waits_for_different_ip_even_if_cancelled(gluetun, monkeypatch):
    requests = []
    ips = iter(["8.8.8.8", "8.8.8.8", "1.1.1.1"])

    class Opener:
        def open(self, req, timeout):
            assert req.get_header("X-api-key") == "test-key"
            assert req.full_url.startswith("http://127.0.0.1:8011/v1/")
            if req.get_method() == "GET":
                assert req.full_url.endswith("/publicip/ip")
                requests.append("IP")
                return io.BytesIO(json.dumps({"public_ip": next(ips)}).encode())
            assert req.full_url.endswith("/vpn/status")
            status = json.loads(req.data)["status"]
            requests.append(status)
            if status == "stopped":
                gluetun.set()
            return io.BytesIO()

    def opener(proxy_handler, redirect_handler):
        assert proxy_handler.proxies == {}
        assert redirect_handler.redirect_request(None, None, 302, "Found", {}, "http://other-host") is None
        return Opener()

    monkeypatch.setattr(restoreNetwork, "build_opener", opener)
    monkeypatch.setattr(restoreNetwork.time, "sleep", lambda seconds: None)
    restoreNetwork.rotate_vpn(gluetun)
    assert requests == ["IP", "stopped", "running", "IP", "IP"]


def test_gluetun_restarts_when_stop_response_is_lost(gluetun, monkeypatch):
    statuses = []

    class Opener:
        def open(self, req, timeout):
            if req.get_method() == "GET":
                return io.BytesIO(b'{"public_ip":"8.8.8.8"}')
            status = json.loads(req.data)["status"]
            statuses.append(status)
            if status == "stopped":
                raise URLError("connection lost")
            return io.BytesIO()

    monkeypatch.setattr(restoreNetwork, "build_opener", lambda *handlers: Opener())
    with pytest.raises(restoreNetwork.VPNRotationError, match="valid response"):
        restoreNetwork.rotate_vpn(gluetun)
    assert statuses == ["stopped", "running"]


def test_gluetun_reports_timeout_if_exit_ip_is_unchanged(gluetun, monkeypatch):
    clock = [0]

    class Opener:
        def open(self, req, timeout):
            return io.BytesIO(b'{"public_ip":"8.8.8.8"}')

    def sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(restoreNetwork, "build_opener", lambda *handlers: Opener())
    monkeypatch.setattr(restoreNetwork.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(restoreNetwork.time, "sleep", sleep)
    with pytest.raises(restoreNetwork.VPNRotationError, match="different public IP"):
        restoreNetwork.rotate_vpn(gluetun)
    assert clock[0] == restoreNetwork.VPN_ROTATION_TIMEOUT


def test_gluetun_rejects_plaintext_remote_control(gluetun, monkeypatch):
    monkeypatch.setenv("LIBRARY_RESTORE_GLUETUN_URL", "http://192.168.2.111:8011")
    with pytest.raises(restoreNetwork.VPNRotationError, match="HTTPS and an API key"):
        restoreNetwork.rotate_vpn(gluetun)


def test_gluetun_rotation_requires_download_proxy(gluetun, monkeypatch):
    monkeypatch.delenv("LIBRARY_RESTORE_VPN_PROXY", raising=False)
    with pytest.raises(restoreNetwork.VPNRotationError, match="LIBRARY_RESTORE_VPN_PROXY"):
        restoreNetwork.rotate_vpn(gluetun)
