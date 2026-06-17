"""P3 event pipeline: state machine, dedup absorption, cooldown, score gate, event clip.

Uses source='manual' (simulate path) so events are injected without real cameras."""
from server.model import db
from server.model.camera import Camera
from server.model.event import STATE_ACTIVE, STATE_ENDED, STATE_PULSE, Event
from server.model.event_policy import EventPolicy
from server.model.recording import CLASS_EVENT, REASON_EVENT, Recording
from server.service import event_pipeline


def _camera() -> Camera:
    c = Camera()
    c.name = 'pipe'
    c.host = 'h'
    c.vendor = 'onvif'
    c.driver = 'onvif'
    c.is_enabled = True
    db.session.add(c)
    db.session.commit()
    return c


def test_unknown_type_ignored(app_db):
    assert event_pipeline.handle(_camera(), {'type': 'bogus'}, 'manual') is None


def test_state_machine_start_then_end(app_db):
    cam = _camera()
    ev = event_pipeline.handle(cam, {'type': 'tamper', 'state': 'start'}, 'manual')
    assert ev.state == STATE_ACTIVE and ev.end_ts is None
    ended = event_pipeline.handle(cam, {'type': 'tamper', 'state': 'end'}, 'manual')
    assert ended.id == ev.id                       # the active event is closed, not a new row
    assert ended.state == STATE_ENDED and ended.end_ts is not None and ended.duration_ms is not None


def test_duplicate_start_absorbed(app_db):
    cam = _camera()
    e1 = event_pipeline.handle(cam, {'type': 'tamper', 'state': 'start'}, 'manual')
    e2 = event_pipeline.handle(cam, {'type': 'tamper', 'state': 'start'}, 'manual')
    assert e2.id == e1.id                           # duplicate start absorbed
    total, _ = Event.get_list(camera_ids=[cam.id])
    assert total == 1


def test_pulse_creates_distinct(app_db):
    cam = _camera()
    a = event_pipeline.handle(cam, {'type': 'tamper'}, 'manual')        # state defaults to pulse
    b = event_pipeline.handle(cam, {'type': 'tamper'}, 'manual')
    assert a.state == STATE_PULSE and a.id != b.id   # tamper→notify_only, no cooldown to suppress


def test_motion_records_with_clip(app_db):
    cam = _camera()
    ev = event_pipeline.handle(cam, {'type': 'motion', 'score': 90}, 'manual')
    assert ev.policy_action == 'record'
    fresh = Event.get_by_id(ev.id)
    assert fresh.recording_id is not None
    rec = Recording.get_by_id(int(fresh.recording_id))
    assert rec.reason == REASON_EVENT and rec.retention_class == CLASS_EVENT


def test_cooldown_suppresses_second(app_db):
    cam = _camera()
    first = event_pipeline.handle(cam, {'type': 'motion', 'score': 90}, 'manual')
    second = event_pipeline.handle(cam, {'type': 'motion', 'score': 90}, 'manual')
    assert Event.get_by_id(first.id).recording_id is not None
    assert second.policy_action == 'discard:cooldown'
    event_recs = [r for r in Recording.list_for_camera(cam.id) if r.reason == REASON_EVENT]
    assert len(event_recs) == 1                      # second did not materialize


def test_min_score_discards(app_db):
    cam = _camera()
    EventPolicy.create({'camera_id': cam.id, 'event_type': 'motion', 'action': 'record',
                        'min_score': 50, 'pre_buffer_s': 5, 'post_buffer_s': 10})
    ev = event_pipeline.handle(cam, {'type': 'motion', 'score': 10}, 'manual')
    assert ev.policy_action == 'discard:score'
    assert Event.get_by_id(ev.id).recording_id is None
