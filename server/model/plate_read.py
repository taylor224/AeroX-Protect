"""License-plate reads (PLAN P7 A7). One OCR'd plate observation. High-frequency, FK-free,
no soft delete — mirrors `detections`/`audio_detections`. `plate_key` is the normalized key
(for equality/search); `plate_text` is the raw read (for display). A watchlist hit stamps
`list_id`/`list_kind` and `event_id`.
"""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, Index, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, generate_snowflake_id, to_epoch_ms, utcnow


class PlateRead(SnowflakeMixin, BaseDB):
    __tablename__ = 'plate_reads'
    __table_args__ = (
        Index('idx_plate_cam_ts', 'camera_id', 'ts'),
        Index('idx_plate_key_ts', 'plate_key', 'ts'),
    )

    camera_id = Column(BigIntId, nullable=False)
    ts = Column(DateTime3, nullable=False)
    plate_text = Column(String(24), nullable=False)         # raw OCR read (display)
    plate_key = Column(String(24), nullable=False)          # normalized (equality/search)
    confidence = Column(SmallInteger, nullable=False)        # 0–100
    region = Column(JSON, nullable=True)                    # [x1,y1,x2,y2] normalized 0–1
    vehicle_label = Column(String(16), nullable=True)       # car/truck/bus… (if linked)
    track_id = Column(BigIntId, nullable=True)
    list_id = Column(BigIntId, nullable=True)               # matched watchlist entry
    list_kind = Column(String(8), nullable=True)            # allow | deny (on match)
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
            pid = m.get('id') or generate_snowflake_id()
            m['id'] = pid
            m.setdefault('created_at', now)
            mappings.append(m)
            ids.append(pid)
        db.session.bulk_insert_mappings(cls, mappings)
        db.session.commit()
        return ids

    @classmethod
    def recent_for_camera(cls, camera_id: int, limit: int = 50) -> list[Self]:
        return (db.session.query(cls).filter(cls.camera_id == camera_id)
                .order_by(cls.ts.desc()).limit(limit).all())

    @classmethod
    def search(cls, *, camera_ids=None, plate_key=None, start: datetime | None = None,
               end: datetime | None = None, list_kind=None, limit: int = 100) -> list[Self]:
        q = db.session.query(cls)
        if camera_ids is not None:
            q = q.filter(cls.camera_id.in_(camera_ids))
        if plate_key:
            q = q.filter(cls.plate_key.like('%' + plate_key + '%'))
        if start is not None:
            q = q.filter(cls.ts >= start)
        if end is not None:
            q = q.filter(cls.ts < end)
        if list_kind:
            q = q.filter(cls.list_kind == list_kind)
        return q.order_by(cls.ts.desc()).limit(limit).all()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'ts': to_epoch_ms(self.ts),
            'plate_text': self.plate_text,
            'plate_key': self.plate_key,
            'confidence': self.confidence,
            'region': self.region,
            'vehicle_label': self.vehicle_label,
            'list_kind': self.list_kind,
            'list_id': str(self.list_id) if self.list_id else None,
            'event_id': str(self.event_id) if self.event_id else None,
        }
