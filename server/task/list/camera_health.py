"""Periodic camera health + thumbnail refresh (PLAN P1 §5.7).

Online/offline is decided by an actual end-to-end **frame grab** through go2rtc — NOT by
go2rtc's producer *list*. go2rtc keeps a configured source listed even when it has never
connected, and on-demand sources only populate runtime state while a consumer is pulling, so
"`len(producers) > 0`" reports an unreachable camera as online. A frame comes back with bytes
only when go2rtc reached the camera and decoded a picture, so it is the reliable liveness
signal. The same frame is cached as the tile thumbnail, so one grab per camera does double duty.
"""
import logging

from server.driver.go2rtc import Go2rtcDriver
from server.model import db, utcnow
from server.model.camera import STATUS_OFFLINE, STATUS_ONLINE, Camera
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)

THUMB_KEY = 'axp:thumb:%s'
THUMB_TTL = 120
THUMB_WIDTH = 640        # tiles are small; scale the (possibly 4K) frame down for cache/serve


def _thumb_stream(camera):
    """Stream to probe for liveness + grab as the tile thumbnail. Prefer the FULL (main)
    stream: the recorder keeps it continuously connected, so go2rtc serves a warm,
    keyframe-aligned frame instantly. The live (sub) stream is on-demand and — for H.265
    cameras — transcoded, so a cold grab catches a pre-keyframe garbage frame, which is what
    produced the gray thumbnails. Fall back to the live stream, then the first one."""
    return (next((s for s in camera.streams if s.is_default_full), None)
            or next((s for s in camera.streams if s.is_default_live), None)
            or (camera.streams[0] if camera.streams else None))


def _resync_source(camera, stream) -> None:
    """Re-push one camera stream's source into go2rtc (idempotent). Best-effort — a failure
    here must never break the health pass."""
    try:
        from server.service import go2rtc_sync
        from server.driver.go2rtc import Go2rtcDriver
        Go2rtcDriver().put_stream(stream.go2rtc_name, go2rtc_sync.build_source(camera, stream))
    except Exception as e:                       # noqa: BLE001
        logger.debug('go2rtc resync failed for %s: %s', getattr(stream, 'go2rtc_name', '?'), e)


def _registered_names(driver) -> set | None:
    """Names of all streams go2rtc currently has. None if it can't be queried (don't act on
    a failed query — treat as 'unknown' rather than 'nothing registered')."""
    try:
        return set(driver.list_streams().keys())
    except Exception:                            # noqa: BLE001
        return None


def _ensure_all_registered(camera, registered: set | None) -> bool:
    """go2rtc keeps REST streams in memory, so a go2rtc restart drops ALL of them. The
    per-camera liveness probe only re-pushes the default-live stream, so the recording
    (main) stream would stay unregistered and recording silently stops until a manual
    re-sync. If ANY enabled stream is missing from go2rtc, re-push the whole camera.
    Returns True if a full sync was issued."""
    if registered is None:
        return False
    want = {s.go2rtc_name for s in camera.streams if s.enabled}
    if want and not want.issubset(registered):
        try:
            from server.service import go2rtc_sync
            go2rtc_sync.sync_camera(camera)
            return True
        except Exception as e:                   # noqa: BLE001
            logger.debug('go2rtc full resync failed for %s: %s', camera.uuid, e)
    return False


def run_health_pass(driver, redis=None) -> int:
    """Probe every enabled camera with a frame grab → set online/offline + cache its thumbnail.
    Returns the number of cameras whose status row was touched. If go2rtc itself is unreachable
    we skip entirely rather than mass-flip every camera offline on a transient blip."""
    if not driver.healthz():
        logger.warning('camera_health: go2rtc unreachable — skipping status update')
        return 0

    from server.service import automation_events
    updated = 0
    transitions = []
    resynced = 0
    registered = _registered_names(driver)       # one query; reused for every camera below
    for camera in Camera.get_all_enabled():
        # recover ALL streams (incl. the recording/main one) after a go2rtc restart — must run
        # regardless of online state, since a camera can be 'online' via its live/sub stream
        # while its main stream is missing, which silently stops recording.
        if _ensure_all_registered(camera, registered):
            resynced += 1

        stream = _thumb_stream(camera)
        frame = driver.get_frame(stream.go2rtc_name, width=THUMB_WIDTH) if stream else None
        online = bool(frame)

        # self-heal: a frameless camera may be reachable but go2rtc lost/wedged its source
        # (go2rtc stores REST streams in memory → a go2rtc restart drops them, and a dropped
        # camera can leave the producer stuck). Re-register the source so the NEXT pass dials
        # fresh — otherwise the camera stays offline until someone edits it / restarts the backend.
        if not online and stream:
            _resync_source(camera, stream)

        if online and frame:
            if redis is not None:
                try:
                    redis.setex(THUMB_KEY % camera.uuid, THUMB_TTL, frame)
                except Exception as e:  # pragma: no cover
                    logger.warning('thumbnail cache failed for %s: %s', camera.uuid, e)
            from server.service import thumbnail_store
            thumbnail_store.save(camera.uuid, frame)   # durable last-frame (survives offline)

        new_status = STATUS_ONLINE if online else STATUS_OFFLINE
        prev_status = camera.status
        if camera.status != new_status or online:
            camera.status = new_status
            if online:
                camera.last_seen_at = utcnow()
                camera.last_error = None
            db.session.add(camera)
            updated += 1
        if prev_status != new_status:                # real online↔offline edge → automation
            transitions.append((camera.id, new_status))

    db.session.commit()
    # emit AFTER commit so rule actions see the persisted status
    for cam_id, status in transitions:
        automation_events.emit('camera_online' if status == STATUS_ONLINE else 'camera_offline',
                               camera_id=cam_id)
    if resynced:
        logger.info('camera_health: re-registered %d cameras into go2rtc (restart recovery)', resynced)
    logger.info('camera_health: %d cameras updated', updated)
    return updated


@app.task(name='server.task.list.camera_health.camera_health_check')
@celery_use_db()
def camera_health_check():
    """Beat task (30s): frame-grab health + thumbnail cache for every enabled camera."""
    from server.service.token import get_redis
    try:
        redis = get_redis()
    except Exception:
        redis = None
    return run_health_pass(Go2rtcDriver(), redis)


@app.task(name='server.task.list.camera_health.thumbnail_refresh')
@celery_use_db()
def thumbnail_refresh():
    """Deprecated: `camera_health_check` now grabs + caches the thumbnail in the same frame
    pass, so a separate thumbnail beat would only double the camera load. Retained as an alias
    (no longer scheduled) so any lingering registration/import still resolves."""
    return camera_health_check()
