from datetime import datetime
from typing import Self

from sqlalchemy import Column, String, or_

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms, utcnow

REASON_CONTINUOUS = 'continuous'
REASON_MANUAL = 'manual'
REASON_EVENT = 'event'        # P3
REASON_SCHEDULE = 'schedule'  # P3
REASON_EDGE = 'edge'          # P6 R6 — imported from camera SD (gap-fill)

CLASS_DEFAULT = 'default'
CLASS_PROTECTED = 'protected'
CLASS_EVENT = 'event'

PROTECTED_CLASSES = (CLASS_PROTECTED, CLASS_EVENT)


class Recording(SnowflakeMixin, TimestampMixin, BaseDB):
    """Logical recording interval — protection + export unit (PLAN P2 §4.4)."""
    __tablename__ = 'recordings'

    camera_id = Column(BigIntId, nullable=False)
    reason = Column(String(12), nullable=False)
    retention_class = Column(String(12), nullable=False, default=CLASS_DEFAULT)
    start_ts = Column(DateTime3, nullable=False)
    end_ts = Column(DateTime3, nullable=True)              # NULL = in progress (manual)
    planned_end_ts = Column(DateTime3, nullable=True)      # manual fixed-duration auto-stop
    created_by_id = Column(BigIntId, nullable=True)
    note = Column(String(500), nullable=True)

    @classmethod
    def get_by_id(cls, recording_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == recording_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_active_manual(cls, camera_id: int) -> Self | None:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.reason == REASON_MANUAL,
            cls.end_ts.is_(None), cls.deleted_at.is_(None)).first()

    @classmethod
    def get_protected_intervals(cls, camera_id: int) -> list[tuple[datetime, datetime]]:
        """[(start, end)] of protected recordings (end=now if in progress)."""
        rows = db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.retention_class.in_(PROTECTED_CLASSES),
            cls.deleted_at.is_(None)).all()
        now = utcnow()
        return [(r.start_ts, r.end_ts or now) for r in rows]

    @classmethod
    def has_active_recording(cls, camera_id: int) -> bool:
        """Any in-progress manual/event recording forcing the recorder on."""
        return db.session.query(cls.id).filter(
            cls.camera_id == camera_id, cls.end_ts.is_(None), cls.deleted_at.is_(None),
            or_(cls.reason == REASON_MANUAL, cls.reason == REASON_EVENT)).first() is not None

    @classmethod
    def list_for_camera(cls, camera_id: int, limit: int = 200) -> list[Self]:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.deleted_at.is_(None)).order_by(cls.start_ts.desc()).limit(limit).all()

    @classmethod
    def due_manual(cls, now: datetime, limit: int = 200) -> list[Self]:
        """Open manual recordings whose fixed duration has elapsed (auto-stop)."""
        return db.session.query(cls).filter(
            cls.reason == REASON_MANUAL, cls.end_ts.is_(None), cls.deleted_at.is_(None),
            cls.planned_end_ts.isnot(None), cls.planned_end_ts <= now).limit(limit).all()

    def set_protected(self, protected: bool):
        """P2 retention lock — protected recordings are exempt from age/quota cleanup."""
        self.retention_class = CLASS_PROTECTED if protected else CLASS_DEFAULT
        db.session.add(self)
        db.session.commit()

    @classmethod
    def find_overlapping(cls, camera_id: int, start: datetime, end: datetime, reason: str) -> Self | None:
        """An existing recording of `reason` overlapping [start, end] (for event coalescing)."""
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.reason == reason, cls.deleted_at.is_(None),
            cls.start_ts < end, or_(cls.end_ts.is_(None), cls.end_ts > start)
        ).order_by(cls.start_ts.asc()).first()

    def extend(self, start: datetime, end: datetime):
        if start < self.start_ts:
            self.start_ts = start
        if self.end_ts is None or end > self.end_ts:
            self.end_ts = end
        db.session.add(self)
        db.session.commit()

    @classmethod
    def create(cls, camera_id, reason, retention_class, start_ts, end_ts=None,
               created_by_id=None, note=None, planned_end_ts=None) -> Self:
        rec = cls()
        rec.camera_id = camera_id
        rec.reason = reason
        rec.retention_class = retention_class
        rec.start_ts = start_ts
        rec.end_ts = end_ts
        rec.planned_end_ts = planned_end_ts
        rec.created_by_id = created_by_id
        rec.note = note
        db.session.add(rec)
        db.session.commit()
        return rec

    def close(self, end_ts: datetime):
        self.end_ts = end_ts
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'reason': self.reason,
            'retention_class': self.retention_class,
            'start_ts': to_epoch_ms(self.start_ts),
            'end_ts': to_epoch_ms(self.end_ts),
            'planned_end_ts': to_epoch_ms(self.planned_end_ts),
            'note': self.note,
        }
