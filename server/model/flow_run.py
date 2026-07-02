"""Flow run log — one row per flow execution, with a per-node result trail
(node_results) so the editor can replay a run on the graph. High-frequency append:
no audit, FK-free (mirrors rule_execution)."""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, Integer, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

STATUS_RUNNING = 'running'
STATUS_SUCCESS = 'success'
STATUS_PARTIAL = 'partial'
STATUS_FAILED = 'failed'
STATUS_SKIPPED = 'skipped'


class FlowRun(SnowflakeMixin, BaseDB):
    __tablename__ = 'flow_runs'

    flow_id = Column(BigIntId, nullable=False, index=True)
    trigger_type = Column(String(16), nullable=False)
    event_id = Column(BigIntId, nullable=True)
    camera_id = Column(BigIntId, nullable=True)
    status = Column(String(16), nullable=False, default=STATUS_RUNNING)
    skip_reason = Column(String(32), nullable=True)
    trigger_snapshot = Column(JSON, nullable=True)   # TriggerEvent.serialize() at run start
    node_results = Column(JSON, nullable=True)       # [{node_id, type, status, input, output, error, started_ts, duration_ms}]
    started_ts = Column(DateTime3, nullable=True)
    finished_ts = Column(DateTime3, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    deleted_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, run_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == run_id).first()

    @classmethod
    def create(cls, **fields) -> Self:
        row = cls()
        for k, v in fields.items():
            setattr(row, k, v)
        db.session.add(row)
        db.session.commit()
        return row

    def update(self, **fields) -> Self:
        for k, v in fields.items():
            setattr(self, k, v)
        db.session.add(self)
        db.session.commit()
        return self

    @classmethod
    def list_runs(cls, *, flow_id=None, status=None, page=1, items_per_page=50) -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if flow_id:
            q = q.filter(cls.flow_id == flow_id)
        if status:
            q = q.filter(cls.status == status)
        total = q.count()
        rows = q.order_by(cls.created_at.desc()).limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    @classmethod
    def purge_older_than(cls, cutoff: datetime) -> int:
        n = db.session.query(cls).filter(cls.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return n

    def to_dict(self, *, with_detail: bool = True) -> dict:
        out = {
            'id': str(self.id), 'flow_id': str(self.flow_id), 'trigger_type': self.trigger_type,
            'event_id': str(self.event_id) if self.event_id else None,
            'camera_id': str(self.camera_id) if self.camera_id else None,
            'status': self.status, 'skip_reason': self.skip_reason,
            'started_ts': to_epoch_ms(self.started_ts), 'finished_ts': to_epoch_ms(self.finished_ts),
            'duration_ms': self.duration_ms, 'created_at': to_epoch_ms(self.created_at),
        }
        if with_detail:
            out['trigger_snapshot'] = self.trigger_snapshot
            out['node_results'] = self.node_results
        else:
            # list view: statuses only — enough to color the graph without the heavy payloads
            out['node_statuses'] = {r.get('node_id'): r.get('status')
                                    for r in (self.node_results or []) if r.get('node_id')}
        return out
