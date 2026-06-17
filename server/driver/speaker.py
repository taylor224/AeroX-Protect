"""IP/SIP speaker driver (PLAN P5 §6.3). vendor_http (Axis/2N/generic CGI) is the primary
path (requests + Digest auth); onvif_backchannel and sip are structured stubs (need hardware
+ heavier deps, deferred). params: {clip_id?, tts_text?}."""
import logging
import time

import requests
from requests.auth import HTTPDigestAuth

logger = logging.getLogger(__name__)


def run(target, params: dict) -> dict:
    proto = target.protocol
    if proto == 'vendor_http':
        return _vendor_http(target, params)
    if proto == 'onvif_backchannel':
        return {'status': 'skipped', 'error': 'onvif_backchannel_deferred', 'protocol': proto}
    if proto == 'sip':
        return {'status': 'skipped', 'error': 'sip_deferred', 'protocol': proto}
    return {'status': 'failed', 'error': 'unknown_protocol', 'protocol': proto}


def _vendor_http(target, params: dict) -> dict:
    cfg = target.config or {}
    clip_id = params.get('clip_id')
    url = cfg.get('play_url') or 'http://%s/axis-cgi/playclip.cgi' % (target.host or '')
    user, password = target.get_credentials()
    auth = HTTPDigestAuth(user, password) if user else None
    query = {'clip': clip_id} if clip_id is not None else {}
    if params.get('tts_text') and cfg.get('tts_param'):
        query[cfg['tts_param']] = params['tts_text']
    t0 = time.monotonic()
    try:
        resp = requests.get(url, params=query, auth=auth, timeout=8)
        ok = resp.status_code < 300
        return {'status': 'success' if ok else 'failed', 'http_status': resp.status_code,
                'latency_ms': int((time.monotonic() - t0) * 1000), 'protocol': 'vendor_http'}
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
