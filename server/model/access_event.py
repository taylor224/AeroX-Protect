"""Access events (PLAN P10). Every swipe decision (granted/denied) is logged here and also
promoted to a P3 `access` event. Append-only audit log — FK-free, no soft delete.
"""
from datetime import datetime
from typing import Self

from sqlalchemy import Column, Index, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

DECISION_GRANTED = 'granted'
DECISION_DENIED = 'denied'


class AccessEvent(SnowflakeMixin, BaseDB):
    __tablename__ = 'access_events'
    __table_args__ = (
        Index('idx_access_door_ts', 'door_id', 'ts'),
        Index('idx_access_card_ts', 'card_number', 'ts'),
    )

    door_id = Column(BigIntId, nullable=False)
    credential_id = Column(BigIntId, nullable=True)
    card_number = Column(String(64), nullable=True)
    holder_name = Column(String(120), nullable=True)
    decision = Column(String(8), nullable=False)
    reason = Column(String(40), nullable=True)
    source = Column(String(16), nullable=True)             # reader | manual | api
    ts = Column(DateTime3, nullable=False, default=utcnow)
    event_id = Column(BigIntId, nullable=True)

    @classmethod
    def record(cls, *, door_id, decision, reason=None, credential_id=None, card_number=None,
               holder_name=None, source=None, event_id=None) -> Self:
        e = cls()
        e.door_id = door_id
        e.decision = decision
        e.reason = reason
        e.credential_id = credential_id
        e.card_number = card_number
        e.holder_name = holder_name
        e.source = source
        e.event_id = event_id
        e.ts = utcnow()
        db.session.add(e)
        db.session.commit()
        return e

    @classmethod
    def recent(cls, *, door_id=None, limit: int = 100) -> list[Self]:
        q = db.session.query(cls)
        if door_id is not None:
            q = q.filter(cls.door_id == door_id)
        return q.order_by(cls.ts.desc()).limit(limit).all()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'door_id': str(self.door_id),
            'credential_id': str(self.credential_id) if self.credential_id else None,
            'card_number': self.card_number,
            'holder_name': self.holder_name,
            'decision': self.decision,
            'reason': self.reason,
            'source': self.source,
            'ts': to_epoch_ms(self.ts),
        }
