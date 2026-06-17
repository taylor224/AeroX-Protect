from datetime import datetime
from typing import Self

from sqlalchemy import JSON, BigInteger, Column, Integer, SmallInteger, String

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

STATUS_QUEUED = 'queued'
STATUS_RUNNING = 'running'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_CANCELED = 'canceled'


class TimelapseJob(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'timelapse_jobs'

    camera_id = Column(BigIntId, nullable=False, index=True)
    range_start_ts = Column(DateTime3, nullable=False)
    range_end_ts = Column(DateTime3, nullable=False)
    source = Column(String(16), nullable=False, default='range')   # range / events
    event_ids = Column(JSON, nullable=True)
    speed_factor = Column(Integer, nullable=False, default=60)
    params = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default=STATUS_QUEUED)
    progress = Column(SmallInteger, nullable=False, default=0)
    celery_task_id = Column(String(64), nullable=True)
    output_disk_id = Column(BigIntId, nullable=True)
    output_path = Column(String(512), nullable=True)
    output_size = Column(BigInteger, nullable=True)
    error = Column(String(512), nullable=True)
    expires_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, job_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == job_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for(cls, camera_id, status, page, items_per_page) -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if camera_id:
            q = q.filter(cls.camera_id == camera_id)
        if status:
            q = q.filter(cls.status == status)
        q = q.order_by(cls.created_at.desc())
        return q.count(), q.limit(items_per_page).offset((page - 1) * items_per_page).all()

    @classmethod
    def create(cls, camera_id, range_start, range_end, source, speed_factor, params,
               event_ids=None, actor_id=None) -> Self:
        j = cls()
        j.camera_id = camera_id
        j.range_start_ts = range_start
        j.range_end_ts = range_end
        j.source = source
        j.speed_factor = speed_factor
        j.params = params
        j.event_ids = event_ids
        j.created_by_id = actor_id
        db.session.add(j)
        db.session.commit()
        return j

    def update(self, **fields):
        for k, v in fields.items():
            setattr(self, k, v)
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'range_start_ts': to_epoch_ms(self.range_start_ts),
            'range_end_ts': to_epoch_ms(self.range_end_ts),
            'source': self.source,
            'speed_factor': self.speed_factor,
            'status': self.status,
            'progress': self.progress,
            'output_size': self.output_size,
            'error': self.error,
            'created_at': to_epoch_ms(self.created_at),
        }
