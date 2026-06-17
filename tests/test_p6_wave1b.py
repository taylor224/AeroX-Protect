"""P6 Wave 1 (deferred set) — L1 two-way audio + A1 semantic search."""
from tests.conftest import create_user, login

CAMERA = {'name': 'Talk', 'host': '192.0.2.90', 'vendor': 'onvif', 'driver': 'onvif',
          'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
          'streams': [{'role': 'main', 'rtsp_path': '/main'}]}


def _camera(client, h, **extra):
    return client.post('/api/v1/cameras', headers=h, json={**CAMERA, **extra}).json['data']


# ── L1 two-way audio ──────────────────────────────────────────────────────────
def test_talk_session_single_speaker(app_db):
    from server.service import talk_session
    assert talk_session.acquire(1, 100) is True
    assert talk_session.acquire(1, 200) is False    # one speaker only
    assert talk_session.acquire(1, 100) is True      # same speaker refreshes
    assert talk_session.release(1, 200) is False     # non-owner can't release
    assert talk_session.release(1, 100) is True
    assert talk_session.acquire(1, 200) is True      # now free


def test_talk_offer_ok_and_stop(client, mock_go2rtc, monkeypatch):
    h = login(client)
    cam = _camera(client, h, two_way_audio=True)

    class FakeResp:
        content = b'v=0\r\na=answer'
        status_code = 200
        headers = {'Content-Type': 'application/sdp'}

    monkeypatch.setattr('server.view.api.talk.requests.post', lambda *a, **k: FakeResp())
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/talk/offer", headers=h,
                    data=b'v=0\r\na=offer', content_type='application/sdp')
    assert r.status_code == 200 and b'answer' in r.data
    assert client.post(f"/api/v1/cameras/{cam['uuid']}/talk/stop", headers=h).status_code == 200


def test_talk_unsupported_camera(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)            # two_way_audio defaults false
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/talk/offer", headers=h,
                    data=b'x', content_type='application/sdp')
    assert r.status_code == 400


def test_talk_flag_gate(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h, two_way_audio=True)
    client.put('/api/v1/feature-flags/two_way_audio', headers=h, json={'enabled': False})
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/talk/offer", headers=h,
                    data=b'x', content_type='application/sdp')
    assert r.status_code == 403


def test_talk_scope_denied(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h, two_way_audio=True)
    create_user(client, h, 'talk_u', {'audio': ['talk']})   # perm, no camera scope
    vh = login(client, 'talk_u', 'viewer1234!')
    r = client.post(f"/api/v1/cameras/{cam['uuid']}/talk/offer", headers=vh,
                    data=b'x', content_type='application/sdp')
    assert r.status_code == 403


# ── A1 semantic search ────────────────────────────────────────────────────────
def test_semantic_reindex_and_search(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    for t in ('motion', 'intrusion', 'motion'):
        client.post('/api/v1/events/simulate', headers=h,
                    json={'camera_uuid': cam['uuid'], 'type': t, 'score': 70})

    ri = client.post('/api/v1/search/semantic/reindex', headers=h, json={})
    assert ri.status_code == 200, ri.json
    assert ri.json['data']['indexed'] >= 3 and ri.json['data']['backend'] == 'hash'

    sr = client.get('/api/v1/search/semantic?q=intrusion', headers=h)
    assert sr.status_code == 200, sr.json
    data = sr.json['data']
    assert data['count'] >= 1 and any('intrusion' in (i['text'] or '') for i in data['items'])
    assert data['items'][0]['score'] > 0


def test_semantic_flag_gate(client, mock_go2rtc):
    h = login(client)
    client.put('/api/v1/feature-flags/semantic_search', headers=h, json={'enabled': False})
    assert client.get('/api/v1/search/semantic?q=x', headers=h).status_code == 403


def test_semantic_scope_default_deny(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    client.post('/api/v1/events/simulate', headers=h, json={'camera_uuid': cam['uuid'], 'type': 'motion'})
    client.post('/api/v1/search/semantic/reindex', headers=h, json={})
    create_user(client, h, 'sem_u', {'ai': ['semantic_search']})   # no camera scope
    vh = login(client, 'sem_u', 'viewer1234!')
    r = client.get('/api/v1/search/semantic?q=motion', headers=vh)
    assert r.status_code == 200 and r.json['data']['count'] == 0


def test_semantic_empty_query(client, mock_go2rtc):
    h = login(client)
    _camera(client, h)
    assert client.get('/api/v1/search/semantic?q=', headers=h).json['data']['count'] == 0
