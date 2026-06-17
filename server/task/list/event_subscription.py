"""Camera event-subscription worker (PLAN §5.5). Long-lived per-camera loop +
a supervisor beat that (re)spawns subscriptions for event-capable cameras.

No event-capable cameras in CI → the supervisor is a no-op; the loop is structural
and activates when a real ONVIF/ISAPI/SUNAPI camera reports event support."""
import logging
import time

import config
from server.model import db, utcnow
from server.model.camera import Camera
from server.model.camera_subscription import CameraSubscription
from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)

POLL_TIMEOUT = 10
LOCK_TTL = 90


def _is_event_capable(camera: Camera) -> bool:
    caps = camera.capabilities or {}
    events = caps.get('events') if isinstance(caps, dict) else None
    if not isinstance(events, dict):
        return False
    return bool(events.get('transport') or any(events.get(k) for k in ('motion', 'linecross', 'intrusion', 'tamper')))


def _redis():
    from server.service.token import get_redis
    return get_redis()


def _stop_key(camera_id):
    return '%s:sub:%s:stop' % (config.REDIS_KEY_PREFIX, camera_id)


def _lock_key(camera_id):
    return '%s:sub:%s:lock' % (config.REDIS_KEY_PREFIX, camera_id)


@app.task(name='server.task.list.event_subscription.supervise_subscriptions')
@celery_use_db()
def supervise_subscriptions():
    """Every 30s: ensure each event-capable camera has a running subscription."""
    try:
        redis = _redis()
    except Exception:
        return 0
    started = 0
    for camera in Camera.get_all_enabled():
        if not _is_event_capable(camera):
            continue
        if redis.exists(_lock_key(camera.id)):
            continue   # already running
        run_subscription.apply_async(args=[str(camera.id)], queue='subs')
        started += 1
    if started:
        logger.info('supervise_subscriptions: started %d', started)
    return started


@app.task(name='server.task.list.event_subscription.run_subscription', bind=True)
@celery_use_db()
def run_subscription(self, camera_id):
    from server.driver.event_base import make_event_source
    from server.service import event_pipeline

    camera_id = int(camera_id)
    redis = _redis()
    worker_id = self.request.id or str(time.time())
    if not redis.set(_lock_key(camera_id), worker_id, nx=True, ex=LOCK_TTL):
        return 'already_running'
    redis.delete(_stop_key(camera_id))

    camera = Camera.get_by_id(camera_id)
    source = make_event_source(camera)
    CameraSubscription.upsert(camera_id, protocol=source.source_name, state='connecting')
    try:
        source.open()
        CameraSubscription.upsert(camera_id, protocol=source.source_name, state='active')
        while not redis.exists(_stop_key(camera_id)):
            now_ms = int(time.time() * 1000)
            if source.needs_renew_at and now_ms >= source.needs_renew_at - 60_000:
                source.renew()
            batch = source.poll(POLL_TIMEOUT)
            redis.set(_lock_key(camera_id), worker_id, ex=LOCK_TTL)  # renew lease
            CameraSubscription.upsert(camera_id, protocol=source.source_name, state='active',
                                      last_event_ts=utcnow())
            for raw in batch:
                try:
                    event_pipeline.handle(camera, raw, source.source_name)
                except Exception:
                    logger.exception('pipeline error camera=%s', camera_id)
                    db.session.rollback()
            if not source.healthy:
                break
    except Exception as e:
        logger.warning('subscription loop ended camera=%s: %s', camera_id, e)
        CameraSubscription.upsert(camera_id, protocol=source.source_name, state='error', last_error=str(e)[:512])
    finally:
        source.close()
        redis.delete(_lock_key(camera_id))
        CameraSubscription.upsert(camera_id, protocol=source.source_name, state='stopped')
    return 'stopped'
