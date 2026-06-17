import datetime
import os
import warnings

from sqlalchemy import BigInteger, Column, DateTime, create_engine, exc
from sqlalchemy import event as sa_event  # aliased — server.model.event submodule shadows it
from sqlalchemy.dialects.mysql import BIGINT as MYSQL_BIGINT
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME
from sqlalchemy.orm import Session, declarative_base, declared_attr, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool

from server.util.snowflake import generate_snowflake_id

# ── Time policy (PLAN §12.1): store UTC DATETIME(3); display KST ─────────────
UTC = datetime.timezone.utc
KST = datetime.timezone(datetime.timedelta(hours=+9), 'KST')

# Millisecond-precision datetime. MySQL -> DATETIME(3); other dialects (sqlite in
# tests) -> plain DATETIME. Shared (stateless) instance, reused across columns.
DateTime3 = DateTime().with_variant(MYSQL_DATETIME(fsp=3), 'mysql')

# Snowflake-valued id columns. MySQL -> BIGINT UNSIGNED (PLAN §4.0); sqlite -> BIGINT.
# Used for PKs, audit columns, and all logical *_id references so create_all() and
# migrations/0000_init.sql produce identical schema.
BigIntId = BigInteger().with_variant(MYSQL_BIGINT(unsigned=True), 'mysql')


def utcnow() -> datetime.datetime:
    """Naive UTC wall clock. MySQL DATETIME has no tz, so we store/compare naive
    UTC everywhere; `to_epoch_ms` treats naive values as UTC on the way out."""
    return datetime.datetime.now(UTC).replace(tzinfo=None)


class DefaultBase:
    @classmethod
    @declared_attr
    def __tablename__(cls):
        return cls.__name__

    def __repr__(self):
        return '<%s (id=%s)>' % (type(self).__name__, getattr(self, 'id', None))


BaseDB = declarative_base(cls=DefaultBase)


# ── Common mixins (every domain table inherits these) ────────────────────────
class SnowflakeMixin:
    """Application-generated BIGINT UNSIGNED PK (no autoincrement)."""
    id = Column(BigIntId, primary_key=True, autoincrement=False, default=generate_snowflake_id)


class TimestampMixin:
    """UTC millisecond timestamps + soft delete."""
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime3, nullable=True, index=True)


class AuditMixin:
    """Who created / last updated the row (logical reference, no FK)."""
    created_by_id = Column(BigIntId, nullable=True)
    last_updated_by_id = Column(BigIntId, nullable=True)


def to_epoch_ms(dt: datetime.datetime | None) -> int | None:
    """Serialize a stored (UTC) datetime to epoch milliseconds for the API."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def add_engine_pidguard(engine):
    """Force reconnect if a connection is shared into a forked sub-process."""

    @sa_event.listens_for(engine, 'connect')
    def connect(dbapi_connection, connection_record):
        connection_record.info['pid'] = os.getpid()

    @sa_event.listens_for(engine, 'checkout')
    def checkout(dbapi_connection, connection_record, connection_proxy):
        pid = os.getpid()
        if connection_record.info['pid'] != pid:
            warnings.warn(
                'Parent process %(orig)s forked (%(newproc)s) with an open '
                'database connection, which is being discarded and recreated.' %
                {'newproc': pid, 'orig': connection_record.info['pid']})
            connection_record.connection = connection_proxy.connection = None
            raise exc.DisconnectionError(
                'Connection record belongs to pid %s, attempting to check out in pid %s' %
                (connection_record.info['pid'], pid)
            )


class DataAccessLayer:
    engine = None
    conn_string = None
    session: Session = None
    metadata = None
    session_options = dict(autocommit=False, autoflush=False, expire_on_commit=False)

    def __init__(self, session_options=None):
        if session_options:
            self.session_options = session_options

    def db_init(self, conn_string, base, engine_options=None, session_options=None):
        if not engine_options:
            engine_options = dict()
        _session_options = session_options or self.session_options

        self.conn_string = conn_string
        self.metadata = base.metadata
        if engine_options.get('poolclass') == NullPool:
            _engine_options = {
                'echo': engine_options.get('echo', False),
                'poolclass': NullPool,
                'isolation_level': engine_options.get('isolation_level'),
            }
        else:
            _engine_options = {
                'echo': engine_options.get('echo', False),
                'pool_size': engine_options.get('pool_size', 5),
                'max_overflow': engine_options.get('max_overflow', 40),
                'pool_recycle': engine_options.get('pool_recycle', 3600),
                'pool_timeout': engine_options.get('pool_timeout', 600),
                'pool_pre_ping': engine_options.get('pool_pre_ping', True),
                'isolation_level': engine_options.get('isolation_level'),
            }
        self.engine = create_engine(conn_string, **_engine_options)
        add_engine_pidguard(self.engine)
        self.session = scoped_session(sessionmaker(bind=self.engine, **_session_options))

    def create_all(self):
        self.metadata.reflect(self.engine)
        self.metadata.create_all(self.engine)

    def dispose(self):
        self.engine.dispose()


db = DataAccessLayer()

# Register all models (import order = table creation order; FK is logical so order is loose).
import server.model.role          # noqa: E402,F401
import server.model.user          # noqa: E402,F401
import server.model.permission    # noqa: E402,F401
import server.model.refresh_token  # noqa: E402,F401
import server.model.audit_log     # noqa: E402,F401
import server.model.camera        # noqa: E402,F401
import server.model.stream        # noqa: E402,F401
import server.model.disk          # noqa: E402,F401
import server.model.storage_policy  # noqa: E402,F401
import server.model.dashboard     # noqa: E402,F401
import server.model.dashboard_acl  # noqa: E402,F401
import server.model.ptz_preset    # noqa: E402,F401
import server.model.segment       # noqa: E402,F401
import server.model.recording     # noqa: E402,F401
import server.model.export_job    # noqa: E402,F401
import server.model.recorder_health  # noqa: E402,F401
import server.model.event         # noqa: E402,F401
import server.model.event_policy  # noqa: E402,F401
import server.model.schedule      # noqa: E402,F401
import server.model.timelapse_job  # noqa: E402,F401
import server.model.event_outbox  # noqa: E402,F401
import server.model.camera_subscription  # noqa: E402,F401
import server.model.detection     # noqa: E402,F401
import server.model.detection_zone  # noqa: E402,F401
import server.model.object_trigger  # noqa: E402,F401
import server.model.ai_node        # noqa: E402,F401
import server.model.detection_assignment  # noqa: E402,F401
import server.model.ai_settings    # noqa: E402,F401
import server.model.rule           # noqa: E402,F401
import server.model.rule_execution  # noqa: E402,F401
import server.model.action_target  # noqa: E402,F401
import server.model.webhook_endpoint  # noqa: E402,F401
import server.model.monitor        # noqa: E402,F401
import server.model.pairing_code   # noqa: E402,F401
import server.model.notification_subscription  # noqa: E402,F401
import server.model.push_subscription  # noqa: E402,F401
import server.model.notification   # noqa: E402,F401
import server.model.api_token      # noqa: E402,F401
import server.model.setting       # noqa: E402,F401
# P6
import server.model.feature_flag  # noqa: E402,F401
import server.model.bookmark      # noqa: E402,F401
import server.model.share_link    # noqa: E402,F401
import server.model.embedding     # noqa: E402,F401
import server.model.privacy_mask  # noqa: E402,F401
import server.model.archive_target  # noqa: E402,F401
import server.model.archive_job   # noqa: E402,F401
import server.model.site_map      # noqa: E402,F401
import server.model.counting      # noqa: E402,F401
import server.model.edge_import_job  # noqa: E402,F401
import server.model.audio_detection  # noqa: E402,F401
import server.model.plate_read     # noqa: E402,F401
import server.model.plate_list     # noqa: E402,F401
import server.model.face_identity  # noqa: E402,F401
import server.model.face_observation  # noqa: E402,F401
import server.model.federation_member  # noqa: E402,F401
import server.model.federation_camera  # noqa: E402,F401
import server.model.turn_config     # noqa: E402,F401
import server.model.door            # noqa: E402,F401
import server.model.access_credential  # noqa: E402,F401
import server.model.access_event    # noqa: E402,F401
import server.model.map_config       # noqa: E402,F401
