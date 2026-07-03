"""Encoder-node services: registry (join/heartbeat), activity-gated scheduler, offload
gates (live source flip + playback segment offload). Mirrors test_p4_services.py — the
distribution engine is the same pattern; what's new is the live_activity gate and the
pending→active source handover."""
import pytest

import server.service.feature_flag as ff
import server.service.live_activity as la
from server.model import db
from server.model.camera import Camera
from server.model.encode_assignment import STATE_ACTIVE, STATE_PENDING, EncodeAssignment
from server.model.encoding_node import KIND_REMOTE, STATUS_OFFLINE, STATUS_ONLINE, EncodingNode
from server.model.stream import Stream
from server.service import encode_config_resolver, encode_node_registry, encode_offload, encode_scheduler


# ── helpers ─────────────────────────────────────────────────────────────────
def _camera_live(name='cam', codec='h265', active=True) -> tuple[Camera, Stream]:
    c = Camera()
    c.name = name
    c.host = 'h'
    c.vendor = 'onvif'
    c.driver = 'onvif'
    c.is_enabled = True
    db.session.add(c)
    db.session.commit()
    s = Stream()
    s.camera_id = c.id
    s.role = 'sub'
    s.codec = codec
    s.rtsp_path = '/sub'
    s.go2rtc_name = 'cam_%s_sub' % c.id
    s.is_default_live = True
    s.enabled = True
    db.session.add(s)
    db.session.commit()
    if active:
        la.mark(s.go2rtc_name, 300)
    return c, s


def _node(name, max_sessions=4, online=True, endpoint='http://enc:8098') -> EncodingNode:
    n = EncodingNode.create(name=name, kind=KIND_REMOTE)
    n.update(max_sessions=max_sessions, endpoint=endpoint,
             status=STATUS_ONLINE if online else STATUS_OFFLINE)
    return n


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(ff, 'is_enabled', lambda key, **kw: key == 'encoding_nodes')


@pytest.fixture
def no_resync(monkeypatch):
    """Capture go2rtc resyncs instead of hitting HTTP."""
    calls = []
    monkeypatch.setattr(encode_scheduler, 'resync_camera', lambda cid: calls.append(cid))
    return calls


# ── registry ─────────────────────────────────────────────────────────────────
def test_join_issues_token_and_records_capacity(app_db, flag_on, no_resync):
    node = EncodingNode.create(name='e1', kind=KIND_REMOTE)
    res = encode_node_registry.join(node.id, {
        'hwaccel': 'nvenc', 'max_sessions': 8, 'endpoint': 'http://10.0.0.9:8098'})
    assert res['node_token'] and res['heartbeat_interval_s'] > 0
    n2 = EncodingNode.get_by_id(node.id)
    assert n2.status == STATUS_ONLINE and n2.hwaccel == 'nvenc'
    assert n2.max_sessions == 8 and n2.endpoint == 'http://10.0.0.9:8098' and n2.token_jti


def test_join_derives_endpoint_from_ip(app_db, flag_on, no_resync):
    node = EncodingNode.create(name='e1', kind=KIND_REMOTE)
    encode_node_registry.join(node.id, {}, ip='10.1.2.3')
    assert EncodingNode.get_by_id(node.id).endpoint == 'http://10.1.2.3:8098'


def test_heartbeat_flips_pending_to_active_and_resyncs(app_db, flag_on, no_resync):
    cam, _ = _camera_live()
    node = _node('e1')
    EncodeAssignment.assign(cam.id, node.id, state=STATE_PENDING)
    no_resync.clear()
    encode_node_registry.heartbeat(node, {'active_sessions': [cam.id]})
    a = EncodeAssignment.get_for_camera(cam.id)
    assert a.state == STATE_ACTIVE and a.claimed_at is not None
    assert cam.id in no_resync            # source flips local → node-published

    no_resync.clear()                     # already active → no re-flip
    encode_node_registry.heartbeat(node, {'active_sessions': [cam.id]})
    assert no_resync == []


def test_heartbeat_ignores_sessions_of_other_nodes(app_db, flag_on, no_resync):
    cam, _ = _camera_live()
    n1, n2 = _node('e1'), _node('e2')
    EncodeAssignment.assign(cam.id, n1.id, state=STATE_PENDING)
    encode_node_registry.heartbeat(n2, {'active_sessions': [cam.id]})
    assert EncodeAssignment.get_for_camera(cam.id).state == STATE_PENDING


# ── scheduler (activity-gated) ────────────────────────────────────────────────
def test_rebalance_noop_when_flag_off(app_db, no_resync):
    _camera_live()
    _node('e1')
    res = encode_scheduler.rebalance()
    assert res['assigned'] == 0 and EncodeAssignment.all_rows() == []


def test_rebalance_assigns_watched_transcode_cameras(app_db, flag_on, no_resync):
    cam, _ = _camera_live()
    node = _node('e1')
    res = encode_scheduler.rebalance()
    assert res['assigned'] == 1
    a = EncodeAssignment.get_for_camera(cam.id)
    assert a is not None and str(a.node_id) == str(node.id) and a.state == STATE_PENDING
    assert cam.id in no_resync


def test_rebalance_skips_idle_camera(app_db, flag_on, no_resync):
    _camera_live(active=False)            # transcode-eligible but nobody watching
    _node('e1')
    res = encode_scheduler.rebalance()
    assert res['assigned'] == 0 and EncodeAssignment.all_rows() == []


def test_rebalance_skips_h264_camera(app_db, flag_on, no_resync):
    _camera_live(codec='h264')            # watched, but no transcode needed
    _node('e1')
    encode_scheduler.rebalance()
    assert EncodeAssignment.all_rows() == []


def test_rebalance_removes_assignment_when_idle(app_db, flag_on, no_resync):
    cam, s = _camera_live()
    _node('e1')
    encode_scheduler.rebalance()
    assert EncodeAssignment.get_for_camera(cam.id) is not None

    from server.service.token import get_redis
    get_redis().delete(la.KEY_PREFIX + s.go2rtc_name)      # viewers gone
    encode_scheduler.rebalance()
    assert EncodeAssignment.get_for_camera(cam.id) is None  # encoder freed


def test_rebalance_overflow_falls_back_local(app_db, flag_on, no_resync):
    _node('e1', max_sessions=1)
    _camera_live('c1')
    _camera_live('c2')
    res = encode_scheduler.rebalance()
    assert res['assigned'] == 1 and res['pending_count'] == 1


def test_reassign_on_node_offline(app_db, flag_on, no_resync):
    n1, n2 = _node('e1'), _node('e2')
    cam, _ = _camera_live()
    encode_scheduler.rebalance()
    first = EncodeAssignment.get_for_camera(cam.id).node_id
    lost, alive = (n1, n2) if str(first) == str(n1.id) else (n2, n1)
    lost.update(status=STATUS_OFFLINE)
    encode_scheduler.rebalance()
    a = EncodeAssignment.get_for_camera(cam.id)
    assert a is not None and str(a.node_id) == str(alive.id)


def test_kick_assigns_unassigned_camera(app_db, flag_on, no_resync):
    cam, _ = _camera_live()
    _node('e1')
    encode_scheduler.kick(cam.id)
    assert EncodeAssignment.get_for_camera(cam.id) is not None


# ── offload gates ─────────────────────────────────────────────────────────────
def test_live_offload_target_requires_active_and_online(app_db, flag_on):
    cam, s = _camera_live()
    node = _node('e1')
    assert encode_offload.live_offload_target(cam) is None            # no assignment

    EncodeAssignment.assign(cam.id, node.id, state=STATE_PENDING)
    assert encode_offload.live_offload_target(cam) is None            # pending → local

    EncodeAssignment.get_for_camera(cam.id).set_state(STATE_ACTIVE)
    off = encode_offload.live_offload_target(cam)
    assert off == {'enc_name': s.go2rtc_name + '_enc', 'raw_name': s.go2rtc_name + '_raw'}

    node.update(status=STATUS_OFFLINE)                                # node lost → local
    assert encode_offload.live_offload_target(cam) is None


def test_live_offload_target_flag_off(app_db):
    cam, _ = _camera_live()
    node = _node('e1')
    EncodeAssignment.assign(cam.id, node.id, state=STATE_ACTIVE)
    assert encode_offload.live_offload_target(cam) is None


def test_live_job_spec_urls(app_db, flag_on):
    cam, s = _camera_live()
    spec = encode_config_resolver.live_job_spec(cam.id)
    assert spec['pull_url'].endswith(s.go2rtc_name + '_raw')
    assert spec['publish_url'].endswith(s.go2rtc_name + '_enc')
    assert spec['v_codec'] == 'libx264' and spec['camera_id'] == cam.id


# ── playback segment offload ──────────────────────────────────────────────────
def test_transcode_segment_flag_off(app_db, tmp_path):
    src = tmp_path / 'in.ts'
    src.write_bytes(b'x' * 100)
    assert encode_offload.transcode_segment(str(src), str(tmp_path / 'out.ts')) is False


def test_transcode_segment_roundtrip(app_db, flag_on, tmp_path, monkeypatch):
    _node('e1')
    src, out = tmp_path / 'in.ts', tmp_path / 'out.ts'
    src.write_bytes(b'raw-bytes')

    class _Resp:
        status_code = 200
        content = b'h264-ts-bytes'

    import requests
    seen = {}

    def _post(url, data=None, headers=None, timeout=None):
        seen['url'], seen['body'] = url, data
        return _Resp()

    monkeypatch.setattr(requests, 'post', _post)
    assert encode_offload.transcode_segment(str(src), str(out)) is True
    assert out.read_bytes() == b'h264-ts-bytes'
    assert seen['url'] == 'http://enc:8098/transcode' and seen['body'] == b'raw-bytes'


def test_transcode_segment_falls_back_on_error(app_db, flag_on, tmp_path, monkeypatch):
    _node('e1')
    src, out = tmp_path / 'in.ts', tmp_path / 'out.ts'
    src.write_bytes(b'raw')

    import requests
    monkeypatch.setattr(requests, 'post', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('down')))
    assert encode_offload.transcode_segment(str(src), str(out)) is False
    assert not out.exists()


def test_transcode_segment_no_node(app_db, flag_on, tmp_path):
    src = tmp_path / 'in.ts'
    src.write_bytes(b'raw')
    assert encode_offload.transcode_segment(str(src), str(tmp_path / 'o.ts')) is False
