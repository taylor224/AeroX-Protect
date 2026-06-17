"""Detection include/ignore zones (PLAN P4 §4.2). Per-camera polygons in normalized
0–1 coords; detector filters by include∪ / ignore∖, ingest attributes detections to a
zone by bottom-center point-in-polygon (priority/area)."""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, SmallInteger, String

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db

KIND_INCLUDE = 'include'   # detect only inside (union of includes; none = whole frame)
KIND_IGNORE = 'ignore'     # drop detections inside
KINDS = (KIND_INCLUDE, KIND_IGNORE)


class DetectionZone(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'detection_zones'

    camera_id = Column(BigIntId, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    kind = Column(String(16), nullable=False, default=KIND_INCLUDE)
    polygon = Column(JSON, nullable=False)             # [[x,y],...] normalized 0–1, ≥3 pts
    label_filter = Column(JSON, nullable=True)         # class whitelist (NULL=all)
    color = Column(String(9), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(SmallInteger, nullable=False, default=0)

    @classmethod
    def get_by_id(cls, zone_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == zone_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_for_camera(cls, camera_id: int, enabled_only: bool = True) -> list[Self]:
        q = db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None))
        if enabled_only:
            q = q.filter(cls.enabled.is_(True))
        return q.order_by(cls.priority.desc(), cls.id.asc()).all()

    @classmethod
    def create(cls, camera_id: int, data: dict, actor_id=None) -> Self:
        z = cls()
        z.camera_id = camera_id
        cls._apply(z, data)
        z.created_by_id = actor_id
        z.last_updated_by_id = actor_id
        db.session.add(z)
        db.session.commit()
        return z

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
    def _apply(z, data):
        for f in ('name', 'kind', 'polygon', 'label_filter', 'color', 'enabled', 'priority'):
            if f in data and data[f] is not None:
                setattr(z, f, data[f])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'name': self.name,
            'kind': self.kind,
            'polygon': self.polygon,
            'label_filter': self.label_filter,
            'color': self.color,
            'enabled': bool(self.enabled),
            'priority': self.priority,
        }
