"""Hikvision ISAPI alertStream event source (PLAN §6.2).

GET /ISAPI/Event/notification/alertStream → multipart/x-mixed-replace stream of
<EventNotificationAlert> XML parts. The XML parser is a module-level pure function
(fixture-testable). ElementTree does not resolve external entities (XXE-safe, §13).
"""
import xml.etree.ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth

from server.driver.event_base import EventSource


def _localname(tag: str) -> str:
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _text(root, name):
    for el in root.iter():
        if _localname(el.tag) == name and el.text:
            return el.text.strip()
    return None


def parse_alert_xml(xml_text: str) -> dict | None:
    """<EventNotificationAlert> → {eventType, eventState, channelID, dateTime, region_points}."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    if _localname(root.tag) != 'EventNotificationAlert':
        return None
    points = []
    for el in root.iter():
        if _localname(el.tag) == 'RegionCoordinates':
            x = _text(el, 'positionX')
            y = _text(el, 'positionY')
            if x is not None and y is not None:
                try:
                    points.append([int(x), int(y)])
                except ValueError:
                    pass
    return {
        'eventType': _text(root, 'eventType'),
        'eventState': _text(root, 'eventState'),
        'channelID': _text(root, 'channelID') or _text(root, 'dynChannelID'),
        'dateTime': _text(root, 'dateTime'),
        'activePostCount': _text(root, 'activePostCount'),
        'region_points': points or None,
    }


def split_multipart(buffer: bytes, boundary: bytes) -> tuple[list[bytes], bytes]:
    """Split a multipart buffer on the boundary; return (complete parts, remainder)."""
    parts = buffer.split(b'--' + boundary)
    remainder = parts.pop() if parts else b''
    return [p for p in parts if p.strip()], remainder


def extract_xml(part: bytes) -> str | None:
    """Pull the XML body out of one multipart part (header\\r\\n\\r\\nbody)."""
    idx = part.find(b'\r\n\r\n')
    body = part[idx + 4:] if idx >= 0 else part
    body = body.strip()
    start = body.find(b'<EventNotificationAlert')
    return body[start:].decode('utf-8', 'ignore') if start >= 0 else None


class IsapiEventSource(EventSource):
    def __init__(self, host, http_port=80, onvif_port=80, username=None, password=None,
                 use_https=False, channel=1):
        self.host = host
        self.http_port = http_port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.channel = channel
        self._resp = None
        self._iter = None
        self._buffer = b''
        self._boundary = b'boundary'
        self._healthy = False

    def _url(self):
        scheme = 'https' if self.use_https else 'http'
        return '%s://%s:%s/ISAPI/Event/notification/alertStream' % (scheme, self.host, self.http_port)

    def open(self) -> None:
        self._resp = requests.get(
            self._url(), auth=HTTPDigestAuth(self.username or '', self.password or ''),
            stream=True, timeout=(6, 65), verify=False)
        if self._resp.status_code != 200:
            raise ConnectionError('alertStream http %s' % self._resp.status_code)
        ctype = self._resp.headers.get('Content-Type', '')
        if 'boundary=' in ctype:
            self._boundary = ctype.split('boundary=', 1)[1].strip().strip('"').encode()
        self._iter = self._resp.iter_content(4096)
        self._healthy = True

    def poll(self, timeout_s: float) -> list[dict]:
        events = []
        try:
            chunk = next(self._iter, b'')
        except (requests.RequestException, StopIteration):
            self._healthy = False
            return events
        if not chunk:
            return events
        self._buffer += chunk
        parts, self._buffer = split_multipart(self._buffer, self._boundary)
        for part in parts:
            xml_text = extract_xml(part)
            if not xml_text:
                continue
            alert = parse_alert_xml(xml_text)
            if alert and alert.get('eventType'):
                events.append(alert)
        return events

    def close(self) -> None:
        if self._resp is not None:
            try:
                self._resp.close()
            except Exception:
                pass
        self._healthy = False

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def source_name(self) -> str:
        return 'isapi'
