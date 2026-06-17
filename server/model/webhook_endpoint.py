"""Webhook endpoint (PLAN P5 §4.4): HMAC-signed delivery target. purpose=action (rule
actions) or subscription (external API event push). secret Fernet-encrypted."""
import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, LargeBinary, SmallInteger, String

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms
from server.util import crypto

PURPOSE_ACTION = 'action'
PURPOSE_SUBSCRIPTION = 'subscription'
FAILURE_CIRCUIT_BREAK = 10


class WebhookEndpoint(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'webhook_endpoints'

    uuid = Column(String(32), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    url = Column(String(1024), nullable=False)
    secret_enc = Column(LargeBinary(512), nullable=True)
    cred_key_id = Column(String(16), nullable=True)
    headers = Column(JSON, nullable=True)
    timeout_ms = Column(Integer, nullable=False, default=5000)
    max_retries = Column(SmallInteger, nullable=False, default=3)
    verify_tls = Column(Boolean, nullable=False, default=True)
    purpose = Column(String(16), nullable=False, default=PURPOSE_ACTION)
    subscription_filter = Column(JSON, nullable=True)
    api_token_id = Column(BigIntId, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    last_status = Column(SmallInteger, nullable=True)
    last_delivered_at = Column(DateTime3, nullable=True)
    consecutive_failures = Column(SmallInteger, nullable=False, default=0)

    @classmethod
    def get_by_id(cls, hook_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == hook_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_uuid(cls, hook_uuid) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == hook_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for(cls, purpose=None) -> list[Self]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if purpose:
            q = q.filter(cls.purpose == purpose)
        return q.order_by(cls.created_at.desc()).all()

    @classmethod
    def active_subscriptions(cls) -> list[Self]:
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True), cls.purpose == PURPOSE_SUBSCRIPTION).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        h = cls()
        h.uuid = uuid_lib.uuid4().hex
        cls._apply(h, data)
        h.created_by_id = actor_id
        h.last_updated_by_id = actor_id
        db.session.add(h)
        db.session.commit()
        return h

    def modify(self, data: dict, actor_id=None) -> Self:
        self._apply(self, data)
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def set_secret(self, secret: str):
        self.secret_enc, self.cred_key_id = crypto.encrypt_credential(secret)

    def get_secret(self) -> str | None:
        return crypto.decrypt_credential(self.secret_enc, self.cred_key_id)

    def record_result(self, http_status: int | None, ok: bool):
        from server.model import utcnow
        self.last_status = http_status
        self.last_delivered_at = utcnow()
        self.consecutive_failures = 0 if ok else (self.consecutive_failures + 1)
        if self.consecutive_failures >= FAILURE_CIRCUIT_BREAK:
            self.enabled = False
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def _apply(h, data):
        for f in ('name', 'url', 'headers', 'timeout_ms', 'max_retries', 'verify_tls', 'purpose',
                  'subscription_filter', 'api_token_id', 'enabled'):
            if f in data and data[f] is not None:
                setattr(h, f, data[f])
        if data.get('secret'):
            h.set_secret(data['secret'])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'uuid': self.uuid, 'name': self.name, 'url': self.url,
            'has_secret': bool(self.secret_enc), 'headers': self.headers, 'timeout_ms': self.timeout_ms,
            'max_retries': self.max_retries, 'verify_tls': bool(self.verify_tls), 'purpose': self.purpose,
            'subscription_filter': self.subscription_filter, 'enabled': bool(self.enabled),
            'last_status': self.last_status, 'consecutive_failures': self.consecutive_failures,
            'last_delivered_at': to_epoch_ms(self.last_delivered_at),
        }
