from typing import Self

from sqlalchemy import JSON, Column, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, utcnow

STATUS_PENDING = 'pending'
STATUS_CONSUMED = 'consumed'
STATUS_FAILED = 'failed'


class EventOutbox(SnowflakeMixin, BaseDB):
    """At-least-once trigger feed for P5 (rules/notifications). PLAN §4.5."""
    __tablename__ = 'event_outbox'

    event_id = Column(BigIntId, nullable=False, index=True)
    camera_id = Column(BigIntId, nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False, default=STATUS_PENDING)
    attempts = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    consumed_at = Column(DateTime3, nullable=True)

    @classmethod
    def publish(cls, event) -> Self:
        row = cls()
        row.event_id = event.id
        row.camera_id = event.camera_id
        row.event_type = event.type
        row.payload = event.to_dict(with_raw=True)   # raw carries face identity / lpr plate for rules
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def get_pending(cls, limit: int = 100) -> list[Self]:
        return db.session.query(cls).filter(cls.status == STATUS_PENDING).order_by(
            cls.created_at.asc()).limit(limit).all()

    def mark_consumed(self):
        self.status = STATUS_CONSUMED
        self.consumed_at = utcnow()
        db.session.add(self)
        db.session.commit()
