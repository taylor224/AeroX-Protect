"""Web-push (VAPID) subscription (PLAN P5 §4.8). endpoint_hash UNIQUE for upsert/dedup;
p256dh/auth are client-generated keys (not server secrets) but kept out of DTOs."""
import hashlib
from typing import Self

from sqlalchemy import CHAR, Boolean, Column, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, utcnow


def hash_endpoint(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


class PushSubscription(SnowflakeMixin, TimestampMixin, BaseDB):
    __tablename__ = 'push_subscriptions'

    user_id = Column(BigIntId, nullable=False)
    endpoint = Column(String(1024), nullable=False)
    endpoint_hash = Column(CHAR(64), nullable=False, unique=True)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(64), nullable=False)
    ua = Column(String(255), nullable=True)
    expiration_ts = Column(DateTime3, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    last_success_at = Column(DateTime3, nullable=True)

    @classmethod
    def upsert(cls, user_id: int, endpoint: str, p256dh: str, auth: str, ua=None) -> Self:
        eh = hash_endpoint(endpoint)
        row = db.session.query(cls).filter(cls.endpoint_hash == eh).first()
        if row is None:
            row = cls()
            row.endpoint_hash = eh
        row.user_id = user_id
        row.endpoint = endpoint
        row.p256dh = p256dh
        row.auth = auth
        row.ua = ua
        row.enabled = True
        row.deleted_at = None
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def active_for_user(cls, user_id: int) -> list[Self]:
        return db.session.query(cls).filter(
            cls.user_id == user_id, cls.enabled.is_(True), cls.deleted_at.is_(None)).all()

    @classmethod
    def disable_by_endpoint(cls, user_id: int, endpoint: str):
        db.session.query(cls).filter(
            cls.endpoint_hash == hash_endpoint(endpoint), cls.user_id == user_id
        ).update({cls.enabled: False, cls.deleted_at: utcnow()}, synchronize_session=False)
        db.session.commit()

    def disable(self):
        self.enabled = False
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def mark_success(self):
        self.last_success_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        from server.model import to_epoch_ms
        return {'id': str(self.id), 'ua': self.ua, 'enabled': bool(self.enabled),
                'last_success_at': to_epoch_ms(self.last_success_at)}
