"""Share links (PLAN P6 R1): a scoped, revocable public link to one clip/event. The
public URL carries an opaque token; only `sha256(token)` is stored (plaintext shown once,
api_token pattern). Access is bounded by expiry / max_views / optional password / revoke —
the token grants ONLY that resource, never any other API (PLAN §13).
"""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Self

from sqlalchemy import Boolean, Column, Integer, String, desc, func

import config
from server.model import (
    AuditMixin,
    BaseDB,
    BigIntId,
    DateTime3,
    SnowflakeMixin,
    TimestampMixin,
    db,
    to_epoch_ms,
    utcnow,
)

KIND_CLIP = 'clip'    # camera + [range_start, range_end]
KIND_EVENT = 'event'  # an event (camera + its clip window)
KINDS = {KIND_CLIP, KIND_EVENT}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(pw: str) -> str:
    # secondary gate on an already-secret, short-lived token → sha256 + app pepper.
    return hashlib.sha256(('%s:%s' % (config.SECRET_KEY, pw)).encode()).hexdigest()


class ShareLink(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'share_links'

    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    kind = Column(String(16), nullable=False)
    camera_id = Column(BigIntId, nullable=False)
    target_ref = Column(String(64), nullable=True)        # event id when kind=event
    range_start = Column(DateTime3, nullable=True)
    range_end = Column(DateTime3, nullable=True)
    label = Column(String(200), nullable=True)
    password_hash = Column(String(64), nullable=True)
    watermark = Column(Boolean, nullable=False, default=False)
    max_views = Column(Integer, nullable=True)
    view_count = Column(Integer, nullable=False, default=0)
    expires_at = Column(DateTime3, nullable=True)
    revoked_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_hash(cls, token_hash: str) -> Self | None:
        return db.session.query(cls).filter(cls.token_hash == token_hash, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_id(cls, share_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == share_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for_user(cls, user_id: int | None) -> list[Self]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if user_id is not None:
            q = q.filter(cls.created_by_id == user_id)
        return q.order_by(desc(cls.created_at)).all()

    @classmethod
    def create(cls, *, kind: str, camera_id: int, token_hash: str, target_ref=None,
               range_start=None, range_end=None, label=None, password_hash=None,
               watermark=False, max_views=None, expires_at=None, actor_id=None) -> Self:
        s = cls()
        s.kind = kind
        s.camera_id = camera_id
        s.token_hash = token_hash
        s.target_ref = target_ref
        s.range_start = range_start
        s.range_end = range_end
        s.label = label
        s.password_hash = password_hash
        s.watermark = bool(watermark)
        s.max_views = max_views
        s.expires_at = expires_at
        s.created_by_id = actor_id
        s.last_updated_by_id = actor_id
        db.session.add(s)
        db.session.commit()
        return s

    # ── state ──────────────────────────────────────────────────────────────────
    def is_live(self, now: datetime | None = None) -> bool:
        now = now or utcnow()
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        if self.max_views is not None and (self.view_count or 0) >= self.max_views:
            return False
        return True

    def status_reason(self, now: datetime | None = None) -> str | None:
        now = now or utcnow()
        if self.revoked_at is not None:
            return 'revoked'
        if self.expires_at is not None and self.expires_at <= now:
            return 'expired'
        if self.max_views is not None and (self.view_count or 0) >= self.max_views:
            return 'exhausted'
        return None

    def register_view(self):
        # atomic UPDATE — a read-modify-write here loses counts under concurrent
        # public views, letting a max_views link be opened more than allowed
        cls = type(self)
        db.session.query(cls).filter(cls.id == self.id).update(
            {cls.view_count: func.coalesce(cls.view_count, 0) + 1}, synchronize_session=False)
        db.session.commit()
        db.session.refresh(self)

    def revoke(self, actor_id=None):
        self.revoked_at = utcnow()
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()

    # ── serialization (owner view — never includes the token or any hash) ───────
    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'kind': self.kind,
            'camera_id': str(self.camera_id),
            'target_ref': self.target_ref,
            'range_start': to_epoch_ms(self.range_start),
            'range_end': to_epoch_ms(self.range_end),
            'label': self.label,
            'has_password': self.password_hash is not None,
            'watermark': bool(self.watermark),
            'max_views': self.max_views,
            'view_count': self.view_count,
            'expires_at': to_epoch_ms(self.expires_at),
            'revoked_at': to_epoch_ms(self.revoked_at),
            'status': self.status_reason() or 'active',
            'created_at': to_epoch_ms(self.created_at),
        }

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(24)

    @staticmethod
    def default_expiry(seconds: int) -> datetime:
        return utcnow() + timedelta(seconds=seconds)
