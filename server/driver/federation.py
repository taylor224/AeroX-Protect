"""Federation client (PLAN P8). Talks to a member AeroXProtect's P5 external API
(`/api/v1/ext/*`) with the member's opaque api_token. SSRF-guarded (same policy as the P5
webhook driver — block private/loopback unless explicitly allowed for local e2e). All
methods raise FederationError on transport/HTTP failure so the sync service can mark the
member offline.
"""
import logging

import requests

import config

logger = logging.getLogger(__name__)

TIMEOUT = 8


class FederationError(Exception):
    pass


class FederationClient:
    def __init__(self, base_url: str, token: str | None):
        self.base_url = (base_url or '').rstrip('/')
        self.token = token

    def _headers(self) -> dict:
        return {'Authorization': 'Bearer %s' % (self.token or ''), 'Accept': 'application/json'}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = self.base_url + path
        _guard_url(url)
        try:
            # allow_redirects=False so a member can't 302 the hub to an internal target
            # after the URL passed the SSRF check
            resp = requests.get(url, headers=self._headers(), params=params or {},
                                timeout=TIMEOUT, allow_redirects=False)
        except requests.exceptions.RequestException as e:
            raise FederationError('unreachable: %s' % e)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            raise FederationError('redirect refused')
        if resp.status_code in (401, 403):
            raise FederationError('unauthorized (check api token + scopes)')
        if resp.status_code != 200:
            raise FederationError('http %s' % resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            raise FederationError('bad json')
        return body.get('data', body) if isinstance(body, dict) else {}

    def state(self) -> dict:
        """Member /ext/state → {cameras:[{uuid,name,online,status}], ...}."""
        return self._get('/api/v1/ext/state')

    def list_cameras(self) -> list[dict]:
        data = self._get('/api/v1/ext/cameras')
        return data.get('cameras', []) if isinstance(data, dict) else []

    def list_events(self, params: dict | None = None) -> list[dict]:
        data = self._get('/api/v1/ext/events', params=params)
        return data.get('items', []) if isinstance(data, dict) else []


def _guard_url(url: str):
    """Block SSRF using the same hardened policy as the webhook driver: metadata/
    loopback/reserved are ALWAYS blocked and an unresolvable host fails closed; RFC1918
    LAN is gated by WEBHOOK_ALLOW_PRIVATE (set for local federation e2e)."""
    from server.driver.webhook import ssrf_check
    ok, reason = ssrf_check(url)
    if not ok:
        raise FederationError('blocked host: %s' % reason)
