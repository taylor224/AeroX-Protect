"""SMTP email driver (PLAN P5 §6.6). Loads the profile from an action_target(type=email) or
falls back to config SMTP_*. Sends an event summary (KST). STARTTLS. Mock-friendly (tests
monkeypatch smtplib.SMTP)."""
import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from server.model import KST

logger = logging.getLogger(__name__)


def _smtp_from(target) -> dict:
    if target is not None:
        cfg = target.config or {}
        user, password = target.get_credentials()
        return {'host': target.host or cfg.get('smtp_host'), 'port': target.port or cfg.get('smtp_port', 587),
                'from': cfg.get('from') or config.SMTP_FROM, 'user': user, 'password': password,
                'use_tls': cfg.get('use_tls', True)}
    return {'host': config.SMTP_HOST, 'port': config.SMTP_PORT, 'from': config.SMTP_FROM,
            'user': config.SMTP_USER, 'password': config.SMTP_PASSWORD, 'use_tls': config.SMTP_USE_TLS}


def _summary(payload: dict) -> tuple[str, str]:
    import datetime
    cam = payload.get('camera_id')
    ts = payload.get('ts')
    when = datetime.datetime.fromtimestamp(ts / 1000, KST).strftime('%Y-%m-%d %H:%M:%S KST') if ts else '-'
    label = payload.get('subtype') or payload.get('type') or 'event'
    subject = '[AeroX Protect] %s 감지' % label
    body = '카메라 %s · %s · %s\n' % (cam or '-', label, when)
    if payload.get('event_id'):
        body += '\n이벤트: /events/%s\n' % payload['event_id']
    return subject, body


def send_event(target, payload: dict) -> dict:
    cfg = target.config or {}
    to = cfg.get('to') or cfg.get('recipients')
    if isinstance(to, list):
        to = ','.join(to)
    return send_event_to(to, payload, target=target)


def send_event_to(recipient: str | None, payload: dict, target=None) -> dict:
    if not recipient:
        return {'status': 'skipped', 'error': 'no_recipient'}
    profile = _smtp_from(target)
    if not profile['host']:
        return {'status': 'skipped', 'error': 'smtp_not_configured'}
    subject, body = _summary(payload)
    msg = MIMEMultipart()
    msg['From'] = profile['from']
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    t0 = time.monotonic()
    try:
        server = smtplib.SMTP(profile['host'], int(profile['port']), timeout=10)
        try:
            if profile['use_tls']:
                server.starttls()
            if profile['user']:
                server.login(profile['user'], profile['password'] or '')
            server.sendmail(profile['from'], recipient.split(','), msg.as_string())
        finally:
            server.quit()
        return {'status': 'success', 'latency_ms': int((time.monotonic() - t0) * 1000)}
    except Exception as exc:                       # noqa: BLE001
        logger.warning('email send failed: %s', exc)
        return {'status': 'failed', 'error': str(exc)[:200]}
