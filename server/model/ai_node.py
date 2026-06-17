"""Distributed inference node registry (PLAN P4 §4.4). builtin (server's own detector)
+ remote (joined external machines), same protocol. Authority for load = capacity +
detection_assignments. Heartbeat staleness → offline → reassign."""
import uuid as uuid_lib
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Boolean, Column, SmallInteger, String

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

KIND_BUILTIN = 'builtin'
KIND_REMOTE = 'remote'

STATUS_ONLINE = 'online'
STATUS_DEGRADED = 'degraded'
STATUS_OFFLINE = 'offline'
STATUS_DRAINING = 'draining'
STATUS_DISABLED = 'disabled'


class AiNode(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'ai_nodes'

    uuid = Column(String(32), nullable=False, unique=True)
    name = Column(String(80), nullable=False)
    kind = Column(String(16), nullable=False, default=KIND_REMOTE)
    endpoint = Column(String(255), nullable=True)
    status = Column(String(16), nullable=False, default=STATUS_OFFLINE)
    enabled = Column(Boolean, nullable=False, default=True)
    gpu = Column(Boolean, nullable=False, default=False)
    gpu_name = Column(String(80), nullable=True)
    capacity = Column(SmallInteger, nullable=False, default=0)
    capabilities = Column(JSON, nullable=True)
    bench = Column(JSON, nullable=True)
    version = Column(String(40), nullable=True)
    assigned_count = Column(SmallInteger, nullable=False, default=0)
    last_heartbeat_ts = Column(DateTime3, nullable=True)
    token_jti = Column(String(36), nullable=True)
    last_seen_ip = Column(String(64), nullable=True)
    last_error = Column(String(512), nullable=True)

    @classmethod
    def get_by_id(cls, node_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == node_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_uuid(cls, node_uuid: str) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == node_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_builtin(cls) -> Self | None:
        return db.session.query(cls).filter(cls.kind == KIND_BUILTIN, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(cls.created_at.asc()).all()

    @classmethod
    def schedulable(cls) -> list[Self]:
        """enabled & online & not draining/disabled — eligible for assignment."""
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True), cls.status == STATUS_ONLINE
        ).order_by(cls.gpu.desc(), cls.capacity.desc()).all()

    @classmethod
    def stale(cls, older_than: datetime) -> list[Self]:
        """online/degraded nodes whose last heartbeat is older than the threshold."""
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.status.in_([STATUS_ONLINE, STATUS_DEGRADED]),
            cls.last_heartbeat_ts < older_than,
        ).all()

    @classmethod
    def create(cls, name: str, kind: str = KIND_REMOTE, actor_id=None, node_uuid: str | None = None) -> Self:
        n = cls()
        n.uuid = node_uuid or uuid_lib.uuid4().hex
        n.name = name
        n.kind = kind
        n.created_by_id = actor_id
        n.last_updated_by_id = actor_id
        db.session.add(n)
        db.session.commit()
        return n

    def update(self, **fields) -> Self:
        for k, v in fields.items():
            setattr(self, k, v)
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        self.status = STATUS_DISABLED
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'uuid': self.uuid,
            'name': self.name,
            'kind': self.kind,
            'endpoint': self.endpoint,
            'status': self.status,
            'enabled': bool(self.enabled),
            'gpu': bool(self.gpu),
            'gpu_name': self.gpu_name,
            'capacity': self.capacity,
            'capabilities': self.capabilities,
            'bench': self.bench,
            'version': self.version,
            'assigned_count': self.assigned_count,
            'last_heartbeat_ts': to_epoch_ms(self.last_heartbeat_ts),
            'last_error': self.last_error,
            'created_at': to_epoch_ms(self.created_at),
        }
