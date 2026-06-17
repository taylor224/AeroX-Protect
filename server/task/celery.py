import functools

import sentry_sdk
from celery import Celery, signals
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sqlalchemy import NullPool
from sqlalchemy.exc import OperationalError, PendingRollbackError

import config
from server.model import BaseDB, db
from server.task import celeryconfig

app = Celery(
    'axp',
    include=[
        'server.task.list.maintenance',
        'server.task.list.camera_health',
        'server.task.list.retention',
        'server.task.list.disk_scan',
        'server.task.list.segment_sweep',
        'server.task.list.transcode',
        'server.task.list.archive',
        'server.task.list.edge_import',
        'server.task.list.federation_sync',
        'server.task.list.recording_autoclose',
        'server.task.list.thumbnail',
        'server.task.list.event_subscription',
        'server.task.list.event_maintenance',
        'server.task.list.timelapse',
        'server.task.list.ai_supervise',
        'server.task.list.detection_linker',
        'server.task.list.detection_retention',
        'server.task.list.ai_crop_thumb',
        'server.task.list.outbox_consumer',
        'server.task.list.schedule_trigger',
        'server.task.list.pairing_code_cleanup',
        'server.task.list.p5_retention',
    ],
)
app.autodiscover_tasks()
app.config_from_object(celeryconfig)
app.conf.timezone = 'UTC'
app.conf.enable_utc = True


@signals.celeryd_init.connect
def init_sentry(**_kwargs):
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        integrations=[CeleryIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=False,
    )


def celery_use_db():
    """Per-task DB session lifecycle (NullPool — no cross-fork connection reuse)."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            db.db_init(config.DATABASE_URI, BaseDB, engine_options={
                'pool_size': 0,
                'pool_recycle': 0,
                'pool_timeout': 0,
                'pool_pre_ping': True,
                'poolclass': NullPool,
            })
            try:
                return func(*args, **kwargs)
            except PendingRollbackError:
                db.session.rollback()
                db.session.close_all()
            except OperationalError:
                db.session.close_all()
            finally:
                db.session.close_all()
        return wrapper
    return decorator
