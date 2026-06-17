"""Monitor client (PLAN P5 §4.5): a kiosk display bound to a dashboard, paired via a 60s
numeric code, driven by an audience=monitor scoped JWT. token_version bumps invalidate all
issued tokens (revoke / dashboard change)."""
import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, String

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms, utcnow

STATUS_UNPAIRED = 'unpaired'
STATUS_PENDING = 'pending'
STATUS_PAIRED = 'paired'
STATUS_REVOKED = 'revoked'


class Monitor(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'monitors'

    uuid = Column(String(32), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    dashboard_id = Column(BigIntId, nullable=False)
    rotation = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default=STATUS_UNPAIRED)
    token_version = Column(Integer, nullable=False, default=0)
    paired_at = Column(DateTime3, nullable=True)
    last_seen_at = Column(DateTime3, nullable=True)
    last_ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    device_label = Column(String(120), nullable=True)
    settings = Column(JSON, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, monitor_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == monitor_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_uuid(cls, monitor_uuid) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == monitor_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(cls.created_at.desc()).all()

    @classmethod
    def create(cls, name: str, dashboard_id: int, actor_id=None, **extra) -> Self:
        m = cls()
        m.uuid = uuid_lib.uuid4().hex
        m.name = name
        m.dashboard_id = dashboard_id
        m.settings = extra.get('settings')
        m.device_label = extra.get('device_label')
        m.created_by_id = actor_id
        m.last_updated_by_id = actor_id
        db.session.add(m)
        db.session.commit()
        return m

    def update(self, **fields) -> Self:
        for k, v in fields.items():
            setattr(self, k, v)
        db.session.add(self)
        db.session.commit()
        return self

    def bump_token_version(self):
        self.token_version = (self.token_version or 0) + 1
        db.session.add(self)
        db.session.commit()

    def mark_paired(self, ip=None, ua=None):
        self.status = STATUS_PAIRED
        self.paired_at = utcnow()
        self.last_seen_at = utcnow()
        self.last_ip = ip
        self.user_agent = ua
        db.session.add(self)
        db.session.commit()

    def soft_delete(self):
        self.deleted_at = utcnow()
        self.status = STATUS_REVOKED
        self.token_version = (self.token_version or 0) + 1
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'uuid': self.uuid, 'name': self.name,
            'dashboard_id': str(self.dashboard_id), 'status': self.status, 'rotation': self.rotation,
            'paired_at': to_epoch_ms(self.paired_at), 'last_seen_at': to_epoch_ms(self.last_seen_at),
            'last_ip': self.last_ip, 'device_label': self.device_label, 'settings': self.settings,
            'enabled': bool(self.enabled), 'created_at': to_epoch_ms(self.created_at),
        }
