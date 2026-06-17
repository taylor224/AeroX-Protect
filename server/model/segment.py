from datetime import datetime
from typing import Self

from sqlalchemy import BigInteger, Boolean, Column, Integer, SmallInteger, String, func

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

TIER_CACHE = 'cache'
TIER_RECORD = 'record'
REASON_CONTINUOUS = 'continuous'
REASON_MANUAL = 'manual'
REASON_EDGE = 'edge'          # P6 R6 — imported from camera SD (gap-fill)


class Segment(SnowflakeMixin, BaseDB):
    """Physical recorded segment index (PLAN P2 §4.3). Highest-frequency table —
    no FK, no soft delete (delete = file unlink + row DELETE)."""
    __tablename__ = 'segments'

    camera_id = Column(BigIntId, nullable=False)
    disk_id = Column(BigIntId, nullable=False)
    rel_path = Column(String(500), nullable=False)          # relative to disk.mount_path
    start_ts = Column(DateTime3, nullable=False)
    end_ts = Column(DateTime3, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    container = Column(String(8), nullable=False, default='fmp4')
    video_codec = Column(String(20), nullable=True)
    has_audio = Column(Boolean, nullable=False, default=False)
    width = Column(SmallInteger, nullable=True)
    height = Column(SmallInteger, nullable=True)
    first_keyframe_ms = Column(Integer, nullable=False, default=0)
    reason = Column(String(12), nullable=False, default=REASON_CONTINUOUS)
    storage_tier = Column(String(8), nullable=False, default=TIER_CACHE)
    stream_role = Column(String(8), nullable=False, default='main')   # P6 R4 — main | sub
    corrupt = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def get_by_id(cls, segment_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == segment_id).first()

    @classmethod
    def exists_rel_path(cls, camera_id: int, rel_path: str) -> bool:
        return db.session.query(cls.id).filter(
            cls.camera_id == camera_id, cls.rel_path == rel_path).first() is not None

    @classmethod
    def get_range(cls, camera_id: int, start: datetime, end: datetime) -> list[Self]:
        """Segments overlapping [start, end], ordered by start_ts (timeline/playback)."""
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.corrupt.is_(False),
            cls.start_ts < end, cls.end_ts > start).order_by(cls.start_ts.asc()).all()

    @classmethod
    def get_at(cls, camera_id: int, ts: datetime) -> Self | None:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.start_ts <= ts, cls.end_ts > ts).order_by(cls.start_ts.desc()).first()

    @classmethod
    def oldest_for_camera(cls, camera_id: int, limit: int = 500) -> list[Self]:
        return db.session.query(cls).filter(cls.camera_id == camera_id).order_by(cls.start_ts.asc()).limit(limit).all()

    @classmethod
    def older_than(cls, camera_id: int, cutoff: datetime, limit: int = 1000) -> list[Self]:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.end_ts < cutoff).order_by(cls.start_ts.asc()).limit(limit).all()

    @classmethod
    def oldest_on_disk(cls, disk_id: int, limit: int = 500) -> list[Self]:
        return db.session.query(cls).filter(cls.disk_id == disk_id).order_by(cls.start_ts.asc()).limit(limit).all()

    @classmethod
    def total_size_for_camera(cls, camera_id: int) -> int:
        return int(db.session.query(func.coalesce(func.sum(cls.size_bytes), 0)).filter(
            cls.camera_id == camera_id).scalar() or 0)

    @classmethod
    def cache_tier_older_than(cls, cutoff: datetime, limit: int = 500) -> list[Self]:
        return db.session.query(cls).filter(
            cls.storage_tier == TIER_CACHE, cls.end_ts < cutoff).order_by(cls.start_ts.asc()).limit(limit).all()

    @classmethod
    def create(cls, **fields) -> Self:
        seg = cls(**fields)
        db.session.add(seg)
        db.session.commit()
        return seg

    def mark_reason(self, reason: str):
        self.reason = reason
        db.session.add(self)

    def delete_row(self):
        db.session.delete(self)

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'disk_id': str(self.disk_id),
            'start_ts': to_epoch_ms(self.start_ts),
            'end_ts': to_epoch_ms(self.end_ts),
            'duration_ms': self.duration_ms,
            'size_bytes': self.size_bytes,
            'container': self.container,
            'video_codec': self.video_codec,
            'has_audio': bool(self.has_audio),
            'width': self.width,
            'height': self.height,
            'first_keyframe_ms': self.first_keyframe_ms,
            'reason': self.reason,
            'storage_tier': self.storage_tier,
        }
