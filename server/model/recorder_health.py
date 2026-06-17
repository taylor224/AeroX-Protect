from typing import Self

from sqlalchemy import Column, Integer, String

from server.model import BaseDB, BigIntId, DateTime3, db, to_epoch_ms, utcnow

STATE_STOPPED = 'stopped'
STATE_STARTING = 'starting'
STATE_RECORDING = 'recording'
STATE_RECONNECTING = 'reconnecting'
STATE_ERROR = 'error'


class RecorderHealth(BaseDB):
    """Per-camera recorder health snapshot — UPSERT, keyed by camera_id (PLAN P2 §4.6)."""
    __tablename__ = 'recorder_health'

    camera_id = Column(BigIntId, primary_key=True, autoincrement=False)
    state = Column(String(16), nullable=False, default=STATE_STOPPED)
    pid = Column(Integer, nullable=True)
    last_segment_at = Column(DateTime3, nullable=True)
    restart_count = Column(Integer, nullable=False, default=0)
    last_error = Column(String(1000), nullable=True)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get(cls, camera_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id == camera_id).first()

    @classmethod
    def get_all(cls) -> list[Self]:
        return db.session.query(cls).all()

    @classmethod
    def upsert(cls, camera_id: int, **fields) -> Self:
        row = db.session.query(cls).filter(cls.camera_id == camera_id).first()
        if not row:
            row = cls()
            row.camera_id = camera_id
        for key, value in fields.items():
            setattr(row, key, value)
        row.updated_at = utcnow()
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self) -> dict:
        return {
            'camera_id': str(self.camera_id),
            'state': self.state,
            'pid': self.pid,
            'last_segment_at': to_epoch_ms(self.last_segment_at),
            'restart_count': self.restart_count,
            'last_error': self.last_error,
            'updated_at': to_epoch_ms(self.updated_at),
        }
