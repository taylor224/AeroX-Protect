"""Maps + camera markers (PLAN P6 L6). A map is either a geo map (OSM tiles) or a floorplan
(background image). Markers place a camera on it: for geo, (x,y)=(lng,lat); for floorplan,
(x,y)=normalized 0–1 over the image. Click a marker → live. Mirrors the simple CRUD pattern.
"""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Float, String, asc

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db

KIND_GEO = 'geo'              # leaflet OSM tiles, marker = (lng, lat)
KIND_FLOORPLAN = 'floorplan'  # background image, marker = normalized (x, y)
KINDS = (KIND_GEO, KIND_FLOORPLAN)


class SiteMap(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'maps'

    name = Column(String(120), nullable=False)
    kind = Column(String(16), nullable=False, default=KIND_GEO)
    image_url = Column(String(1000), nullable=True)        # floorplan background
    config = Column(JSON, nullable=True)                   # geo: {center_lat, center_lng, zoom}; floorplan: {w,h}
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, map_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == map_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(asc(cls.name)).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        m = cls()
        m.name = data['name']
        m.kind = data.get('kind') or KIND_GEO
        m.image_url = data.get('image_url')
        m.config = data.get('config') or {}
        m.enabled = data.get('enabled', True)
        m.created_by_id = actor_id
        m.last_updated_by_id = actor_id
        db.session.add(m)
        db.session.commit()
        return m

    def modify(self, data: dict, actor_id=None) -> Self:
        for f in ('name', 'kind', 'image_url', 'config', 'enabled'):
            if f in data and data[f] is not None:
                setattr(self, f, data[f])
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def to_dict(self, with_markers: bool = False) -> dict:
        d = {
            'id': str(self.id),
            'name': self.name,
            'kind': self.kind,
            'image_url': self.image_url,
            'config': self.config or {},
            'enabled': bool(self.enabled),
        }
        if with_markers:
            d['markers'] = [mk.to_dict() for mk in MapMarker.get_for_map(self.id)]
        return d


class MapMarker(SnowflakeMixin, TimestampMixin, BaseDB):
    __tablename__ = 'map_markers'

    map_id = Column(BigIntId, nullable=False, index=True)
    camera_id = Column(BigIntId, nullable=False)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    heading = Column(Float, nullable=True)
    label = Column(String(120), nullable=True)

    @classmethod
    def get_for_map(cls, map_id: int) -> list[Self]:
        return (db.session.query(cls)
                .filter(cls.map_id == map_id, cls.deleted_at.is_(None))
                .order_by(asc(cls.id)).all())

    @classmethod
    def replace_for_map(cls, map_id: int, markers: list[dict]):
        """Replace all markers for a map (hard delete old, insert new) — editor save."""
        db.session.query(cls).filter(cls.map_id == map_id).delete(synchronize_session=False)
        for mk in markers or []:
            row = cls()
            row.map_id = map_id
            row.camera_id = int(mk['camera_id'])
            row.x = float(mk['x'])
            row.y = float(mk['y'])
            row.heading = mk.get('heading')
            row.label = mk.get('label')
            db.session.add(row)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'x': self.x,
            'y': self.y,
            'heading': self.heading,
            'label': self.label,
        }
