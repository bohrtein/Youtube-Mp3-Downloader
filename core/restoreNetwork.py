"""Network settings and YouTube limit handling for library restores."""
import ipaddress
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


VPN_ROTATION_LIMIT = 3
VPN_ROTATION_TIMEOUT = 90
GLUETUN_REQUEST_TIMEOUT = 5
GLUETUN_POLL_INTERVAL = 2
_RATE_LIMIT = re.compile(
    r"\b(?:HTTP(?: Error)?\s+429|Too Many Requests|rate[- ]limit(?:ed)?|"
    r"sign in to confirm you.re not a bot)\b|"
    r"this content isn.t available, try again later",
    re.IGNORECASE,
)


class VPNRotationError(RuntimeError):
    """The server could not obtain a new download route."""


def is_rate_limited(stderr):
    return bool(_RATE_LIMIT.search(stderr or ""))


def vpn_proxy():
    """Optional server-side proxy for yt-dlp, usually a stable VPN proxy URL."""
    return os.environ.get("LIBRARY_RESTORE_VPN_PROXY", "").strip() or None


def rotate_vpn(cancel_event):
    """Wait for the configured VPN route to rotate before another download."""
    if cancel_event.is_set():
        return
    hook = os.environ.get("LIBRARY_RESTORE_VPN_ROTATE", "").strip()
    if hook:
        _run_rotation_hook(Path(hook))
        return
    control_url = os.environ.get("LIBRARY_RESTORE_GLUETUN_URL", "").strip()
    if control_url:
        if not vpn_proxy():
            raise VPNRotationError("Set LIBRARY_RESTORE_VPN_PROXY to route restore downloads through Gluetun.")
        _rotate_gluetun(control_url, cancel_event)
        return
    raise VPNRotationError("Configure LIBRARY_RESTORE_GLUETUN_URL or LIBRARY_RESTORE_VPN_ROTATE on the server.")


def _run_rotation_hook(executable):
    if not executable.is_absolute():
        raise VPNRotationError("Set LIBRARY_RESTORE_VPN_ROTATE to the absolute path of the server's VPN rotation executable.")
    try:
        # Let the hook finish changing the route even if the restore is cancelled
        # mid-switch. The caller checks cancellation before launching yt-dlp again.
        subprocess.run([str(executable)], check=True, timeout=VPN_ROTATION_TIMEOUT,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise VPNRotationError("The VPN rotation timed out.") from None
    except subprocess.CalledProcessError as exc:
        raise VPNRotationError(f"The VPN rotation exited with status {exc.returncode}.") from None
    except OSError:
        raise VPNRotationError("The server could not run the configured VPN rotation executable.") from None


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _rotate_gluetun(control_url, cancel_event):
    # Keep credentials on the configured origin and bypass the download proxy.
    try:
        origin = urlsplit(control_url)
        port = origin.port
    except ValueError:
        raise VPNRotationError("The Gluetun control URL is invalid.") from None
    if (origin.scheme not in ("http", "https") or not origin.hostname or port == 0
            or origin.username is not None or origin.query or origin.fragment or origin.path not in ("", "/")):
        raise VPNRotationError("Set LIBRARY_RESTORE_GLUETUN_URL to the Gluetun control server's HTTP or HTTPS origin.")
    loopback = origin.hostname in ("localhost", "127.0.0.1", "::1")
    api_key = os.environ.get("LIBRARY_RESTORE_GLUETUN_API_KEY", "").strip()
    if not loopback and (origin.scheme != "https" or not api_key):
        raise VPNRotationError("Use HTTPS and an API key for a Gluetun control server outside localhost.")

    opener = build_opener(ProxyHandler({}), _NoRedirects())
    headers = {"X-API-Key": api_key} if api_key else {}
    base_url = control_url.rstrip("/")

    def request(path, status=None, timeout=GLUETUN_REQUEST_TIMEOUT):
        if status is None:
            req = Request(base_url + path, headers=headers)
        else:
            payload = json.dumps({"status": status}).encode()
            req = Request(base_url + path, data=payload,
                          headers={**headers, "Content-Type": "application/json"}, method="PUT")
        try:
            with opener.open(req, timeout=timeout) as response:
                if status is None:
                    public_ip = json.loads(response.read(4096))["public_ip"]
                    if isinstance(public_ip, str):
                        address = ipaddress.ip_address(public_ip)
                        if address.is_global and not address.is_multicast:
                            return address
                    raise ValueError("Invalid public IP")
        except HTTPError as exc:
            exc.close()
            raise VPNRotationError(f"The Gluetun control server returned HTTP {exc.code}.") from None
        except (URLError, OSError, ValueError, KeyError, TypeError):
            raise VPNRotationError("The Gluetun control server did not return a valid response.") from None

    deadline = time.monotonic() + VPN_ROTATION_TIMEOUT
    public_ip_path = "/v1/publicip/ip"
    status_path = "/v1/vpn/status"
    old_ip = request(public_ip_path)
    if cancel_event.is_set():
        return

    # Restore the tunnel even if the stop response is lost or the job is cancelled.
    try:
        request(status_path, status="stopped")
    finally:
        request(status_path, status="running")

    while (remaining := deadline - time.monotonic()) > 0:
        try:
            if request(public_ip_path, timeout=min(remaining, GLUETUN_REQUEST_TIMEOUT)) != old_ip:
                return
        except VPNRotationError:
            pass  # Gluetun may have no public IP to report while reconnecting.
        time.sleep(max(0, min(GLUETUN_POLL_INTERVAL, deadline - time.monotonic())))
    raise VPNRotationError("Gluetun did not report a different public IP after reconnecting.")
