"""Observed faces (PLAN P7 A8 — `faces`/`face_matches`). One detected face from a camera
with its embedding + best identity match. High-frequency, FK-free, no soft delete (pruned
by retention). The embedding is stored for re-matching after enrollment changes but is NOT
returned in to_dict (privacy + payload size).
"""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, Index, Integer, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, generate_snowflake_id, to_epoch_ms, utcnow


class FaceObservation(SnowflakeMixin, BaseDB):
    __tablename__ = 'face_observations'
    __table_args__ = (
        Index('idx_face_cam_ts', 'camera_id', 'ts'),
        Index('idx_face_identity_ts', 'identity_id', 'ts'),
    )

    camera_id = Column(BigIntId, nullable=False)
    ts = Column(DateTime3, nullable=False)
    backend = Column(String(16), nullable=False)
    dim = Column(Integer, nullable=False)
    embedding = Column(JSON, nullable=False)               # the observed vector
    quality = Column(SmallInteger, nullable=True)          # detector face quality 0–100
    region = Column(JSON, nullable=True)
    identity_id = Column(BigIntId, nullable=True)          # matched identity (null = unknown)
    identity_name = Column(String(120), nullable=True)     # name snapshot at match time
    score = Column(SmallInteger, nullable=True)            # match cosine ×100
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
            fid = m.get('id') or generate_snowflake_id()
            m['id'] = fid
            m.setdefault('created_at', now)
            mappings.append(m)
            ids.append(fid)
        db.session.bulk_insert_mappings(cls, mappings)
        db.session.commit()
        return ids

    @classmethod
    def get_by_id(cls, obs_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == obs_id).first()

    @classmethod
    def recent_for_camera(cls, camera_id: int, limit: int = 50) -> list[Self]:
        return (db.session.query(cls).filter(cls.camera_id == camera_id)
                .order_by(cls.ts.desc()).limit(limit).all())

    @classmethod
    def search(cls, *, camera_ids=None, identity_id=None, known_only=False, limit: int = 100) -> list[Self]:
        q = db.session.query(cls)
        if camera_ids is not None:
            q = q.filter(cls.camera_id.in_(camera_ids))
        if identity_id is not None:
            q = q.filter(cls.identity_id == identity_id)
        elif known_only:
            q = q.filter(cls.identity_id.isnot(None))
        return q.order_by(cls.ts.desc()).limit(limit).all()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'ts': to_epoch_ms(self.ts),
            'quality': self.quality,
            'region': self.region,
            'identity_id': str(self.identity_id) if self.identity_id else None,
            'identity_name': self.identity_name,
            'score': self.score,
            'event_id': str(self.event_id) if self.event_id else None,
        }
