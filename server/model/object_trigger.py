"""Object-detection → event trigger rules (PLAN P4 §4.3). Promotes a detection/track to
a P3 event(type='object'); P3 policy then decides record/notify. camera_id NULL = global."""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, SmallInteger, String, or_

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db


class ObjectTrigger(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'object_triggers'

    camera_id = Column(BigIntId, nullable=True, index=True)   # NULL = global default
    name = Column(String(80), nullable=False)
    labels = Column(JSON, nullable=False)                     # ["person"] / ["car","truck"]
    zone_id = Column(BigIntId, nullable=True)
    min_confidence = Column(SmallInteger, nullable=False, default=50)
    min_dwell_ms = Column(Integer, nullable=False, default=0)
    require_zone_entry = Column(Boolean, nullable=False, default=False)
    min_count = Column(SmallInteger, nullable=False, default=1)
    cooldown_s = Column(SmallInteger, nullable=False, default=30)
    debounce_per_track = Column(Boolean, nullable=False, default=True)
    event_subtype = Column(String(48), nullable=True)
    action_hint = Column(String(16), nullable=True)          # record/notify_only (P3 fallback)
    notify = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=True)
    active_schedule_id = Column(BigIntId, nullable=True)

    @classmethod
    def get_by_id(cls, trigger_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == trigger_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_candidates(cls, camera_id: int) -> list[Self]:
        """Enabled triggers for a camera (camera-specific + global), camera-first."""
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True),
            or_(cls.camera_id == camera_id, cls.camera_id.is_(None)),
        ).order_by(cls.camera_id.is_(None).asc()).all()   # camera-specific first

    @classmethod
    def list_for(cls, camera_id: int | None) -> list[Self]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if camera_id is not None:
            q = q.filter(or_(cls.camera_id == camera_id, cls.camera_id.is_(None)))
        return q.order_by(cls.camera_id.is_(None).desc(), cls.name.asc()).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        t = cls()
        cls._apply(t, data)
        t.created_by_id = actor_id
        t.last_updated_by_id = actor_id
        db.session.add(t)
        db.session.commit()
        return t

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
    def _apply(t, data):
        for f in ('camera_id', 'name', 'labels', 'zone_id', 'min_confidence', 'min_dwell_ms',
                  'require_zone_entry', 'min_count', 'cooldown_s', 'debounce_per_track',
                  'event_subtype', 'action_hint', 'notify', 'enabled', 'active_schedule_id'):
            if f in data and data[f] is not None:
                setattr(t, f, data[f])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'name': self.name,
            'labels': self.labels,
            'zone_id': str(self.zone_id) if self.zone_id else None,
            'min_confidence': self.min_confidence,
            'min_dwell_ms': self.min_dwell_ms,
            'require_zone_entry': bool(self.require_zone_entry),
            'min_count': self.min_count,
            'cooldown_s': self.cooldown_s,
            'debounce_per_track': bool(self.debounce_per_track),
            'event_subtype': self.event_subtype,
            'action_hint': self.action_hint,
            'notify': bool(self.notify),
            'enabled': bool(self.enabled),
            'active_schedule_id': str(self.active_schedule_id) if self.active_schedule_id else None,
        }
