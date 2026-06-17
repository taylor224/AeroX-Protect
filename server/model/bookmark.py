"""Bookmarks / labels (PLAN P6 §4.1, R2): a named point or range on a camera's
timeline. `lock_retention=true` ties into P2 retention (marks the covering recording
`protected` so it survives purge). Identified by id (str) like events/detections — no
external uuid needed.
"""
from datetime import datetime
from typing import Self

from sqlalchemy import Boolean, Column, String, Text, asc, func

from server.model import (
    AuditMixin,
    BaseDB,
    BigIntId,
    DateTime3,
    SnowflakeMixin,
    TimestampMixin,
    db,
    to_epoch_ms,
)

DEFAULT_COLOR = '#3E6AE1'  # DESIGN Electric Blue


class Bookmark(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'bookmarks'

    camera_id = Column(BigIntId, nullable=False, index=True)
    start_ts = Column(DateTime3, nullable=False, index=True)
    end_ts = Column(DateTime3, nullable=True)          # NULL = point bookmark
    label = Column(String(200), nullable=False)
    color = Column(String(16), nullable=True)
    note = Column(Text, nullable=True)
    recording_id = Column(BigIntId, nullable=True)
    event_id = Column(BigIntId, nullable=True)
    lock_retention = Column(Boolean, nullable=False, default=False)

    @classmethod
    def get_by_id(cls, bookmark_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == bookmark_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for_camera(cls, camera_id: int, start: datetime | None = None,
                        end: datetime | None = None) -> list[Self]:
        q = db.session.query(cls).filter(cls.camera_id == camera_id, cls.deleted_at.is_(None))
        # overlap: bookmark.start <= window.end AND coalesce(end, start) >= window.start
        if end is not None:
            q = q.filter(cls.start_ts <= end)
        if start is not None:
            q = q.filter(func.coalesce(cls.end_ts, cls.start_ts) >= start)
        return q.order_by(asc(cls.start_ts)).all()

    @classmethod
    def create(cls, camera_id: int, start_ts: datetime, label: str, *, end_ts=None,
               color=None, note=None, recording_id=None, event_id=None,
               lock_retention=False, actor_id=None) -> Self:
        b = cls()
        b.camera_id = camera_id
        b.start_ts = start_ts
        b.end_ts = end_ts
        b.label = label
        b.color = color or DEFAULT_COLOR
        b.note = note
        b.recording_id = recording_id
        b.event_id = event_id
        b.lock_retention = bool(lock_retention)
        b.created_by_id = actor_id
        b.last_updated_by_id = actor_id
        db.session.add(b)
        db.session.commit()
        return b

    def update(self, actor_id=None, **fields) -> Self:
        for k, v in fields.items():
            setattr(self, k, v)
        if actor_id is not None:
            self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'start_ts': to_epoch_ms(self.start_ts),
            'end_ts': to_epoch_ms(self.end_ts),
            'label': self.label,
            'color': self.color,
            'note': self.note,
            'recording_id': str(self.recording_id) if self.recording_id else None,
            'event_id': str(self.event_id) if self.event_id else None,
            'lock_retention': bool(self.lock_retention),
            'created_by_id': str(self.created_by_id) if self.created_by_id else None,
            'created_at': to_epoch_ms(self.created_at),
        }
