"""Edge-recording import jobs (PLAN P6 R6). One gap-fill import of a camera's on-board
SD clips into the NVR timeline over a time range. The driver searches the camera's SD
recordings (ISAPI ContentMgmt/search · SUNAPI SD · ONVIF Replay/Search); the service
imports only the clips that overlap *gaps* in our segments and indexes them as
`reason='edge'`. Mirrors ArchiveJob (queued→running→done/failed + manifest).
"""
from typing import Self

from sqlalchemy import JSON, BigInteger, Column, Integer, String, desc

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

STATUS_QUEUED = 'queued'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'


class EdgeImportJob(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'edge_import_jobs'

    camera_id = Column(BigIntId, nullable=False, index=True)
    range_start = Column(DateTime3, nullable=False)
    range_end = Column(DateTime3, nullable=False)
    status = Column(String(12), nullable=False, default=STATUS_QUEUED)
    progress = Column(Integer, nullable=False, default=0)
    clips_found = Column(Integer, nullable=False, default=0)
    clips_imported = Column(Integer, nullable=False, default=0)
    bytes_done = Column(BigInteger, nullable=False, default=0)
    manifest = Column(JSON, nullable=True)         # [{start_ts, end_ts, size_bytes, rel_path}]
    celery_task_id = Column(String(100), nullable=True)
    error_message = Column(String(1000), nullable=True)

    @classmethod
    def get_by_id(cls, job_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == job_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for_camera(cls, camera_id, limit: int = 50) -> list[Self]:
        return (db.session.query(cls)
                .filter(cls.camera_id == camera_id, cls.deleted_at.is_(None))
                .order_by(desc(cls.created_at)).limit(limit).all())

    @classmethod
    def create(cls, camera_id, range_start, range_end, actor_id=None) -> Self:
        j = cls()
        j.camera_id = camera_id
        j.range_start = range_start
        j.range_end = range_end
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
            'camera_id': str(self.camera_id),
            'range_start': to_epoch_ms(self.range_start),
            'range_end': to_epoch_ms(self.range_end),
            'status': self.status,
            'progress': self.progress,
            'clips_found': self.clips_found,
            'clips_imported': self.clips_imported,
            'bytes_done': self.bytes_done,
            'manifest': self.manifest,
            'error_message': self.error_message,
            'created_at': to_epoch_ms(self.created_at),
        }
