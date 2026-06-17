"""Twilio SMS driver (PLAN P6 N1). Sends via the Twilio Messages REST API over HTTPS —
no SDK, just `requests` with HTTP basic auth (Account SID : Auth Token). Config resolves
from the admin UI (DB Setting) with TWILIO_* env fallback — see server.service.twilio_config.
Mock-friendly (tests monkeypatch requests.post). Skips cleanly when unconfigured so a
missing Twilio account never breaks the notification pipeline.
"""
import datetime
import logging

import requests

from server.model import KST
from server.service import twilio_config

logger = logging.getLogger(__name__)


def _summary(payload: dict) -> str:
    ts = payload.get('ts')
    when = datetime.datetime.fromtimestamp(ts / 1000, KST).strftime('%m-%d %H:%M') if ts else '-'
    label = payload.get('subtype') or payload.get('type') or 'event'
    cam = payload.get('camera_id')
    return '[AeroX Protect] %s · cam %s · %s KST' % (label, cam or '-', when)


def configured() -> bool:
    return twilio_config.configured()


def send_event_to(to: str, payload: dict) -> dict:
    if not to:
        return {'status': 'skipped', 'reason': 'no_recipient'}
    cfg = twilio_config.get_config()
    if not (cfg['account_sid'] and cfg['auth_token'] and cfg['from_number']):
        return {'status': 'skipped', 'reason': 'not_configured'}

    url = '%s/2010-04-01/Accounts/%s/Messages.json' % (cfg['api_base'], cfg['account_sid'])
    try:
        res = requests.post(
            url,
            auth=(cfg['account_sid'], cfg['auth_token']),
            data={'To': to, 'From': cfg['from_number'], 'Body': _summary(payload)[:1500]},
            timeout=10,
        )
    except requests.RequestException as e:
        logger.warning('twilio send failed: %s', e)
        return {'status': 'error', 'detail': str(e)[:200]}

    if res.status_code in (200, 201):
        sid = None
        try:
            sid = res.json().get('sid')
        except Exception:
            pass
        return {'status': 'success', 'sid': sid}
    logger.warning('twilio send rejected (%s): %s', res.status_code, res.text[:200])
    return {'status': 'error', 'code': res.status_code, 'detail': res.text[:200]}
