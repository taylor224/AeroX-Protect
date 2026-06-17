"""Rule execution log (PLAN P5 §4.2) — high-frequency append. No audit/soft-audit; FK-free."""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

STATUS_QUEUED = 'queued'
STATUS_RUNNING = 'running'
STATUS_SUCCESS = 'success'
STATUS_PARTIAL = 'partial'
STATUS_FAILED = 'failed'
STATUS_SKIPPED = 'skipped'


class RuleExecution(SnowflakeMixin, BaseDB):
    __tablename__ = 'rule_executions'

    rule_id = Column(BigIntId, nullable=False)
    trigger_type = Column(String(16), nullable=False)
    event_id = Column(BigIntId, nullable=True)
    camera_id = Column(BigIntId, nullable=True)
    matched = Column(Boolean, nullable=False, default=False)
    skip_reason = Column(String(32), nullable=True)
    idempotency_key = Column(String(120), nullable=True)
    action_results = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default=STATUS_QUEUED)
    started_ts = Column(DateTime3, nullable=True)
    finished_ts = Column(DateTime3, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    celery_task_id = Column(String(64), nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    deleted_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, exec_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == exec_id).first()

    @classmethod
    def create(cls, **fields) -> Self:
        row = cls()
        for k, v in fields.items():
            setattr(row, k, v)
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def list_logs(cls, *, rule_id=None, camera_id=None, status=None, page=1, items_per_page=50) -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if rule_id:
            q = q.filter(cls.rule_id == rule_id)
        if camera_id:
            q = q.filter(cls.camera_id == camera_id)
        if status:
            q = q.filter(cls.status == status)
        total = q.count()
        rows = q.order_by(cls.created_at.desc()).limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    def update(self, **fields) -> Self:
        for k, v in fields.items():
            setattr(self, k, v)
        db.session.add(self)
        db.session.commit()
        return self

    @classmethod
    def purge_older_than(cls, cutoff: datetime) -> int:
        n = db.session.query(cls).filter(cls.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return n

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'rule_id': str(self.rule_id), 'trigger_type': self.trigger_type,
            'event_id': str(self.event_id) if self.event_id else None,
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'matched': bool(self.matched), 'skip_reason': self.skip_reason,
            'action_results': self.action_results, 'status': self.status,
            'started_ts': to_epoch_ms(self.started_ts), 'finished_ts': to_epoch_ms(self.finished_ts),
            'duration_ms': self.duration_ms, 'created_at': to_epoch_ms(self.created_at),
        }
