"""IO module / relay driver (PLAN P5 §6.4). vendor_http (Hikvision ISAPI / Hanwha SUNAPI /
generic CGI) via requests; onvif_relay is a structured stub (onvif-zeep wiring deferred).
params: {output_id, action: on|off|pulse, pulse_ms?}. Modbus is P6."""
import logging
import time

import requests
from requests.auth import HTTPDigestAuth

logger = logging.getLogger(__name__)
MAX_INLINE_PULSE_MS = 2000


def run(target, params: dict) -> dict:
    proto = target.protocol
    if proto == 'vendor_http':
        return _vendor_http(target, params)
    if proto == 'onvif_relay':
        return {'status': 'skipped', 'error': 'onvif_relay_deferred', 'protocol': proto}
    return {'status': 'failed', 'error': 'unknown_protocol', 'protocol': proto}


def _vendor_http(target, params: dict) -> dict:
    cfg = target.config or {}
    action = params.get('action', 'on')
    output_id = params.get('output_id')
    pulse_ms = params.get('pulse_ms') or cfg.get('default_pulse_ms') or 1000
    url = cfg.get('control_url') or 'http://%s/io' % (target.host or '')
    user, password = target.get_credentials()
    auth = HTTPDigestAuth(user, password) if user else None

    def _send(state: str):
        return requests.get(url, params={'output': output_id, 'state': state}, auth=auth, timeout=6)

    t0 = time.monotonic()
    try:
        if action == 'pulse':
            r1 = _send('on')
            time.sleep(min(int(pulse_ms), MAX_INLINE_PULSE_MS) / 1000)
            _send('off')
            ok = r1.status_code < 300
            code = r1.status_code
        else:
            resp = _send(action)
            ok = resp.status_code < 300
            code = resp.status_code
        return {'status': 'success' if ok else 'failed', 'http_status': code,
                'latency_ms': int((time.monotonic() - t0) * 1000), 'protocol': 'vendor_http', 'action': action}
    except requests.RequestException as exc:
        return {'status': 'failed', 'error': str(exc)[:200], 'protocol': 'vendor_http'}


def healthcheck(target) -> dict:
    if target.protocol == 'vendor_http' and target.host:
        try:
            requests.get('http://%s/' % target.host, timeout=4)
            return {'status': 'online'}
        except requests.RequestException:
            return {'status': 'offline'}
    return {'status': 'unknown'}
