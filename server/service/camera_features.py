"""Per-camera AI feature gate (PLAN — replaces the global audio/smoke/face/lpr flags).
A camera enables these in its settings (`cameras.ai_features` JSON); the ingest/alert paths
check here instead of a global feature flag.
"""


def is_on(camera_id, name: str) -> bool:
    from server.model import db
    from server.model.camera import Camera
    cam = db.session.query(Camera).filter(Camera.id == camera_id, Camera.deleted_at.is_(None)).first()
    return bool(cam and cam.ai_feature_on(name))
