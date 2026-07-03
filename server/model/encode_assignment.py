"""Camera → encoder-node assignment — the distribution authority for live-transcode
offload (mirrors detection_assignments). One row per camera (unique). `epoch` bumps on
every reassign so a stale/returned node's sessions are superseded. No soft-delete
(rebalance rewrites)."""
from typing import Self

from sqlalchemy import Column, Integer, String, UniqueConstraint

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

STATE_PENDING = 'pending'       # assigned, node has not confirmed a running session yet
STATE_ACTIVE = 'active'         # node reported the encode session running (source flips)
STATE_REASSIGNING = 'reassigning'
STATE_PAUSED = 'paused'


class EncodeAssignment(SnowflakeMixin, BaseDB):
    __tablename__ = 'encode_assignments'
    __table_args__ = (UniqueConstraint('camera_id', name='uq_encassign_cam'),)

    camera_id = Column(BigIntId, nullable=False)
    node_id = Column(BigIntId, nullable=False, index=True)
    state = Column(String(16), nullable=False, default=STATE_PENDING)
    claimed_at = Column(DateTime3, nullable=True)
    last_report_ts = Column(DateTime3, nullable=True)
    epoch = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get_for_camera(cls, camera_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id == camera_id).first()

    @classmethod
    def for_node(cls, node_id: int) -> list[Self]:
        return db.session.query(cls).filter(cls.node_id == node_id).all()

    @classmethod
    def all_rows(cls) -> list[Self]:
        return db.session.query(cls).order_by(cls.camera_id.asc()).all()

    @classmethod
    def by_state(cls, state: str) -> list[Self]:
        return db.session.query(cls).filter(cls.state == state).all()

    @classmethod
    def assign(cls, camera_id: int, node_id: int, *, state=STATE_PENDING) -> Self:
        """Create or repoint a camera's assignment, bumping epoch when the node changes."""
        row = cls.get_for_camera(camera_id)
        if row is None:
            row = cls()
            row.camera_id = camera_id
            row.epoch = 1
            row.node_id = node_id
            row.state = state
        else:
            if row.node_id != node_id:
                row.epoch = (row.epoch or 0) + 1
                row.claimed_at = None
            row.node_id = node_id
            row.state = state
        db.session.add(row)
        db.session.commit()
        return row

    def set_state(self, state: str):
        self.state = state
        db.session.add(self)
        db.session.commit()

    @classmethod
    def mark_report(cls, camera_id: int):
        row = cls.get_for_camera(camera_id)
        if row:
            row.last_report_ts = utcnow()
            if row.state == STATE_PENDING:
                row.state = STATE_ACTIVE
                row.claimed_at = utcnow()
            db.session.add(row)
            db.session.commit()

    @classmethod
    def remove_for_camera(cls, camera_id: int):
        db.session.query(cls).filter(cls.camera_id == camera_id).delete(synchronize_session=False)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'camera_id': str(self.camera_id),
            'node_id': str(self.node_id),
            'state': self.state,
            'epoch': self.epoch,
            'claimed_at': to_epoch_ms(self.claimed_at),
            'last_report_ts': to_epoch_ms(self.last_report_ts),
        }
