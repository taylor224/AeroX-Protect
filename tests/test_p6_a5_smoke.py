"""P6 A5 — smoke/fire auxiliary alerting.

A dedicated smoke/fire model is required at inference time (not COCO), so there is NO
dependency-free stub for the *detection* itself (a heuristic would be irresponsible for a
safety feature). What ships + is tested here is the wiring: label normalization, and the
per-camera-gated detection→`smoke` event promotion with confidence floor + per-camera cooldown.
Each camera opts in via `ai_features.smoke` (off by default, model-dependent).
"""
from server.model import db
from server.model.camera import Camera
from server.model.event import TYPE_SMOKE, Event


def _camera(name='smokecam', ai=None) -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, 'h', 'onvif', 'onvif', True
    if ai:
        c.ai_features = ai
    db.session.add(c)
    db.session.commit()
    return c


def _smoke_cam():
    return _camera(ai={'smoke': True})                # per-camera AI enable


def _smoke_events(cam_id):
    return db.session.query(Event).filter(Event.camera_id == cam_id, Event.type == TYPE_SMOKE).all()


# ── label map ────────────────────────────────────────────────────────────────
def test_label_map_normalizes_smoke_fire():
    from server.service import label_map
    assert label_map.normalize(1000, None) == (1000, 'smoke')
    assert label_map.normalize(None, 'smoke') == (1000, 'smoke')
    assert label_map.normalize(None, 'fire') == (1001, 'fire')
    assert 'smoke' in label_map.SMOKE_LABELS and 'fire' in label_map.SMOKE_LABELS


def test_smoke_type_registered():
    from server.service.event_normalizer import VALID_TYPES
    assert TYPE_SMOKE in VALID_TYPES


# ── alert promotion ──────────────────────────────────────────────────────────
def test_smoke_alert_raises_event(app_db):
    from server.service import smoke_alert
    cam = _smoke_cam()
    smoke_alert.process_batch(cam.id, [
        {'label': 'person', 'confidence': 95, 'bbox': [0.1, 0.1, 0.2, 0.2]},   # ignored
        {'label': 'smoke', 'confidence': 82, 'bbox': [0.3, 0.3, 0.5, 0.6]},    # → event
    ])
    evs = _smoke_events(cam.id)
    assert len(evs) == 1 and evs[0].subtype == 'smoke'


def test_smoke_alert_feature_off_noop(app_db):
    from server.service import smoke_alert
    cam = _camera()                                  # ai_features.smoke off by default
    smoke_alert.process_batch(cam.id, [{'label': 'smoke', 'confidence': 99, 'bbox': [0, 0, 1, 1]}])
    assert _smoke_events(cam.id) == []


def test_smoke_alert_below_threshold_noop(app_db):
    from server.service import smoke_alert
    cam = _smoke_cam()
    smoke_alert.process_batch(cam.id, [{'label': 'fire', 'confidence': 20, 'bbox': [0, 0, 1, 1]}])
    assert _smoke_events(cam.id) == []


def test_smoke_alert_cooldown(app_db):
    from server.service import smoke_alert
    cam = _smoke_cam()
    rows = [{'label': 'smoke', 'confidence': 88, 'bbox': [0, 0, 1, 1]}]
    smoke_alert.process_batch(cam.id, rows)
    smoke_alert.process_batch(cam.id, rows)          # within cooldown window → suppressed
    assert len(_smoke_events(cam.id)) == 1


def test_smoke_alert_picks_highest_confidence(app_db):
    from server.service import smoke_alert
    cam = _smoke_cam()
    smoke_alert.process_batch(cam.id, [
        {'label': 'smoke', 'confidence': 55, 'bbox': [0, 0, 1, 1]},
        {'label': 'fire', 'confidence': 91, 'bbox': [0, 0, 1, 1]},
    ])
    evs = _smoke_events(cam.id)
    assert len(evs) == 1 and evs[0].subtype == 'fire'      # highest-confidence candidate wins
