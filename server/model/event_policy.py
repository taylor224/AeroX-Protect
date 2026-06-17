from typing import Self

from sqlalchemy import Boolean, Column, SmallInteger, String, and_, or_

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db

ACTION_RECORD = 'record'
ACTION_DISCARD = 'discard'
ACTION_TIMELAPSE = 'timelapse'
ACTION_NOTIFY_ONLY = 'notify_only'
ACTIONS = (ACTION_RECORD, ACTION_DISCARD, ACTION_TIMELAPSE, ACTION_NOTIFY_ONLY)


class EventPolicy(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'event_policies'

    camera_id = Column(BigIntId, nullable=True, index=True)   # NULL = global default
    event_type = Column(String(32), nullable=False)           # normalized type or '*'
    subtype = Column(String(48), nullable=True)
    action = Column(String(16), nullable=False)
    pre_buffer_s = Column(SmallInteger, nullable=False, default=5)
    post_buffer_s = Column(SmallInteger, nullable=False, default=10)
    cooldown_s = Column(SmallInteger, nullable=False, default=10)
    min_score = Column(SmallInteger, nullable=True)
    retention_class = Column(String(24), nullable=True)
    notify = Column(Boolean, nullable=False, default=True)
    active_schedule_id = Column(BigIntId, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, policy_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == policy_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_candidates(cls, camera_id: int, event_type: str) -> list[Self]:
        """All enabled policies that could apply to (camera, type) — resolver ranks them."""
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True),
            or_(cls.camera_id == camera_id, cls.camera_id.is_(None)),
            or_(cls.event_type == event_type, cls.event_type == '*'),
        ).all()

    @classmethod
    def list_for(cls, camera_id: int | None) -> list[Self]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if camera_id is not None:
            q = q.filter(or_(cls.camera_id == camera_id, cls.camera_id.is_(None)))
        return q.order_by(cls.camera_id.is_(None).desc(), cls.event_type.asc()).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        p = cls()
        cls._apply(p, data)
        p.created_by_id = actor_id
        p.last_updated_by_id = actor_id
        db.session.add(p)
        db.session.commit()
        return p

    def modify(self, data: dict, actor_id=None) -> Self:
        self._apply(self, data)
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def _apply(p, data):
        for field in ('camera_id', 'event_type', 'subtype', 'action', 'pre_buffer_s', 'post_buffer_s',
                      'cooldown_s', 'min_score', 'retention_class', 'notify', 'active_schedule_id', 'enabled'):
            if field in data and data[field] is not None:
                setattr(p, field, data[field])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'event_type': self.event_type,
            'subtype': self.subtype,
            'action': self.action,
            'pre_buffer_s': self.pre_buffer_s,
            'post_buffer_s': self.post_buffer_s,
            'cooldown_s': self.cooldown_s,
            'min_score': self.min_score,
            'retention_class': self.retention_class,
            'notify': bool(self.notify),
            'enabled': bool(self.enabled),
        }
