"""Edge-recording driver (PLAN P6 R6): search + download a camera's on-board SD clips so
the NVR can gap-fill from edge storage after a network/NVR outage.

ISAPI (Hikvision) is implemented via `ContentMgmt/search` + `ContentMgmt/download`. Other
vendors raise `edge_unsupported_vendor` for now (SUNAPI SD / ONVIF Replay-Search are the
documented follow-ups). All network I/O flows through the vendor driver's authenticated
(Digest) HTTP, so auth/reachability failures surface as DriverError to the import service.
"""
import logging
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

from server.driver.base import DriverError
from server.driver.isapi import IsapiDriver

logger = logging.getLogger(__name__)

ISAPI_MAX_RESULTS = 400


@dataclass
class EdgeClip:
    start_ts: datetime          # naive UTC
    end_ts: datetime            # naive UTC
    uri: str                    # vendor playback URI (opaque to us)
    size_bytes: int = 0

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start_ts < end and self.end_ts > start


# ── public dispatch ──────────────────────────────────────────────────────────
def search_clips(camera, start: datetime, end: datetime) -> list[EdgeClip]:
    """Return the camera's SD clips overlapping [start, end] (naive UTC), ordered by start."""
    if camera.driver == 'isapi':
        clips = _search_isapi(camera, start, end)
        return sorted(clips, key=lambda c: c.start_ts)
    raise DriverError('edge_unsupported_vendor: %s' % camera.driver)


def download_clip(camera, clip: EdgeClip, dest_abs: str) -> int:
    """Download one clip to dest_abs. Returns bytes written."""
    if camera.driver == 'isapi':
        return _download_isapi(camera, clip, dest_abs)
    raise DriverError('edge_unsupported_vendor: %s' % camera.driver)


# ── ISAPI (Hikvision) ────────────────────────────────────────────────────────
def _isapi_driver(camera) -> IsapiDriver:
    username, password = camera.get_credentials()
    return IsapiDriver(camera.host, http_port=camera.http_port or 80, rtsp_port=camera.rtsp_port or 554,
                       onvif_port=camera.onvif_port or 80, username=username, password=password,
                       use_https=camera.use_https, channel=camera.channel)


def _iso_z(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_iso_z(text: str) -> datetime | None:
    if not text:
        return None
    try:                                        # 2026-06-08T00:00:00Z (drop offset/Z, keep naive UTC)
        return datetime.strptime(text.strip()[:19], '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None


def _search_isapi(camera, start: datetime, end: datetime) -> list[EdgeClip]:
    drv = _isapi_driver(camera)
    track_id = camera.channel * 100 + 1
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<CMSearchDescription>'
        '<searchID>%s</searchID>'
        '<trackList><trackID>%d</trackID></trackList>'
        '<timeSpanList><timeSpan><startTime>%s</startTime><endTime>%s</endTime></timeSpan></timeSpanList>'
        '<maxResults>%d</maxResults>'
        '<searchResultPostion>0</searchResultPostion>'
        '<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor></metadataList>'
        '</CMSearchDescription>'
    ) % (uuid.uuid4().hex, track_id, _iso_z(start), _iso_z(end), ISAPI_MAX_RESULTS)

    resp = drv._http_request('POST', '/ISAPI/ContentMgmt/search', data=body,
                             headers={'Content-Type': 'application/xml'})
    if resp.status_code != 200:
        raise DriverError('edge search http %s' % resp.status_code)
    return _parse_isapi_matches(resp.text)


def _parse_isapi_matches(xml_text: str) -> list[EdgeClip]:
    """Parse a CMSearchResult into EdgeClips (namespace-agnostic via local tag names)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise DriverError('edge search parse: %s' % e)

    def ln(tag: str) -> str:
        return tag.rsplit('}', 1)[-1]

    clips: list[EdgeClip] = []
    for item in root.iter():
        if ln(item.tag) != 'searchMatchItem':
            continue
        start_ts = end_ts = uri = None
        size = 0
        for el in item.iter():
            name, text = ln(el.tag), (el.text or '').strip()
            if name == 'startTime':
                start_ts = _parse_iso_z(text)
            elif name == 'endTime':
                end_ts = _parse_iso_z(text)
            elif name == 'playbackURI':
                uri = text
            elif name == 'size' and text.isdigit():
                size = int(text)
        if start_ts and end_ts and uri and end_ts > start_ts:
            clips.append(EdgeClip(start_ts=start_ts, end_ts=end_ts, uri=uri, size_bytes=size))
    return clips


def _download_isapi(camera, clip: EdgeClip, dest_abs: str) -> int:
    drv = _isapi_driver(camera)
    body = ('<?xml version="1.0" encoding="utf-8"?>'
            '<downloadRequest><playbackURI>%s</playbackURI></downloadRequest>') % clip.uri
    resp = drv._http_request('POST', '/ISAPI/ContentMgmt/download', data=body,
                             headers={'Content-Type': 'application/xml'})
    if resp.status_code != 200:
        raise DriverError('edge download http %s' % resp.status_code)
    data = resp.content or b''
    with open(dest_abs, 'wb') as fh:
        fh.write(data)
    return len(data)
