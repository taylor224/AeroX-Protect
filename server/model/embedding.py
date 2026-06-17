"""Semantic-search index (PLAN P6 A1). One row per indexed item (event/detection) holding
its embedding vector + the text it was built from. Derived/rebuildable data → lean (no soft
delete); unique on (source_type, source_ref) so reindex upserts.
"""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, Integer, String, UniqueConstraint, and_, asc

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, utcnow


class Embedding(SnowflakeMixin, BaseDB):
    __tablename__ = 'embeddings'
    __table_args__ = (UniqueConstraint('source_type', 'source_ref', name='uq_embeddings_source'),)

    source_type = Column(String(16), nullable=False)        # 'event' | 'detection'
    source_ref = Column(String(64), nullable=False)
    camera_id = Column(BigIntId, nullable=False, index=True)
    ts = Column(DateTime3, nullable=False, index=True)
    text = Column(String(300), nullable=True)
    backend = Column(String(16), nullable=False)            # 'clip' | 'hash'
    dim = Column(Integer, nullable=False)
    vector = Column(JSON, nullable=False)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def upsert(cls, *, source_type: str, source_ref: str, camera_id: int, ts: datetime,
               text: str, backend: str, vector: list[float]) -> Self:
        row = (db.session.query(cls)
               .filter(cls.source_type == source_type, cls.source_ref == str(source_ref))
               .first())
        if not row:
            row = cls()
            row.source_type = source_type
            row.source_ref = str(source_ref)
        row.camera_id = camera_id
        row.ts = ts
        row.text = (text or '')[:300]
        row.backend = backend
        row.dim = len(vector)
        row.vector = vector
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def search_pool(cls, camera_ids: list[int] | None, start: datetime | None,
                    end: datetime | None, backend: str, cap: int = 5000) -> list[Self]:
        """Candidate rows for brute-force cosine ranking, bounded by `cap` (newest first)."""
        q = db.session.query(cls).filter(cls.backend == backend)
        if camera_ids:
            q = q.filter(cls.camera_id.in_(camera_ids))
        if start is not None and end is not None:
            q = q.filter(and_(cls.ts >= start, cls.ts <= end))
        return q.order_by(cls.ts.desc()).limit(cap).all()

    @classmethod
    def count_for(cls, camera_id: int | None = None) -> int:
        q = db.session.query(cls.id)
        if camera_id:
            q = q.filter(cls.camera_id == camera_id)
        return q.count()

    def to_dict(self) -> dict:
        from server.model import to_epoch_ms
        return {
            'source_type': self.source_type,
            'source_ref': self.source_ref,
            'camera_id': str(self.camera_id),
            'ts': to_epoch_ms(self.ts),
            'text': self.text,
        }
