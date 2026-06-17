"""Regression tests for the second full-codebase audit pass:
- OVER_STOP stops only the offending camera (never the shared global policy)
- sweep keeps the segment index of a soft-deleted (unregistered) disk
- evacuate keeps the index row when a move fails (no orphaned files)
- users:update cannot self-escalate permissions / manage a superuser
- api_tokens:manage cannot mint scopes the creator doesn't hold
- external SSE honors the token's camera scope
- quiet-hours reads the event's start_ts (a missing 'ts' meant "always quiet")
- muted_until accepts epoch-ms and can be cleared
- require_pin denies PIN-less credentials
- LPR/face ingest reject bad confidence/embedding rows without aborting the batch
- face consent revocation removes the identity from the match pool
- outbox poison rows go FAILED after MAX_ATTEMPTS (no infinite retry)
- federation keeps the camera cache on a malformed member response
- loitering emits carry per-track dedup_extra (no cooldown collapse)
- schedule-discarded events are not published to the outbox
"""
from datetime import datetime, timedelta

from server.model import UTC, db, to_epoch_ms, utcnow
from server.model.camera import Camera
from server.model.disk import ROLE_RECORD, Disk
from server.model.segment import Segment
from server.model.storage_policy import OVER_STOP, RECORD_CONTINUOUS, RECORD_OFF, StoragePolicy
from tests.conftest import create_user, login

MB = 10 ** 6


def _camera(name='c') -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'onvif', 'onvif', True
    db.session.add(c)
    db.session.commit()
    return c


def _disk(name='d', mount='/tmp/axp_test_audit2/d') -> Disk:
    d = Disk()
    d.name = name
    d.mount_path = mount
    d.role = ROLE_RECORD
    d.total_bytes = 200 * 1024 ** 3
    d.free_bytes = 100 * 1024 ** 3
    db.session.add(d)
    db.session.commit()
    return d


def _seg(cam, disk, start, dur=10, size=MB) -> Segment:
    return Segment.create(
        camera_id=cam.id, disk_id=disk.id,
        rel_path='%s/seg-%s.mp4' % (cam.id, start.strftime('%Y%m%d-%H%M%S')),
        start_ts=start, end_ts=start + timedelta(seconds=dur),
        duration_ms=dur * 1000, size_bytes=size)


# ── retention: OVER_STOP must not flip the global policy off ─────────────────
def test_over_stop_does_not_disable_global_policy(app_db):
    from server.service.retention_engine import run_retention
    cam, disk = _camera(), _disk()
    g = StoragePolicy.upsert_for_camera(None, {
        'record_mode': RECORD_CONTINUOUS, 'retention_max_bytes': 1 * MB,
        'over_capacity_policy': OVER_STOP})
    _seg(cam, disk, utcnow() - timedelta(minutes=5), size=5 * MB)   # over quota

    res = run_retention()
    assert any(w.startswith('capacity_full_stopped') for w in res['warnings'])
    assert StoragePolicy.get_global().record_mode == RECORD_CONTINUOUS   # global untouched
    row = StoragePolicy.get_raw_for_camera(cam.id)
    assert row is not None and row.record_mode == RECORD_OFF             # per-camera stop
    assert g.id != row.id


# ── sweep: unregistered (soft-deleted) disk keeps its segment index ───────────
def test_sweep_keeps_index_for_unregistered_disk(app_db):
    from server.task.list.segment_sweep import sweep
    cam, disk = _camera(), _disk()
    kept = _seg(cam, disk, utcnow() - timedelta(minutes=10))
    orphan = _seg(cam, disk, utcnow() - timedelta(minutes=9))
    orphan.disk_id = 987654321                       # disk row gone entirely → true orphan
    db.session.add(orphan)
    disk.deleted_at = utcnow()                       # unregister = soft delete
    disk.enabled = False
    db.session.add(disk)
    db.session.commit()

    res = sweep()
    assert Segment.get_by_id(kept.id) is not None    # index remains (doc: "index remains")
    assert Segment.get_by_id(orphan.id) is None      # rows w/o ANY disk row are pruned
    assert res['orphans'] == 1


# ── evacuate: a failed move keeps the index row ───────────────────────────────
def test_evacuate_keeps_row_on_move_failure(app_db):
    from server.task.list.segment_sweep import evacuate_disk
    cam = _camera()
    src = _disk('src', '/tmp/axp_test_audit2/src')
    _disk('dst', '/tmp/axp_test_audit2/dst')
    seg = _seg(cam, src, utcnow() - timedelta(minutes=5))   # no actual file → move fails

    res = evacuate_disk(str(src.id))
    assert res['moved'] == 0 and res['failed'] == 1
    row = Segment.get_by_id(seg.id)
    assert row is not None and row.disk_id == src.id        # row kept for retry


# ── privilege escalation guards ───────────────────────────────────────────────
def test_user_manager_cannot_self_escalate(client):
    h = login(client)
    mgr = create_user(client, h, 'mgr', {'users': ['read', 'update', 'create']})
    mh = login(client, 'mgr', 'viewer1234!')

    # granting a permission the actor doesn't hold → 403
    r = client.post('/api/v1/admin/users/%s' % mgr['uuid'], headers=mh,
                    json={'permissions': {'*': ['*']}})
    assert r.status_code == 403
    r = client.post('/api/v1/admin/users/%s' % mgr['uuid'], headers=mh,
                    json={'role': 'admin'})
    assert r.status_code == 403
    # creating a superuser is equally blocked
    r = client.post('/api/v1/admin/users', headers=mh, json={
        'login_id': 'evil', 'password': 'evil12345!', 'name': 'E',
        'role': 'user', 'permissions': {'*': ['*']}})
    assert r.status_code == 403
    # benign self-edit still works
    r = client.post('/api/v1/admin/users/%s' % mgr['uuid'], headers=mh, json={'name': 'MGR2'})
    assert r.status_code == 200

    # a non-superuser cannot manage (reset-password / edit) a superuser account
    admin_uuid = next(u['uuid'] for u in
                      client.get('/api/v1/admin/users', headers=mh).json['data']['items']
                      if u['login_id'] == 'admin')
    r = client.post('/api/v1/admin/users/%s/reset_password' % admin_uuid, headers=mh,
                    json={'password': 'hacked1234!'})
    assert r.status_code == 403


def test_api_token_scopes_limited_to_creator_permissions(client):
    h = login(client)
    create_user(client, h, 'tk', {'api_tokens': ['manage']})
    th = login(client, 'tk', 'viewer1234!')
    r = client.post('/api/v1/api-tokens', headers=th,
                    json={'name': 'x', 'scopes': {'events': ['read']}})
    assert r.status_code == 403                       # tk doesn't hold events:read

    create_user(client, h, 'tk2', {'api_tokens': ['manage'], 'events': ['read']})
    th2 = login(client, 'tk2', 'viewer1234!')
    r = client.post('/api/v1/api-tokens', headers=th2,
                    json={'name': 'y', 'scopes': {'events': ['read']}})
    assert r.status_code == 200                       # delegating what you hold is fine
    # malformed scope shape rejected
    r = client.post('/api/v1/api-tokens', headers=h,
                    json={'name': 'z', 'scopes': {'events': 'read'}})
    assert r.status_code == 400


# ── external SSE camera scope ─────────────────────────────────────────────────
def test_ext_stream_honors_camera_scope(client, monkeypatch):
    import server.view.api.external as ext_view
    from server.model.api_token import ApiToken
    from server.model.event import Event
    monkeypatch.setattr(ext_view.time, 'sleep', lambda s: None)

    cam_a, cam_b = _camera('a'), _camera('b')
    # event slightly in the future so the stream's `start=last` window picks it up
    Event.create(camera_id=cam_a.id, type='motion', source='vendor',
                 dedup_key='k1', start_ts=utcnow() + timedelta(seconds=2))

    _, raw_b = ApiToken.issue('scoped-b', {'events': ['read']}, camera_ids=[cam_b.id])
    r = client.get('/api/v1/ext/stream?camera_id=%s' % cam_a.id,
                   headers={'Authorization': 'Bearer ' + raw_b})
    assert r.status_code == 200
    assert 'data:' not in r.get_data(as_text=True)    # out-of-scope → nothing leaks

    _, raw_a = ApiToken.issue('scoped-a', {'events': ['read']}, camera_ids=[cam_a.id])
    r = client.get('/api/v1/ext/stream?camera_id=%s' % cam_a.id,
                   headers={'Authorization': 'Bearer ' + raw_a})
    assert 'data:' in r.get_data(as_text=True)        # in-scope still streams


# ── notifications: quiet hours + snooze ───────────────────────────────────────
def _sub(**kw):
    from server.model.notification_subscription import NotificationSubscription
    s = NotificationSubscription()
    s.channel = 'push'
    s.min_priority = 'normal'
    s.muted = False
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_quiet_hours_uses_event_start_ts(app_db):
    from server.service.notification_router import _suppressed
    quiet = {'ranges': [{'start': '00:00', 'end': '06:00'}]}    # KST 00–06
    noon_kst = int(datetime(2026, 6, 11, 3, 0, tzinfo=UTC).timestamp() * 1000)   # KST 12:00
    night_kst = int(datetime(2026, 6, 11, 18, 0, tzinfo=UTC).timestamp() * 1000)  # KST 03:00

    sub = _sub(quiet_hours=quiet)
    # event payloads have start_ts (epoch ms), not 'ts' — must not read as "always quiet"
    assert _suppressed(sub, 'normal', {'start_ts': noon_kst}) is False
    assert _suppressed(sub, 'normal', {'start_ts': night_kst}) is True


def test_muted_until_epoch_ms_coerced_and_clearable(app_db):
    from server.model.notification_subscription import NotificationSubscription
    from server.service.notification_router import _suppressed
    future_ms = to_epoch_ms(utcnow() + timedelta(minutes=30))
    sub = NotificationSubscription.create(1, {'channel': 'push', 'muted_until': future_ms})
    assert isinstance(sub.muted_until, datetime)              # not a raw int
    assert _suppressed(sub, 'critical', {'start_ts': to_epoch_ms(utcnow())}) is True
    sub.modify({'muted_until': None})                         # explicit null clears the snooze
    assert sub.muted_until is None
    assert _suppressed(sub, 'normal', {'start_ts': to_epoch_ms(utcnow())}) is False


# ── access control: require_pin ───────────────────────────────────────────────
def test_require_pin_denies_pinless_credential(app_db):
    from server.model.access_credential import AccessCredential
    from server.model.door import Door
    from server.service import access_control
    door = Door.create({'name': 'P', 'controller_type': 'mock', 'access_group': 'default',
                        'require_pin': True})
    AccessCredential.create({'card_number': 'NOPIN', 'holder_name': 'H', 'access_group': 'default'})
    res = access_control.evaluate(door, 'NOPIN')              # no PIN on card, none supplied
    assert res['decision'] == 'denied' and res['reason'] == 'bad_pin'

    AccessCredential.create({'card_number': 'WITHPIN', 'holder_name': 'H2',
                             'access_group': 'default', 'pin': '1234'})
    assert access_control.evaluate(door, 'WITHPIN', '1234')['decision'] == 'granted'
    assert access_control.evaluate(door, 'WITHPIN', '9999')['decision'] == 'denied'


# ── ingest poison pills ───────────────────────────────────────────────────────
def _node():
    from server.model.ai_node import KIND_REMOTE, STATUS_ONLINE, AiNode
    n = AiNode.create(name='n', kind=KIND_REMOTE)
    n.update(status=STATUS_ONLINE)
    return n


def test_lpr_bad_confidence_rejects_only_that_row(app_db, monkeypatch):
    from server.model.detection_assignment import DetectionAssignment
    from server.service import feature_flag, lpr_ingest
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    node, cam = _node(), _camera()
    DetectionAssignment.assign(cam.id, node.id)
    res = lpr_ingest.ingest_batch(node, [
        {'camera_id': cam.id, 'plate_text': 'AAA111', 'confidence': 'high'},
        {'camera_id': cam.id, 'plate_text': 'BBB222', 'confidence': '95.5'},
        {'camera_id': cam.id, 'plate_text': 'CCC333', 'confidence': 90},
    ])
    assert res['accepted'] == 2                       # float-string parses; junk rejected
    assert any(r['reason'] == 'bad_confidence' for r in res['rejected'])


def test_face_bad_embedding_rejects_only_that_row(app_db, monkeypatch):
    from server.model.detection_assignment import DetectionAssignment
    from server.service import face_ingest, feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: True)
    node, cam = _node(), _camera()
    DetectionAssignment.assign(cam.id, node.id)
    res = face_ingest.ingest_batch(node, [
        {'camera_id': cam.id, 'embedding': [0.1, 'x', 0.2], 'backend': 'arc'},
        {'camera_id': cam.id, 'embedding': [0.1, 0.2], 'backend': 'arc'},
    ])
    assert res['accepted'] == 1
    assert any(r['reason'] == 'bad_embedding' for r in res['rejected'])


# ── face consent ──────────────────────────────────────────────────────────────
def test_consent_revocation_stops_matching(app_db):
    from server.model.face_identity import FaceIdentity
    from server.service import face_match
    ident = FaceIdentity.create(name='p', consent=True)
    ident.add_embedding([1.0, 0.0], 'arc', 2)
    matched, score = face_match.match([1.0, 0.0], 'arc')
    assert matched is not None and matched.id == ident.id

    ident.modify({'consent': False})
    matched, _ = face_match.match([1.0, 0.0], 'arc')
    assert matched is None                            # revoked → out of the match pool


# ── outbox: poison row goes FAILED ────────────────────────────────────────────
def test_outbox_poison_row_marked_failed(app_db, monkeypatch):
    from server.model.event import Event
    from server.model.event_outbox import STATUS_FAILED, EventOutbox
    from server.service import trigger_router
    from server.task.list import outbox_consumer
    cam = _camera()
    ev = Event.create(camera_id=cam.id, type='motion', source='vendor',
                      dedup_key='poison', start_ts=utcnow())
    row = EventOutbox.publish(ev)
    monkeypatch.setattr(trigger_router, 'from_outbox',
                        lambda r: (_ for _ in ()).throw(RuntimeError('boom')))
    for _ in range(outbox_consumer.MAX_ATTEMPTS):
        outbox_consumer.consume()
    fresh = db.session.query(EventOutbox).filter(EventOutbox.id == row.id).first()
    assert fresh.status == STATUS_FAILED              # no infinite hot-loop retry
    assert outbox_consumer.consume() == 0             # no longer selected


# ── federation: malformed 200 keeps the cache ─────────────────────────────────
def test_federation_malformed_state_keeps_cache(app_db, monkeypatch):
    from server.model.federation_camera import FederationCamera
    from server.model.federation_member import FederationMember
    from server.service import federation
    member = FederationMember.create(name='m', base_url='http://member')
    FederationCamera.replace_for_member(member.id, [{'uuid': 'u1', 'name': 'c1'}])

    class _Stub:
        def state(self):
            return {}                                 # 200 but no cameras key

    monkeypatch.setattr(federation, '_client', lambda m: _Stub())
    res = federation.sync_member(member.id)
    assert res == {'ok': False, 'error': 'malformed_state'}
    assert len(FederationCamera.for_members([member.id])) == 1   # cache intact


# ── counting: loitering dedup per line+track ──────────────────────────────────
def test_loitering_emits_per_track_dedup_extra(app_db, monkeypatch, redis_client):
    from server.service import counting, event_pipeline
    captured = []
    monkeypatch.setattr(event_pipeline, 'ingest_object',
                        lambda cam_id, payload: captured.append(payload))

    class _Line:
        id, loiter_threshold_s, geometry = 7, 1, [[0, 0], [1, 0], [1, 1], [0, 1]]

    t0 = utcnow()
    counting._dwell(redis_client, 1, _Line, 'trk-1', t0, 'person')                       # enter
    counting._dwell(redis_client, 1, _Line, 'trk-1', t0 + timedelta(seconds=2), 'person')  # dwell met
    assert captured and captured[0]['dedup_extra'] == '7:trk-1'


# ── pipeline: schedule-discard publishes no notification ──────────────────────
def test_schedule_discard_does_not_publish_outbox(app_db, monkeypatch):
    from server.model.event_outbox import EventOutbox
    from server.model.event_policy import EventPolicy
    from server.model.schedule import MODE_OFF
    from server.service import event_pipeline
    cam = _camera()
    EventPolicy.create({'camera_id': cam.id, 'event_type': 'object', 'action': 'record',
                        'pre_buffer_s': 5, 'post_buffer_s': 10})    # notify defaults True
    monkeypatch.setattr(event_pipeline.schedule_resolver, 'mode', lambda cid, ts: MODE_OFF)
    ev = event_pipeline.ingest_object(cam.id, {'type': 'object', 'subtype': 'person', 'score': 90})
    assert ev is not None and ev.policy_action == 'discard'
    assert db.session.query(EventOutbox).count() == 0   # discard ⇒ no notification traffic
