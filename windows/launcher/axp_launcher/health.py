"""Readiness probes for supervised services (stdlib only)."""
import json
import socket
import urllib.request


def tcp_open(port: int, host: str = '127.0.0.1', timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except Exception:
        return False


def healthz(port: int, timeout: float = 3.0) -> dict | None:
    """Backend /api/v1/healthz body ({'data': {'db':…, 'redis':…, 'version':…}})."""
    try:
        with urllib.request.urlopen(
                'http://127.0.0.1:%d/api/v1/healthz' % port, timeout=timeout) as r:
            body = json.loads(r.read().decode('utf-8'))
            return body.get('data') or body
    except Exception:
        return None
