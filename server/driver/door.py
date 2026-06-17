"""Door controller driver (PLAN P10). Drives the physical lock relay on unlock/lock.
`mock` is a no-op (for testing / unconfigured doors), `vendor_http` toggles a camera/NVR
relay output via CGI (Hikvision ISAPI / Hanwha SUNAPI / generic), `onvif_relay` is a
deferred stub. Returns a structured result; never raises (callers log the failure).
"""
import logging

logger = logging.getLogger(__name__)


def unlock(door, seconds: int) -> dict:
    return _drive(door, 'unlock', seconds)


def lock(door) -> dict:
    return _drive(door, 'lock', 0)


def _drive(door, action: str, seconds: int) -> dict:
    ctype = door.controller_type
    if ctype == 'mock':
        return {'status': 'ok', 'controller': 'mock', 'action': action}
    if ctype == 'vendor_http':
        return _vendor_http(door, action, seconds)
    if ctype == 'onvif_relay':
        return {'status': 'skipped', 'controller': 'onvif_relay', 'error': 'onvif_relay_deferred'}
    return {'status': 'failed', 'error': 'unknown_controller: %s' % ctype}


def _vendor_http(door, action: str, seconds: int) -> dict:
    import requests
    from requests.auth import HTTPDigestAuth
    cfg = door.controller_config or {}
    host = cfg.get('host')
    if not host:
        return {'status': 'failed', 'error': 'no_host'}
    url = cfg.get('url') or ('http://%s/cgi-bin/accessControl.cgi' % host)
    auth = HTTPDigestAuth(cfg.get('username', ''), cfg.get('password', '')) if cfg.get('username') else None
    params = {'output': cfg.get('output_id', 1), 'action': action, 'seconds': seconds}
    try:
        r = requests.get(url, params=params, auth=auth, timeout=6)
        ok = r.status_code == 200
        return {'status': 'ok' if ok else 'failed', 'controller': 'vendor_http',
                'http': r.status_code, 'action': action}
    except requests.RequestException as e:
        return {'status': 'failed', 'controller': 'vendor_http', 'error': str(e)[:200]}
