from typing import Self

from sqlalchemy import Column, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow


class CameraSubscription(SnowflakeMixin, BaseDB):
    """Event-subscription state mirror for UI/diagnostics (PLAN §4.6; runtime in Redis)."""
    __tablename__ = 'camera_subscriptions'

    camera_id = Column(BigIntId, nullable=False, unique=True, index=True)
    protocol = Column(String(16), nullable=False)
    state = Column(String(16), nullable=False)
    last_event_ts = Column(DateTime3, nullable=True)
    renew_at_ts = Column(DateTime3, nullable=True)
    fail_count = Column(SmallInteger, nullable=False, default=0)
    last_error = Column(String(512), nullable=True)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get_all(cls) -> list[Self]:
        return db.session.query(cls).all()

    @classmethod
    def get_by_camera(cls, camera_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.camera_id == camera_id).first()

    @classmethod
    def upsert(cls, camera_id: int, **fields) -> Self:
        row = db.session.query(cls).filter(cls.camera_id == camera_id).first()
        if not row:
            row = cls()
            row.camera_id = camera_id
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = utcnow()
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self) -> dict:
        return {
            'camera_id': str(self.camera_id),
            'protocol': self.protocol,
            'state': self.state,
            'last_event_ts': to_epoch_ms(self.last_event_ts),
            'renew_at_ts': to_epoch_ms(self.renew_at_ts),
            'fail_count': self.fail_count,
            'last_error': self.last_error,
            'updated_at': to_epoch_ms(self.updated_at),
        }
