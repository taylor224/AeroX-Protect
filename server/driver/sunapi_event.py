"""Hanwha SUNAPI event source (PLAN §6.3). Polls eventstatus.cgi?action=check and
diffs against the previous bitmap to synthesize start/end. The diff is the testable
core; HTTP is structural for real hardware."""
import logging

import requests
from requests.auth import HTTPDigestAuth

from server.driver.event_base import EventSource

logger = logging.getLogger(__name__)


def parse_eventstatus(text: str) -> dict:
    """key=value SUNAPI eventstatus → {event_key: bool_active}."""
    state = {}
    for line in (text or '').splitlines():
        line = line.strip()
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        state[key.strip()] = value.strip().lower() in ('true', '1', 'on')
    return state


def diff_status(prev: dict, current: dict) -> list[dict]:
    """Synthesize start/end events from two eventstatus snapshots."""
    events = []
    for key, active in current.items():
        was = prev.get(key, False)
        if active and not was:
            events.append({'event': _event_name(key), 'state': 'true', 'channel': _channel(key)})
        elif not active and was:
            events.append({'event': _event_name(key), 'state': 'false', 'channel': _channel(key)})
    return events


def _event_name(key: str) -> str:
    # e.g. "Channel.0.MotionDetection" → "MotionDetection"
    return key.rsplit('.', 1)[-1]


def _channel(key: str):
    parts = key.split('.')
    for i, p in enumerate(parts):
        if p.lower() == 'channel' and i + 1 < len(parts) and parts[i + 1].isdigit():
            return int(parts[i + 1])
    return None


class SunapiEventSource(EventSource):
    def __init__(self, host, http_port=80, onvif_port=80, username=None, password=None,
                 use_https=False, channel=1):
        self.host = host
        self.http_port = http_port
        self.username = username
        self.password = password
        self.use_https = use_https
        self._prev = {}
        self._healthy = False

    def _url(self):
        scheme = 'https' if self.use_https else 'http'
        return '%s://%s:%s/stw-cgi/eventstatus.cgi?msubmenu=eventstatus&action=check' % (
            scheme, self.host, self.http_port)

    def open(self) -> None:
        self._prev = {}
        self._healthy = True

    def poll(self, timeout_s: float) -> list[dict]:
        try:
            resp = requests.get(self._url(), auth=HTTPDigestAuth(self.username or '', self.password or ''),
                                timeout=timeout_s, verify=False)
            if resp.status_code != 200:
                self._healthy = False
                return []
        except requests.RequestException as e:
            logger.debug('sunapi poll failed: %s', e)
            self._healthy = False
            return []
        current = parse_eventstatus(resp.text)
        events = diff_status(self._prev, current)
        self._prev = current
        self._healthy = True
        return events

    def close(self) -> None:
        self._healthy = False

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def source_name(self) -> str:
        return 'sunapi'
