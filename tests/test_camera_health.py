"""Camera online/offline health — decided by a real go2rtc frame grab, not the producer list.

A configured-but-unreachable camera has a producer entry in go2rtc yet returns no frame, so the
frame-grab signal is what tells reachable from merely-registered.
"""
from server.model.camera import Camera
from server.task.list import camera_health
from tests.conftest import login


class _FakeDriver:
    """Stand-in for Go2rtcDriver: configurable go2rtc-up + per-name frame bytes.
    `streams` (when set) is what list_streams() reports go2rtc currently has registered."""
    def __init__(self, frame=None, up=True, streams=None):
        self._frame, self._up = frame, up
        self._streams = streams
        self.asked = []

    def healthz(self):
        return self._up

    def get_frame(self, name, width=None, **kwargs):
        self.asked.append(name)
        return self._frame

    def list_streams(self):
        if self._streams is None:
            raise AttributeError('list_streams not configured')
        return {name: {} for name in self._streams}


def _camera(client, h, host='192.0.2.50'):
    return client.post('/api/v1/cameras', headers=h, json={
        'name': 'H', 'host': host, 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/m'}]}).json['data']


def test_thumbnail_grabbed_from_full_stream_not_live(client, mock_go2rtc):
    """The tile thumbnail must be grabbed from the FULL (main) stream — kept warm by the
    recorder, so go2rtc returns a clean keyframe — NOT the on-demand/transcoded live (sub)
    stream whose cold grab catches pre-keyframe garbage → a gray thumbnail."""
    h = login(client)
    cam = client.post('/api/v1/cameras', headers=h, json={
        'name': 'D', 'host': '192.0.2.60', 'vendor': 'onvif', 'driver': 'onvif',
        'streams': [{'role': 'main', 'rtsp_path': '/main'}, {'role': 'sub', 'rtsp_path': '/sub'}]}).json['data']
    c = Camera.get_by_uuid(cam['uuid'])
    main = next(s.go2rtc_name for s in c.streams if s.is_default_full)
    sub = next(s.go2rtc_name for s in c.streams if s.is_default_live)
    drv = _FakeDriver(frame=b'\xff\xd8jpeg')
    camera_health.run_health_pass(drv)
    assert main in drv.asked and sub not in drv.asked


def test_frame_present_marks_online(client, mock_go2rtc):
    h = login(client)
    cam = _camera(client, h)
    n = camera_health.run_health_pass(_FakeDriver(frame=b'\xff\xd8jpeg-bytes'))
    assert n == 1
    c = Camera.get_by_uuid(cam['uuid'])
    assert c.status == 'online' and c.last_seen_at is not None and c.last_error is None


def test_no_frame_marks_offline(client, mock_go2rtc):
    """The key fix: a camera go2rtc lists but can't actually pull a frame from is OFFLINE."""
    h = login(client)
    cam = _camera(client, h)
    camera_health.run_health_pass(_FakeDriver(frame=b'x'))      # online first
    camera_health.run_health_pass(_FakeDriver(frame=None))      # now no frame
    assert Camera.get_by_uuid(cam['uuid']).status == 'offline'


def test_offline_camera_resyncs_go2rtc_source(client, mock_go2rtc, monkeypatch):
    """A frameless (offline) camera gets its go2rtc source re-registered so it can recover
    even if go2rtc lost/wedged the stream — instead of staying offline forever."""
    from server.driver.go2rtc import Go2rtcDriver
    pushed = []
    monkeypatch.setattr(Go2rtcDriver, 'put_stream', lambda self, name, src: pushed.append(name))
    h = login(client)
    cam = _camera(client, h)
    camera_health.run_health_pass(_FakeDriver(frame=None))      # offline → should resync
    assert any(cam['uuid'] in n for n in pushed)


def test_missing_main_stream_triggers_full_resync(client, mock_go2rtc, monkeypatch):
    """After a go2rtc restart the recording (main) stream can be missing while the camera is
    still 'online' via its live stream. The health pass must re-push the WHOLE camera so
    recording recovers — not just the probed live stream. Regression for: go2rtc restart
    silently stops recording until a manual re-sync."""
    from server.service import go2rtc_sync
    h = login(client)
    cam = _camera(client, h)                                    # create itself syncs once
    c = Camera.get_by_uuid(cam['uuid'])
    want = {s.go2rtc_name for s in c.streams if s.enabled}
    synced = []
    monkeypatch.setattr(go2rtc_sync, 'sync_camera', lambda cam: synced.append(cam.id) or {})
    # go2rtc reports it has NONE of the camera's streams → full re-sync expected
    camera_health.run_health_pass(_FakeDriver(frame=b'\xff\xd8x', streams=set()))
    assert c.id in synced
    assert want                                                 # sanity: the camera has streams


def test_all_streams_present_no_resync(client, mock_go2rtc, monkeypatch):
    """When every enabled stream is already registered, no redundant full re-sync is issued."""
    from server.service import go2rtc_sync
    h = login(client)
    cam = _camera(client, h)
    c = Camera.get_by_uuid(cam['uuid'])
    present = {s.go2rtc_name for s in c.streams if s.enabled}
    synced = []
    monkeypatch.setattr(go2rtc_sync, 'sync_camera', lambda cam: synced.append(cam.id) or {})
    camera_health.run_health_pass(_FakeDriver(frame=b'\xff\xd8x', streams=present))
    assert synced == []


def test_go2rtc_down_does_not_mass_flip(client, mock_go2rtc):
    """If go2rtc is unreachable we skip — don't flip every camera offline on a transient blip."""
    h = login(client)
    cam = _camera(client, h)
    camera_health.run_health_pass(_FakeDriver(frame=b'x'))      # online
    drv = _FakeDriver(up=False)
    assert camera_health.run_health_pass(drv) == 0
    assert drv.asked == []                                      # never even probed cameras
    assert Camera.get_by_uuid(cam['uuid']).status == 'online'   # status preserved


def test_thumbnail_cached_on_online(client, mock_go2rtc, redis_client):
    h = login(client)
    cam = _camera(client, h)
    camera_health.run_health_pass(_FakeDriver(frame=b'JPEGDATA'), redis=redis_client)
    assert redis_client.get(camera_health.THUMB_KEY % cam['uuid']) is not None


def test_last_frame_persisted_and_served_when_offline(client, mock_go2rtc, redis_client, monkeypatch, tmp_path):
    """The last online frame is written to disk and still served after the camera goes offline
    and the Redis cache expires — the tile keeps its last picture instead of going blank."""
    monkeypatch.setattr('config.THUMB_DIR', str(tmp_path))
    h = login(client)
    cam = _camera(client, h)

    # online pass writes the durable file (must be a real JPEG to be persisted)
    jpeg = b'\xff\xd8' + b'L' * 800
    camera_health.run_health_pass(_FakeDriver(frame=jpeg), redis=redis_client)
    from server.service import thumbnail_store
    assert thumbnail_store.load(cam['uuid']) == jpeg

    # camera goes offline + Redis cache gone → thumbnail endpoint serves the persisted file
    camera_health.run_health_pass(_FakeDriver(frame=None), redis=redis_client)
    redis_client.flushall()
    r = client.get(f"/api/v1/cameras/{cam['uuid']}/thumbnail", headers=h)
    assert r.status_code == 200 and r.data == jpeg

    # deleting the camera removes the file
    client.delete(f"/api/v1/cameras/{cam['uuid']}", headers=h)
    assert thumbnail_store.load(cam['uuid']) is None


def test_editing_camera_does_not_flip_offline_to_online(client, mock_go2rtc):
    """Editing a camera (e.g. fisheye) re-registers its stream in go2rtc, but registration is
    NOT a reachability check — an offline camera must stay offline until the health check says
    otherwise. Regression for the 'toggle fisheye → camera jumps back online' bug."""
    h = login(client)
    cam = _camera(client, h)
    camera_health.run_health_pass(_FakeDriver(frame=None))      # health: offline
    assert Camera.get_by_uuid(cam['uuid']).status == 'offline'

    r = client.post(f"/api/v1/cameras/{cam['uuid']}", headers=h, json={'fisheye': True})
    assert r.status_code == 200, r.json
    assert r.json['data']['status'] == 'offline'                # not fabricated online
    assert Camera.get_by_uuid(cam['uuid']).status == 'offline'
