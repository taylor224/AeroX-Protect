"""External API token (PLAN P5 §4.10): opaque token (sha256 hash stored, plaintext shown
once), scoped (resource:action subset) + camera intersection, revocable immediately."""
import hashlib
import secrets
import uuid as uuid_lib
from typing import Self

from sqlalchemy import CHAR, JSON, Column, SmallInteger, String

import config
from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

TOKEN_PREFIX = 'axp_'


def hash_token(raw: str) -> str:
    pepper = getattr(config, 'API_TOKEN_PEPPER', config.SECRET_KEY or '')
    return hashlib.sha256((raw + pepper).encode()).hexdigest()


class ApiToken(SnowflakeMixin, AuditMixin, BaseDB):
    __tablename__ = 'api_tokens'

    uuid = Column(String(32), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    token_prefix = Column(CHAR(8), nullable=False)
    token_hash = Column(CHAR(64), nullable=False, unique=True)
    scopes = Column(JSON, nullable=False, default=dict)
    camera_ids = Column(JSON, nullable=True)
    expires_at = Column(DateTime3, nullable=True)
    last_used_at = Column(DateTime3, nullable=True)
    last_ip = Column(String(64), nullable=True)
    revoked_at = Column(DateTime3, nullable=True)
    rate_limit_per_min = Column(SmallInteger, nullable=False, default=120)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    @classmethod
    def get_by_id(cls, token_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == token_id).first()

    @classmethod
    def get_by_uuid(cls, token_uuid) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == token_uuid).first()

    @classmethod
    def get_by_hash(cls, token_hash: str) -> Self | None:
        return db.session.query(cls).filter(cls.token_hash == token_hash).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return db.session.query(cls).order_by(cls.created_at.desc()).all()

    @classmethod
    def issue(cls, name: str, scopes: dict, camera_ids=None, expires_at=None, actor_id=None) -> tuple[Self, str]:
        """Create a token; returns (row, plaintext). Plaintext is shown to the caller once."""
        raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
        t = cls()
        t.uuid = uuid_lib.uuid4().hex
        t.name = name
        t.token_prefix = raw[:8]
        t.token_hash = hash_token(raw)
        t.scopes = scopes or {}
        t.camera_ids = camera_ids
        t.expires_at = expires_at
        t.created_by_id = actor_id
        t.last_updated_by_id = actor_id
        db.session.add(t)
        db.session.commit()
        return t, raw

    def revoke(self):
        self.revoked_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def is_valid(self) -> bool:
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= utcnow():
            return False
        return True

    def touch(self, ip=None):
        self.last_used_at = utcnow()
        if ip:
            self.last_ip = ip
        db.session.add(self)
        db.session.commit()

    def has_scope(self, resource: str, action: str) -> bool:
        actions = (self.scopes or {}).get(resource) or []
        return action in actions or '*' in actions

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'uuid': self.uuid, 'name': self.name, 'token_prefix': self.token_prefix,
            'scopes': self.scopes, 'camera_ids': self.camera_ids, 'expires_at': to_epoch_ms(self.expires_at),
            'last_used_at': to_epoch_ms(self.last_used_at), 'revoked_at': to_epoch_ms(self.revoked_at),
            'rate_limit_per_min': self.rate_limit_per_min, 'created_at': to_epoch_ms(self.created_at),
        }
