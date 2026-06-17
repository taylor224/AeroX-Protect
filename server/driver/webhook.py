"""Webhook delivery (PLAN P5 §6.5, §7.5): HMAC-SHA256 signature (ts.body), SSRF guard
(scheme + private/loopback/metadata IP block), no redirects, timeout. Uses requests."""
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
import uuid
from urllib.parse import urlparse

import requests

import config

logger = logging.getLogger(__name__)


def ssrf_check(url: str) -> tuple[bool, str]:
    p = urlparse(url)
    if p.scheme not in ('http', 'https'):
        return False, 'bad_scheme'
    host = p.hostname
    if not host:
        return False, 'no_host'
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == 'https' else 80))
    except OSError:
        return False, 'dns_fail'                  # unresolvable → fail closed
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # ALWAYS blocked, regardless of WEBHOOK_ALLOW_PRIVATE: cloud-metadata
        # (link-local 169.254/16, fd00 ULA handled by is_private below), loopback,
        # reserved, multicast, unspecified. These are never a legitimate webhook target.
        if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False, 'blocked_ip'
        # RFC1918 LAN (10/8, 192.168, 172.16) — legitimate for on-prem automation,
        # but opt-in so a misconfigured deploy can't be pivoted into the internal network.
        if ip.is_private and not config.WEBHOOK_ALLOW_PRIVATE:
            return False, 'private_ip'
    return True, ''


def sign(secret: str, ts: str, body: bytes) -> str:
    return hmac.new(secret.encode(), (ts + '.').encode() + body, hashlib.sha256).hexdigest()


def deliver(endpoint, payload: dict) -> dict:
    ok, reason = ssrf_check(endpoint.url)
    if not ok:
        endpoint.record_result(None, False)
        return {'status': 'failed', 'error': 'ssrf_blocked:%s' % reason}

    body = json.dumps(payload, separators=(',', ':')).encode()
    ts = str(int(time.time()))
    secret = endpoint.get_secret()
    headers = {
        'Content-Type': 'application/json', 'User-Agent': 'AeroXProtect/axp',
        'X-Axp-Event': str(payload.get('type', 'event')), 'X-Axp-Delivery': uuid.uuid4().hex,
        'X-Axp-Timestamp': ts, **(endpoint.headers or {}),
    }
    if secret:
        headers['X-Axp-Signature'] = 'sha256=' + sign(secret, ts, body)

    t0 = time.monotonic()
    try:
        resp = requests.post(endpoint.url, data=body, headers=headers,
                             timeout=(endpoint.timeout_ms or 5000) / 1000,
                             verify=bool(endpoint.verify_tls), allow_redirects=False)
        ok2 = resp.status_code < 300
        endpoint.record_result(resp.status_code, ok2)
        return {'status': 'success' if ok2 else 'failed', 'http_status': resp.status_code,
                'latency_ms': int((time.monotonic() - t0) * 1000), 'signature_sent': bool(secret)}
    except requests.RequestException as exc:
        endpoint.record_result(None, False)
        return {'status': 'failed', 'error': str(exc)[:200], 'latency_ms': int((time.monotonic() - t0) * 1000)}


def deliver_inline(cfg: dict, payload: dict) -> dict:
    """Send a webhook configured inline on an automation action (no pre-registered endpoint).

    cfg = {
      url, method (GET|POST|PUT), body_type (json|form|urlencoded|query|none),
      headers: {..}, auth: {type: none|basic|bearer|header, username, password, token,
                            header_name, header_value},
      body: dict|str   # merged with the event payload for templated sends
      verify_tls: bool, timeout_ms: int
    }
    SSRF-guarded, no redirects. The action payload is exposed as the body for json/form types
    (or appended to the query string for GET/query).
    """
    url = (cfg.get('url') or '').strip()
    if not url:
        return {'status': 'failed', 'error': 'no_url'}
    ok, reason = ssrf_check(url)
    if not ok:
        return {'status': 'failed', 'error': 'ssrf_blocked:%s' % reason}

    method = (cfg.get('method') or 'POST').upper()
    if method not in ('GET', 'POST', 'PUT'):
        return {'status': 'failed', 'error': 'bad_method'}
    body_type = cfg.get('body_type') or ('query' if method == 'GET' else 'json')
    # explicit body wins; otherwise send the event payload
    body = cfg.get('body')
    data_obj = body if isinstance(body, dict) else (payload if body is None else None)

    headers = dict(cfg.get('headers') or {})
    headers.setdefault('User-Agent', 'AeroXProtect/axp')
    auth = _build_auth(cfg.get('auth') or {}, headers)

    kwargs: dict = {'timeout': (cfg.get('timeout_ms') or 5000) / 1000,
                    'verify': bool(cfg.get('verify_tls', True)), 'allow_redirects': False,
                    'headers': headers}
    if auth:
        kwargs['auth'] = auth
    if body_type == 'query' or method == 'GET':
        kwargs['params'] = data_obj if isinstance(data_obj, dict) else {}
    elif body_type == 'json':
        kwargs['json'] = data_obj
    elif body_type == 'form' or body_type == 'urlencoded':
        kwargs['data'] = data_obj if isinstance(data_obj, dict) else {}
    elif body_type == 'none':
        pass
    else:
        return {'status': 'failed', 'error': 'bad_body_type'}

    t0 = time.monotonic()
    try:
        resp = requests.request(method, url, **kwargs)
        ok2 = resp.status_code < 300
        return {'status': 'success' if ok2 else 'failed', 'http_status': resp.status_code,
                'latency_ms': int((time.monotonic() - t0) * 1000)}
    except requests.RequestException as exc:
        return {'status': 'failed', 'error': str(exc)[:200], 'latency_ms': int((time.monotonic() - t0) * 1000)}


def _build_auth(auth: dict, headers: dict):
    """Apply the chosen auth scheme; returns a requests auth tuple for basic, else mutates
    headers (bearer / custom header) and returns None."""
    atype = (auth.get('type') or 'none').lower()
    if atype == 'basic':
        return (auth.get('username') or '', auth.get('password') or '')
    if atype == 'bearer' and auth.get('token'):
        headers['Authorization'] = 'Bearer %s' % auth['token']
    elif atype == 'header' and auth.get('header_name'):
        headers[auth['header_name']] = auth.get('header_value') or ''
    return None


def is_retryable(result: dict) -> bool:
    """5xx / network / timeout → retry; 4xx → permanent (no retry)."""
    if result.get('status') == 'success':
        return False
    code = result.get('http_status')
    if code is None:
        return True                        # network/timeout
    return code >= 500
