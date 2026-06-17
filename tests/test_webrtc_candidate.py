"""Settings-driven WebRTC LAN candidate (2026-06-15).

The server LAN IP is entered in Settings and the backend injects it as a host ICE candidate
into go2rtc's WebRTC answer, so low-latency WebRTC live works on the local network without a
go2rtc restart. go2rtc listens on 0.0.0.0:8555 but only advertises configured candidates; on
a LAN with no reachable STUN it advertises none, so ICE never connects without this.
"""
import json

from server.model.setting import Setting
from server.view.api import live as live_api
from tests.conftest import login


def test_inject_host_candidate_crlf():
    sdp = 'v=0\r\na=ice-ufrag:abcd\r\na=ice-pwd:secret\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
    out = live_api._inject_host_candidate(sdp, '192.168.1.10')
    lines = out.split('\r\n')
    i = lines.index('a=ice-pwd:secret')
    assert lines[i + 1] == 'a=candidate:1 1 UDP 2130706431 192.168.1.10 8555 typ host'


def test_inject_host_candidate_lf_only():
    out = live_api._inject_host_candidate('v=0\na=ice-pwd:secret\n', '10.0.0.5')
    assert 'a=candidate:1 1 UDP 2130706431 10.0.0.5 8555 typ host' in out
    assert '\r' not in out


def test_with_lan_candidate_json(app_db):
    Setting.set_value('webrtc_candidate_ip', '192.168.1.10')
    body = b'{"type":"answer","sdp":"v=0\\r\\na=ice-pwd:x\\r\\n"}'
    out = live_api._with_lan_candidate(body, 'application/json')
    obj = json.loads(out)
    assert '192.168.1.10 8555 typ host' in obj['sdp']
    assert obj['type'] == 'answer'                       # other fields preserved


def test_with_lan_candidate_raw_sdp(app_db):
    Setting.set_value('webrtc_candidate_ip', '10.1.2.3')
    out = live_api._with_lan_candidate(b'v=0\r\na=ice-pwd:x\r\n', 'application/sdp')
    assert b'10.1.2.3 8555 typ host' in out


def test_with_lan_candidate_disabled_when_blank(app_db):
    Setting.set_value('webrtc_candidate_ip', '')
    body = b'{"type":"answer","sdp":"v=0\\r\\na=ice-pwd:x\\r\\n"}'
    assert live_api._with_lan_candidate(body, 'application/json') == body   # untouched


def test_with_lan_candidate_bad_body_is_passthrough(app_db):
    """A non-JSON, non-SDP body (or anything unexpected) is returned unchanged — never break
    signaling over a munge error."""
    Setting.set_value('webrtc_candidate_ip', '192.168.1.10')
    assert live_api._with_lan_candidate(b'\xff\xfe garbage', 'application/json') == b'\xff\xfe garbage'
    assert live_api._with_lan_candidate(b'{"no":"sdp"}', 'application/json') == b'{"no":"sdp"}'


def test_settings_get_includes_webrtc_ip(client, mock_go2rtc):
    h = login(client)
    r = client.get('/api/v1/settings/general', headers=h)
    assert r.status_code == 200 and 'webrtc_candidate_ip' in r.json['data']


def test_settings_validates_and_saves_ip(client, mock_go2rtc):
    h = login(client)
    ok = client.put('/api/v1/settings/general', headers=h, json={'webrtc_candidate_ip': '192.168.1.50'})
    assert ok.status_code == 200 and ok.json['data']['webrtc_candidate_ip'] == '192.168.1.50'

    bad = client.put('/api/v1/settings/general', headers=h, json={'webrtc_candidate_ip': 'not-an-ip'})
    assert bad.status_code == 400

    # the rejected value did not overwrite the saved one
    assert client.get('/api/v1/settings/general', headers=h).json['data']['webrtc_candidate_ip'] == '192.168.1.50'

    cleared = client.put('/api/v1/settings/general', headers=h, json={'webrtc_candidate_ip': ''})
    assert cleared.status_code == 200 and cleared.json['data']['webrtc_candidate_ip'] == ''