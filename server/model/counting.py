"""Counting lines / regions + time-series stats (PLAN P6 A2/A3). A `line` counts track
crossings (in/out); a `region` measures occupancy and, with `loiter_threshold_s`, emits
loitering. Geometry is normalized 0–1 (P3 region convention). Stats are minute-bucketed.
"""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, BigInteger, Boolean, Column, Integer, String, and_, asc

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

KIND_LINE = 'line'        # geometry = [[x1,y1],[x2,y2]] — crossing in/out
KIND_REGION = 'region'    # geometry = [[x,y],...] polygon — occupancy + loitering
KINDS = (KIND_LINE, KIND_REGION)


class CountingLine(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'counting_lines'

    camera_id = Column(BigIntId, nullable=False, index=True)
    name = Column(String(80), nullable=False)
    kind = Column(String(16), nullable=False, default=KIND_LINE)
    geometry = Column(JSON, nullable=False)
    class_filter = Column(JSON, nullable=True)               # ['person','car'] | NULL=all
    direction_labels = Column(JSON, nullable=True)           # {'in':'들어옴','out':'나감'}
    loiter_threshold_s = Column(Integer, nullable=True)      # region → loitering when dwell ≥
    occupancy_threshold = Column(Integer, nullable=True)     # region → occupancy event when >
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, line_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == line_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_for_camera(cls, camera_id: int, enabled_only: bool = True) -> list[Self]:
        q = db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None))
        if enabled_only:
            q = q.filter(cls.enabled.is_(True))
        return q.order_by(asc(cls.id)).all()

    @classmethod
    def create(cls, camera_id: int, data: dict, actor_id=None) -> Self:
        c = cls()
        c.camera_id = camera_id
        cls._apply(c, data)
        c.created_by_id = actor_id
        c.last_updated_by_id = actor_id
        db.session.add(c)
        db.session.commit()
        return c

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
    def _apply(c, data: dict):
        for f in ('name', 'kind', 'geometry', 'class_filter', 'direction_labels',
                  'loiter_threshold_s', 'occupancy_threshold', 'enabled'):
            if f in data and data[f] is not None:
                setattr(c, f, data[f])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'name': self.name,
            'kind': self.kind,
            'geometry': self.geometry,
            'class_filter': self.class_filter,
            'direction_labels': self.direction_labels,
            'loiter_threshold_s': self.loiter_threshold_s,
            'occupancy_threshold': self.occupancy_threshold,
            'enabled': bool(self.enabled),
        }


class CountingStat(SnowflakeMixin, BaseDB):
    """Minute-bucketed counts/occupancy. Upserted per (camera, line, bucket, label)."""
    __tablename__ = 'counting_stats'

    camera_id = Column(BigIntId, nullable=False, index=True)
    line_id = Column(BigIntId, nullable=False, index=True)
    bucket_ts = Column(DateTime3, nullable=False, index=True)
    in_count = Column(Integer, nullable=False, default=0)
    out_count = Column(Integer, nullable=False, default=0)
    occupancy = Column(Integer, nullable=False, default=0)
    label = Column(String(32), nullable=True)

    @staticmethod
    def _bucket(ts: datetime) -> datetime:
        return ts.replace(second=0, microsecond=0)

    @classmethod
    def record(cls, camera_id, line_id, ts: datetime, in_delta=0, out_delta=0,
               occupancy=None, label=None):
        bucket = cls._bucket(ts)
        row = (db.session.query(cls)
               .filter(cls.camera_id == camera_id, cls.line_id == line_id,
                       cls.bucket_ts == bucket, cls.label == label)
               .first())
        if not row:
            row = cls()
            row.camera_id = camera_id
            row.line_id = line_id
            row.bucket_ts = bucket
            row.label = label
        row.in_count = (row.in_count or 0) + in_delta
        row.out_count = (row.out_count or 0) + out_delta
        if occupancy is not None:
            row.occupancy = max(row.occupancy or 0, occupancy)
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def query(cls, camera_id, line_id=None, start: datetime | None = None, end: datetime | None = None):
        q = db.session.query(cls).filter(cls.camera_id == camera_id)
        if line_id:
            q = q.filter(cls.line_id == line_id)
        if start is not None and end is not None:
            q = q.filter(and_(cls.bucket_ts >= start, cls.bucket_ts <= end))
        return q.order_by(asc(cls.bucket_ts)).limit(2000).all()

    def to_dict(self) -> dict:
        return {
            'line_id': str(self.line_id),
            'bucket_ts': to_epoch_ms(self.bucket_ts),
            'in_count': self.in_count,
            'out_count': self.out_count,
            'occupancy': self.occupancy,
            'label': self.label,
        }
