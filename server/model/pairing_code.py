"""60s one-time numeric pairing code (PLAN P5 §4.6). Plaintext is NEVER stored — only
sha256(code + pepper). Consume is an atomic UPDATE…WHERE consumed_at IS NULL so concurrent
claims race to exactly one winner."""
from datetime import datetime
from typing import Self

from sqlalchemy import CHAR, Column, SmallInteger, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow


class PairingCode(SnowflakeMixin, BaseDB):
    __tablename__ = 'pairing_codes'

    monitor_id = Column(BigIntId, nullable=False)
    code_hash = Column(CHAR(64), nullable=False)
    code_last4 = Column(CHAR(4), nullable=True)
    expires_at = Column(DateTime3, nullable=False)
    attempts = Column(SmallInteger, nullable=False, default=0)
    max_attempts = Column(SmallInteger, nullable=False, default=5)
    consumed_at = Column(DateTime3, nullable=True)
    created_ip = Column(String(64), nullable=True)
    created_by_id = Column(BigIntId, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def find_active(cls, code_hash: str) -> Self | None:
        """An unconsumed, unexpired code matching the hash."""
        return db.session.query(cls).filter(
            cls.code_hash == code_hash, cls.consumed_at.is_(None), cls.expires_at > utcnow()
        ).order_by(cls.created_at.desc()).first()

    @classmethod
    def create(cls, monitor_id: int, code_hash: str, expires_at: datetime, ip=None, actor_id=None) -> Self:
        c = cls()
        c.monitor_id = monitor_id
        c.code_hash = code_hash
        c.expires_at = expires_at
        c.created_ip = ip
        c.created_by_id = actor_id
        db.session.add(c)
        db.session.commit()
        return c

    @classmethod
    def expire_active_for_monitor(cls, monitor_id: int):
        """Force-expire any live codes for a monitor (only one active code at a time)."""
        db.session.query(cls).filter(
            cls.monitor_id == monitor_id, cls.consumed_at.is_(None), cls.expires_at > utcnow()
        ).update({cls.expires_at: utcnow()}, synchronize_session=False)
        db.session.commit()

    def bump_attempts(self):
        self.attempts = (self.attempts or 0) + 1
        db.session.add(self)
        db.session.commit()

    def consume(self) -> bool:
        """Atomic one-time consume. Returns True iff this call won the race."""
        rowcount = db.session.query(type(self)).filter(
            type(self).id == self.id, type(self).consumed_at.is_(None)
        ).update({type(self).consumed_at: utcnow()}, synchronize_session=False)
        db.session.commit()
        return rowcount == 1

    @classmethod
    def cleanup(cls) -> int:
        n = db.session.query(cls).filter(
            (cls.expires_at < utcnow()) | (cls.consumed_at.isnot(None))).delete(synchronize_session=False)
        db.session.commit()
        return n
