"""Audio classification results (PLAN P6 A4). High-frequency, FK-free, no soft delete —
the audio worker classifies windows of camera audio (glass break / scream / alarm / dog
bark …) and the node POSTs batches that land here. Mirrors `detections` (lean ingest).
"""
from datetime import datetime
from typing import Self

from sqlalchemy import Column, Index, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, generate_snowflake_id, to_epoch_ms, utcnow


class AudioDetection(SnowflakeMixin, BaseDB):
    __tablename__ = 'audio_detections'
    __table_args__ = (
        Index('idx_aud_cam_ts', 'camera_id', 'ts'),
        Index('idx_aud_label_ts', 'label', 'ts'),
    )

    camera_id = Column(BigIntId, nullable=False)
    ts = Column(DateTime3, nullable=False)
    label = Column(String(32), nullable=False)
    score = Column(SmallInteger, nullable=False)            # 0–100
    clip_path = Column(String(500), nullable=True)
    event_id = Column(BigIntId, nullable=True)
    node_id = Column(BigIntId, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def bulk_create(cls, rows: list[dict]) -> list[int]:
        if not rows:
            return []
        now = utcnow()
        mappings, ids = [], []
        for r in rows:
            m = dict(r)
            aid = m.get('id') or generate_snowflake_id()
            m['id'] = aid
            m.setdefault('created_at', now)
            mappings.append(m)
            ids.append(aid)
        db.session.bulk_insert_mappings(cls, mappings)
        db.session.commit()
        return ids

    @classmethod
    def recent_for_camera(cls, camera_id: int, limit: int = 50) -> list[Self]:
        return (db.session.query(cls).filter(cls.camera_id == camera_id)
                .order_by(cls.ts.desc()).limit(limit).all())

    @classmethod
    def search(cls, *, camera_ids=None, labels=None, start: datetime | None = None,
               end: datetime | None = None, min_score=None, limit: int = 100) -> list[Self]:
        q = db.session.query(cls)
        if camera_ids:
            q = q.filter(cls.camera_id.in_(camera_ids))
        if labels:
            q = q.filter(cls.label.in_(labels))
        if start is not None:
            q = q.filter(cls.ts >= start)
        if end is not None:
            q = q.filter(cls.ts < end)
        if min_score is not None:
            q = q.filter(cls.score >= min_score)
        return q.order_by(cls.ts.desc()).limit(limit).all()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'ts': to_epoch_ms(self.ts),
            'label': self.label,
            'score': self.score,
            'clip_path': self.clip_path,
            'event_id': str(self.event_id) if self.event_id else None,
        }
