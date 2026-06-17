"""Vendor event payload → unified NormalizedEvent (PLAN §6.4, §6.5). Pure functions
(no I/O) so they're fixture-testable. Unmapped topics → type='unknown' (kept for
later remapping). Coordinates normalized to 0–1 via region_normalizer."""
from dataclasses import dataclass
from datetime import datetime, timezone

from server.model.event import (
    TYPE_ACCESS,
    TYPE_AUDIO,
    TYPE_AUDIO_CLASS,
    TYPE_COUNT,
    TYPE_DOORBELL,
    TYPE_FACE,
    TYPE_LPR,
    TYPE_SMOKE,
    TYPE_INTRUSION,
    TYPE_IO,
    TYPE_LINE_CROSSING,
    TYPE_LOITERING,
    TYPE_MOTION,
    TYPE_OBJECT,
    TYPE_OCCUPANCY,
    TYPE_REGION_ENTER,
    TYPE_REGION_EXIT,
    TYPE_TAMPER,
    TYPE_UNKNOWN,
    TYPE_VIDEO_LOSS,
)

VALID_TYPES = {
    TYPE_MOTION, TYPE_LINE_CROSSING, TYPE_INTRUSION, TYPE_REGION_ENTER, TYPE_REGION_EXIT,
    TYPE_TAMPER, TYPE_AUDIO, TYPE_IO, TYPE_VIDEO_LOSS, TYPE_OBJECT,
    TYPE_LOITERING, TYPE_COUNT, TYPE_OCCUPANCY, TYPE_DOORBELL, TYPE_AUDIO_CLASS, TYPE_SMOKE,
    TYPE_LPR, TYPE_FACE, TYPE_ACCESS, TYPE_UNKNOWN,
}

# Hikvision eventType (lowercased) → normalized type
ISAPI_MAP = {
    'vmd': TYPE_MOTION, 'motiondetection': TYPE_MOTION,
    'linedetection': TYPE_LINE_CROSSING,
    'fielddetection': TYPE_INTRUSION,
    'regionentrance': TYPE_REGION_ENTER, 'regionexiting': TYPE_REGION_EXIT,
    'tamperdetection': TYPE_TAMPER, 'shelteralarm': TYPE_TAMPER,
    'scenechangedetection': TYPE_TAMPER, 'defocus': TYPE_TAMPER,
    'audioexception': TYPE_AUDIO,
    'io': TYPE_IO, 'inputport': TYPE_IO,
    'videoloss': TYPE_VIDEO_LOSS, 'videomismatch': TYPE_VIDEO_LOSS,
    'facedetection': TYPE_OBJECT,
}

# ONVIF topic substring (lowercased) → normalized type
ONVIF_PATTERNS = [
    ('cellmotiondetector', TYPE_MOTION), ('motionalarm', TYPE_MOTION), ('motiondetect', TYPE_MOTION),
    ('linedetector', TYPE_LINE_CROSSING),
    ('fielddetector', TYPE_INTRUSION), ('intrusiondetector', TYPE_INTRUSION),
    ('tamperdetector', TYPE_TAMPER), ('imagetooblurry', TYPE_TAMPER),
    ('audioanalytics', TYPE_AUDIO), ('audiotooloud', TYPE_AUDIO),
    ('digitalinput', TYPE_IO), ('device/io', TYPE_IO),
    ('signalloss', TYPE_VIDEO_LOSS), ('globalscenechange', TYPE_VIDEO_LOSS),
]

# Hanwha SUNAPI event key (lowercased) → normalized type
SUNAPI_MAP = {
    'motiondetection': TYPE_MOTION,
    'tampering': TYPE_TAMPER, 'defocusdetection': TYPE_TAMPER,
    'audiodetection': TYPE_AUDIO,
    'passline': TYPE_LINE_CROSSING, 'linecrossing': TYPE_LINE_CROSSING,
    'intrusion': TYPE_INTRUSION, 'intrudedobject': TYPE_INTRUSION,
    'enter': TYPE_REGION_ENTER, 'appear': TYPE_REGION_ENTER,
    'exit': TYPE_REGION_EXIT, 'disappear': TYPE_REGION_EXIT,
    'videoloss': TYPE_VIDEO_LOSS, 'alarminput': TYPE_IO,
}


@dataclass
class NormalizedEvent:
    type: str
    state: str                 # 'start' / 'end' / 'pulse'
    subtype: str | None = None
    ts: int | None = None      # epoch ms (camera clock) or None
    score: int | None = None
    channel: int | None = None
    region: dict | None = None
    vendor_event_id: str | None = None
    snapshot_path: str | None = None
    dedup_extra: str | None = None    # extra dedup discriminator (e.g. plate/identity/door)


def _parse_iso_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        v = value.strip().replace('Z', '+00:00')
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def region_normalizer(vendor: str, points: list, frame_w: int | None = None,
                      frame_h: int | None = None) -> list[list[float]]:
    """Vendor coordinates → 0–1 normalized [[x,y],...] (resolution-independent overlay)."""
    out = []
    for p in points or []:
        try:
            x, y = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        v = (vendor or '').lower()
        if v == 'hikvision':           # 0–1000
            x, y = x / 1000.0, y / 1000.0
        elif frame_w and frame_h:      # raw pixels
            x, y = x / frame_w, y / frame_h
        elif x > 1 or y > 1:           # heuristic: looks like pixels w/o frame
            x, y = min(1.0, x / 1920.0), min(1.0, y / 1080.0)
        out.append([round(max(0.0, min(1.0, x)), 4), round(max(0.0, min(1.0, y)), 4)])
    return out


# ── per-vendor normalizers ────────────────────────────────────────────────────
def normalize_isapi(alert: dict) -> NormalizedEvent | None:
    etype = (alert.get('eventType') or '').lower()
    if not etype:
        return None
    ntype = ISAPI_MAP.get(etype, TYPE_UNKNOWN)
    estate = (alert.get('eventState') or '').lower()
    state = 'start' if estate == 'active' else ('end' if estate == 'inactive' else 'pulse')
    channel = _safe_int(alert.get('channelID') or alert.get('dynChannelID'))
    region = None
    coords = alert.get('region_points')
    if coords:
        region = {'shapes': [{'kind': 'poly', 'pts': region_normalizer('hikvision', coords)}]}
    return NormalizedEvent(type=ntype, state=state, subtype=etype, ts=_parse_iso_ms(alert.get('dateTime')),
                           channel=channel, region=region, vendor_event_id=alert.get('vendor_event_id'))


def normalize_onvif(message: dict) -> NormalizedEvent | None:
    topic = (message.get('topic') or '').lower()
    if not topic:
        return None
    ntype = TYPE_UNKNOWN
    for pattern, mapped in ONVIF_PATTERNS:
        if pattern in topic:
            ntype = mapped
            break
    # State from SimpleItem (IsMotion / State) + PropertyOperation
    items = message.get('data') or {}
    raw_state = str(items.get('State', items.get('IsMotion', ''))).lower()
    op = (message.get('property_operation') or '').lower()
    if raw_state in ('true', '1', 'active'):
        state = 'start'
    elif raw_state in ('false', '0', 'inactive'):
        state = 'end'
    elif op == 'deleted':
        state = 'end'
    else:
        state = 'pulse'
    subtype = topic.rsplit('/', 1)[-1] if '/' in topic else None
    return NormalizedEvent(type=ntype, state=state, subtype=subtype, ts=_parse_iso_ms(message.get('utc_time')),
                           channel=_safe_int(message.get('channel')))


def normalize_sunapi(status: dict) -> NormalizedEvent | None:
    key = (status.get('event') or '').lower()
    if not key:
        return None
    ntype = SUNAPI_MAP.get(key, TYPE_UNKNOWN)
    raw_state = str(status.get('state', '')).lower()
    state = 'start' if raw_state in ('true', '1', 'on', 'active') else (
        'end' if raw_state in ('false', '0', 'off', 'inactive') else 'pulse')
    return NormalizedEvent(type=ntype, state=state, subtype=key, ts=_parse_iso_ms(status.get('ts')),
                           channel=_safe_int(status.get('channel')))


def normalize_manual(raw: dict) -> NormalizedEvent | None:
    """Simulated/injected events (source='manual') — already in unified shape."""
    ntype = raw.get('type')
    if ntype not in VALID_TYPES:
        return None
    return NormalizedEvent(
        type=ntype, state=raw.get('state', 'pulse'), subtype=raw.get('subtype'),
        ts=raw.get('ts'), score=_safe_int(raw.get('score')), channel=_safe_int(raw.get('channel')),
        region=raw.get('region'), vendor_event_id=raw.get('vendor_event_id'))


def normalize(camera, raw: dict, source: str) -> NormalizedEvent | None:
    """Dispatch by source. Heartbeat/empty payloads → None (ignored)."""
    if not raw:
        return None
    if source == 'isapi':
        return normalize_isapi(raw)
    if source == 'onvif':
        return normalize_onvif(raw)
    if source == 'sunapi':
        return normalize_sunapi(raw)
    if source == 'manual':
        return normalize_manual(raw)
    return None


def _safe_int(value):
    try:
        return int(value) if value not in (None, '') else None
    except (ValueError, TypeError):
        return None
