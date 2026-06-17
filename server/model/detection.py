"""Tracked object detection — ultra-high-frequency append, the search core (PLAN P4 §4.1).

No soft-delete/audit (retention = batch DELETE / partition DROP); FK-free (logical refs).
bbox is normalized 0–1 [x1,y1,x2,y2] (resolution-independent overlay). ts is the go2rtc
frame wall-clock (UTC) so it time-aligns with P2 segments (§6.6)."""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, Index, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow
from server.util.snowflake import generate_snowflake_id


class Detection(SnowflakeMixin, BaseDB):
    __tablename__ = 'detections'
    __table_args__ = (
        Index('idx_det_cam_ts', 'camera_id', 'ts'),
        Index('idx_det_label_ts', 'label', 'ts'),
        Index('idx_det_cam_label_ts', 'camera_id', 'label', 'ts'),
        Index('idx_det_track', 'camera_id', 'track_id'),
        Index('idx_det_zone_ts', 'zone_id', 'ts'),
        Index('idx_det_segment', 'segment_id'),
        Index('idx_det_event', 'event_id'),
    )

    camera_id = Column(BigIntId, nullable=False)
    ts = Column(DateTime3, nullable=False)
    class_id = Column(SmallInteger, nullable=False)
    label = Column(String(32), nullable=False)
    confidence = Column(SmallInteger, nullable=False)        # 0–100
    track_id = Column(BigIntId, nullable=True)
    track_key = Column(String(32), nullable=True)
    bbox = Column(JSON, nullable=False)                      # [x1,y1,x2,y2] normalized 0–1
    frame_w = Column(SmallInteger, nullable=True)
    frame_h = Column(SmallInteger, nullable=True)
    zone_id = Column(BigIntId, nullable=True)
    segment_id = Column(BigIntId, nullable=True)
    event_id = Column(BigIntId, nullable=True)
    attrs = Column(JSON, nullable=True)
    node_id = Column(BigIntId, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    # ── ingest (bulk) ─────────────────────────────────────────────────────────
    @classmethod
    def bulk_create(cls, rows: list[dict]) -> list[int]:
        """Bulk-insert detection mappings (bypasses ORM defaults → set id/created_at)."""
        if not rows:
            return []
        now = utcnow()
        mappings, ids = [], []
        for r in rows:
            m = dict(r)
            did = m.get('id') or generate_snowflake_id()
            m['id'] = did
            m.setdefault('created_at', now)
            mappings.append(m)
            ids.append(did)
        db.session.bulk_insert_mappings(cls, mappings)
        db.session.commit()
        return ids

    # ── queries ───────────────────────────────────────────────────────────────
    @classmethod
    def get_by_id(cls, det_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == det_id).first()

    @classmethod
    def search(cls, *, camera_ids=None, labels=None, start=None, end=None, zone_ids=None,
               min_confidence=None, track_id=None, page=1, items_per_page=50,
               order='desc') -> tuple[int, list[Self]]:
        q = db.session.query(cls)
        if camera_ids:
            q = q.filter(cls.camera_id.in_(camera_ids))
        if labels:
            q = q.filter(cls.label.in_(labels))
        if start is not None:
            q = q.filter(cls.ts >= start)
        if end is not None:
            q = q.filter(cls.ts <= end)
        if zone_ids:
            q = q.filter(cls.zone_id.in_(zone_ids))
        if min_confidence is not None:
            q = q.filter(cls.confidence >= min_confidence)
        if track_id is not None:
            q = q.filter(cls.track_id == track_id)
        total = q.count()
        q = q.order_by(cls.ts.asc() if order == 'asc' else cls.ts.desc())
        rows = q.limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    @classmethod
    def in_window(cls, camera_id: int, start: datetime, end: datetime, labels=None) -> list[Self]:
        """All detections in [start,end] for a camera (overlay/timeline), ts-ascending."""
        q = db.session.query(cls).filter(cls.camera_id == camera_id, cls.ts >= start, cls.ts <= end)
        if labels:
            q = q.filter(cls.label.in_(labels))
        return q.order_by(cls.ts.asc()).all()

    @classmethod
    def backfill_candidates(cls, limit: int = 500) -> list[Self]:
        return db.session.query(cls).filter(cls.segment_id.is_(None)).order_by(cls.ts.asc()).limit(limit).all()

    @classmethod
    def link_segment(cls, det_ids: list[int], segment_id: int):
        if not det_ids:
            return
        db.session.query(cls).filter(cls.id.in_(det_ids)).update(
            {cls.segment_id: segment_id}, synchronize_session=False)
        db.session.commit()

    @classmethod
    def link_event(cls, det_ids: list[int], event_id: int):
        if not det_ids:
            return
        db.session.query(cls).filter(cls.id.in_(det_ids)).update(
            {cls.event_id: event_id}, synchronize_session=False)
        db.session.commit()

    @classmethod
    def purge_older_than(cls, cutoff: datetime) -> int:
        n = db.session.query(cls).filter(cls.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return n

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'ts': to_epoch_ms(self.ts),
            'class_id': self.class_id,
            'label': self.label,
            'confidence': self.confidence,
            'track_id': str(self.track_id) if self.track_id else None,
            'track_key': self.track_key,
            'bbox': self.bbox,
            'frame_w': self.frame_w,
            'frame_h': self.frame_h,
            'zone_id': str(self.zone_id) if self.zone_id else None,
            'segment_id': str(self.segment_id) if self.segment_id else None,
            'event_id': str(self.event_id) if self.event_id else None,
            'node_id': str(self.node_id) if self.node_id else None,
        }
