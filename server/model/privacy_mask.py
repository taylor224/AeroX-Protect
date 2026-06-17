"""Privacy masks (PLAN P6 L2). Per-camera polygons (normalized 0–1, P3 region convention)
that hide a region. MVP mode = `server_render`: the client overlays the polygon on live/
playback (managers may reveal). `camera_osd` (driver push) and `burn_export` (export burn)
are reserved. Mirrors detection_zone's shape/CRUD.
"""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, String

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db

MODE_SERVER_RENDER = 'server_render'
MODE_CAMERA_OSD = 'camera_osd'      # reserved — driver pushes OSD mask (irreversible)
MODE_BURN_EXPORT = 'burn_export'    # reserved — burned into exports only
MODES = (MODE_SERVER_RENDER, MODE_CAMERA_OSD, MODE_BURN_EXPORT)


class PrivacyMask(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'privacy_masks'

    camera_id = Column(BigIntId, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    polygon = Column(JSON, nullable=False)             # [[x,y],...] normalized 0–1, ≥3 pts
    mode = Column(String(16), nullable=False, default=MODE_SERVER_RENDER)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, mask_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == mask_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_for_camera(cls, camera_id: int, enabled_only: bool = False) -> list[Self]:
        q = db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None))
        if enabled_only:
            q = q.filter(cls.enabled.is_(True))
        return q.order_by(cls.id.asc()).all()

    @classmethod
    def create(cls, camera_id: int, data: dict, actor_id=None) -> Self:
        m = cls()
        m.camera_id = camera_id
        cls._apply(m, data)
        m.created_by_id = actor_id
        m.last_updated_by_id = actor_id
        db.session.add(m)
        db.session.commit()
        return m

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
    def _apply(m, data: dict):
        for f in ('name', 'polygon', 'mode', 'enabled'):
            if f in data and data[f] is not None:
                setattr(m, f, data[f])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'name': self.name,
            'polygon': self.polygon,
            'mode': self.mode,
            'enabled': bool(self.enabled),
        }
