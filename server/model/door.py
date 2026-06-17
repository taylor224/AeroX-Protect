"""Access-controlled door (PLAN P10). A door has a controller (relay/reader) that the
access service drives to unlock on a granted swipe. `access_group` gates which credentials
may open it; `require_pin` adds a PIN factor. Controller details live in `controller_config`
(host/output for vendor_http relays). Soft-deleted + audited.
"""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, String

from server.model import (
    AuditMixin,
    BaseDB,
    BigIntId,
    DateTime3,
    SnowflakeMixin,
    TimestampMixin,
    db,
    to_epoch_ms,
    utcnow,
)

CONTROLLER_MOCK = 'mock'
CONTROLLER_VENDOR_HTTP = 'vendor_http'
CONTROLLER_ONVIF = 'onvif_relay'
CONTROLLERS = (CONTROLLER_MOCK, CONTROLLER_VENDOR_HTTP, CONTROLLER_ONVIF)

STATE_LOCKED = 'locked'
STATE_UNLOCKED = 'unlocked'


class Door(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'doors'

    name = Column(String(120), nullable=False)
    location = Column(String(200), nullable=True)
    controller_type = Column(String(16), nullable=False, default=CONTROLLER_MOCK)
    controller_config = Column(JSON, nullable=True)         # {host, output_id, username, …}
    lock_state = Column(String(12), nullable=False, default=STATE_LOCKED)
    camera_id = Column(BigIntId, nullable=True)             # linked camera (video verification)
    access_group = Column(String(64), nullable=False, default='default')   # 'public' = any valid card
    require_pin = Column(Boolean, nullable=False, default=False)
    unlock_seconds = Column(Integer, nullable=False, default=5)
    unlocked_at = Column(DateTime3, nullable=True)          # last momentary-unlock pulse
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, door_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == door_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(cls.name.asc()).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        d = cls()
        d.name = data['name']
        d.location = data.get('location')
        d.controller_type = data.get('controller_type') or CONTROLLER_MOCK
        d.controller_config = data.get('controller_config')
        d.camera_id = data.get('camera_id')
        d.access_group = data.get('access_group') or 'default'
        d.require_pin = bool(data.get('require_pin'))
        d.unlock_seconds = int(data.get('unlock_seconds') or 5)
        d.created_by_id = d.last_updated_by_id = actor_id
        db.session.add(d)
        db.session.commit()
        return d

    def modify(self, data: dict, actor_id=None) -> Self:
        for f in ('name', 'location', 'controller_type', 'controller_config', 'camera_id',
                  'access_group', 'unlock_seconds'):
            if f in data and data[f] is not None:
                setattr(self, f, data[f])
        for f in ('require_pin', 'enabled'):
            if f in data:
                setattr(self, f, bool(data[f]))
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def set_state(self, state: str):
        self.lock_state = state
        if state == STATE_LOCKED:
            self.unlocked_at = None
        db.session.add(self)
        db.session.commit()

    def mark_unlocked(self):
        """Record a momentary unlock pulse. `effective_lock_state` auto-relocks it after
        `unlock_seconds` (read-time), so the DB never reports a momentary door open forever."""
        self.lock_state = STATE_UNLOCKED
        self.unlocked_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def effective_lock_state(self) -> str:
        """lock_state, but a momentary pulse reverts to 'locked' once its window elapses."""
        if self.lock_state == STATE_UNLOCKED and self.unlocked_at is not None:
            if (utcnow() - self.unlocked_at).total_seconds() >= (self.unlock_seconds or 5):
                return STATE_LOCKED
        return self.lock_state

    def soft_delete(self, actor_id=None):
        self.deleted_at = utcnow()
        self.enabled = False
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'name': self.name,
            'location': self.location,
            'controller_type': self.controller_type,
            'controller_config': self.controller_config,
            'lock_state': self.effective_lock_state(),
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'access_group': self.access_group,
            'require_pin': bool(self.require_pin),
            'unlock_seconds': self.unlock_seconds,
            'enabled': bool(self.enabled),
            'updated_at': to_epoch_ms(self.updated_at),
        }
