"""Archive jobs (PLAN P6 M2): one offload of a recording's segments to a target, with a
manifest (restore index). High-frequency-ish but bounded; lean, no soft delete needed but
kept for consistency.
"""
from typing import Self

from sqlalchemy import JSON, BigInteger, Column, Integer, String, desc

from server.model import AuditMixin, BaseDB, BigIntId, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

STATUS_QUEUED = 'queued'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'

SOURCE_RECORDING = 'recording'


class ArchiveJob(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'archive_jobs'

    target_id = Column(BigIntId, nullable=False, index=True)
    source_type = Column(String(16), nullable=False, default=SOURCE_RECORDING)
    source_ref = Column(String(64), nullable=False)
    status = Column(String(12), nullable=False, default=STATUS_QUEUED)
    progress = Column(Integer, nullable=False, default=0)
    bytes_total = Column(BigInteger, nullable=False, default=0)
    bytes_done = Column(BigInteger, nullable=False, default=0)
    manifest = Column(JSON, nullable=True)
    celery_task_id = Column(String(100), nullable=True)
    error_message = Column(String(1000), nullable=True)

    @classmethod
    def get_by_id(cls, job_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == job_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls, limit: int = 50) -> list[Self]:
        return (db.session.query(cls).filter(cls.deleted_at.is_(None))
                .order_by(desc(cls.created_at)).limit(limit).all())

    @classmethod
    def create(cls, target_id, source_type, source_ref, actor_id=None) -> Self:
        j = cls()
        j.target_id = target_id
        j.source_type = source_type
        j.source_ref = str(source_ref)
        j.created_by_id = actor_id
        j.last_updated_by_id = actor_id
        db.session.add(j)
        db.session.commit()
        return j

    def update(self, **fields) -> Self:
        for k, v in fields.items():
            setattr(self, k, v)
        db.session.add(self)
        db.session.commit()
        return self

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'target_id': str(self.target_id),
            'source_type': self.source_type,
            'source_ref': self.source_ref,
            'status': self.status,
            'progress': self.progress,
            'bytes_total': self.bytes_total,
            'bytes_done': self.bytes_done,
            'manifest': self.manifest,
            'error_message': self.error_message,
            'created_at': to_epoch_ms(self.created_at),
        }
