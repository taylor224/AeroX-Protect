from server.driver.isapi_event import extract_xml, parse_alert_xml, split_multipart
from server.service import event_normalizer as N

ISAPI_ALERT = """<?xml version="1.0" encoding="UTF-8"?>
<EventNotificationAlert xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <channelID>1</channelID>
  <dateTime>2026-06-05T14:30:00+09:00</dateTime>
  <eventType>linedetection</eventType>
  <eventState>active</eventState>
  <DetectionRegionList><DetectionRegionEntry><RegionCoordinatesList>
    <RegionCoordinates><positionX>100</positionX><positionY>200</positionY></RegionCoordinates>
    <RegionCoordinates><positionX>900</positionX><positionY>800</positionY></RegionCoordinates>
  </RegionCoordinatesList></DetectionRegionEntry></DetectionRegionList>
</EventNotificationAlert>"""


# ── normalizers ───────────────────────────────────────────────────────────────
def test_isapi_motion_start():
    n = N.normalize_isapi({'eventType': 'VMD', 'eventState': 'active', 'channelID': '1',
                           'dateTime': '2026-06-05T14:30:00+09:00'})
    assert n.type == 'motion' and n.state == 'start' and n.channel == 1


def test_isapi_line_end():
    n = N.normalize_isapi({'eventType': 'linedetection', 'eventState': 'inactive'})
    assert n.type == 'line_crossing' and n.state == 'end'


def test_isapi_unknown_kept():
    assert N.normalize_isapi({'eventType': 'weirdthing', 'eventState': 'active'}).type == 'unknown'


def test_onvif_motion_start():
    n = N.normalize_onvif({'topic': 'tns1:RuleEngine/CellMotionDetector/Motion',
                           'data': {'IsMotion': 'true'}, 'utc_time': '2026-06-05T05:30:00Z'})
    assert n.type == 'motion' and n.state == 'start' and n.ts is not None


def test_onvif_tamper_end():
    n = N.normalize_onvif({'topic': 'tns1:RuleEngine/TamperDetector/Tamper', 'data': {'State': 'false'}})
    assert n.type == 'tamper' and n.state == 'end'


def test_sunapi_intrusion():
    n = N.normalize_sunapi({'event': 'Intrusion', 'state': 'true', 'channel': 0})
    assert n.type == 'intrusion' and n.state == 'start'


def test_manual_passthrough_and_invalid():
    assert N.normalize_manual({'type': 'motion', 'score': 80}).score == 80
    assert N.normalize_manual({'type': 'bogus'}) is None


def test_region_normalizer():
    assert N.region_normalizer('hikvision', [[500, 500], [1000, 1000]]) == [[0.5, 0.5], [1.0, 1.0]]
    assert N.region_normalizer('onvif', [[960, 540]], frame_w=1920, frame_h=1080) == [[0.5, 0.5]]


# ── ISAPI alertStream parser ──────────────────────────────────────────────────
def test_parse_alert_xml():
    a = parse_alert_xml(ISAPI_ALERT)
    assert a['eventType'] == 'linedetection' and a['eventState'] == 'active'
    assert a['channelID'] == '1'
    assert a['region_points'] == [[100, 200], [900, 800]]


def test_normalize_isapi_with_region():
    a = parse_alert_xml(ISAPI_ALERT)
    n = N.normalize_isapi(a)
    assert n.type == 'line_crossing'
    assert n.region['shapes'][0]['pts'] == [[0.1, 0.2], [0.9, 0.8]]   # 0–1000 → 0–1


def test_multipart_split_and_extract():
    body = ('--myboundary\r\nContent-Type: application/xml\r\n\r\n' + ISAPI_ALERT +
            '\r\n--myboundary\r\nContent-Type: application/xml\r\n\r\n').encode()
    parts, _ = split_multipart(body, b'myboundary')
    assert parts
    assert extract_xml(parts[0]).startswith('<EventNotificationAlert')
