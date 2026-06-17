"""Federated member NVR (PLAN P8 — multi-NVR). A hub registers other AeroXProtect
instances and aggregates their cameras/events by calling each member's P5 external API
(`/api/v1/ext/*`) with a per-member opaque api_token. The token is Fernet-encrypted at
rest (never returned in to_dict — only `has_token`). Soft-deleted + audited.
"""
from typing import Self

from sqlalchemy import Boolean, Column, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import VARBINARY as MYSQL_VARBINARY

from server.model import AuditMixin, BaseDB, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms, utcnow

EncBytes = LargeBinary(512).with_variant(MYSQL_VARBINARY(512), 'mysql')

STATUS_UNKNOWN = 'unknown'
STATUS_ONLINE = 'online'
STATUS_OFFLINE = 'offline'
STATUS_ERROR = 'error'


class FederationMember(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'federation_members'

    name = Column(String(120), nullable=False)
    base_url = Column(String(300), nullable=False)          # e.g. https://site-b.example.com
    token_enc = Column(EncBytes, nullable=True)
    cred_key_id = Column(String(32), nullable=True)
    status = Column(String(16), nullable=False, default=STATUS_UNKNOWN)
    last_sync_at = Column(DateTime3, nullable=True)
    last_error = Column(String(500), nullable=True)
    camera_count = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)

    # ── token (never returned) ────────────────────────────────────────────────
    def set_token(self, token: str | None):
        from server.util import crypto
        if token:
            self.token_enc, self.cred_key_id = crypto.encrypt_credential(token)

    def get_token(self) -> str | None:
        from server.util import crypto
        return crypto.decrypt_credential(self.token_enc, self.cred_key_id) if self.token_enc else None

    @property
    def has_token(self) -> bool:
        return self.token_enc is not None

    # ── queries ───────────────────────────────────────────────────────────────
    @classmethod
    def get_by_id(cls, member_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == member_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return (db.session.query(cls).filter(cls.deleted_at.is_(None))
                .order_by(cls.name.asc()).all())

    @classmethod
    def list_enabled(cls) -> list[Self]:
        return (db.session.query(cls)
                .filter(cls.deleted_at.is_(None), cls.enabled.is_(True)).all())

    # ── mutations ─────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, *, name, base_url, token=None, actor_id=None) -> Self:
        m = cls()
        m.name, m.base_url = name, base_url.rstrip('/')
        m.set_token(token)
        m.created_by_id = m.last_updated_by_id = actor_id
        db.session.add(m)
        db.session.commit()
        return m

    def modify(self, data: dict, actor_id=None) -> Self:
        if data.get('name'):
            self.name = data['name']
        if data.get('base_url'):
            self.base_url = data['base_url'].rstrip('/')
        if data.get('token'):
            self.set_token(data['token'])
        if 'enabled' in data:
            self.enabled = bool(data['enabled'])
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def mark_sync(self, status, camera_count=None, error=None):
        self.status = status
        self.last_sync_at = utcnow()
        if camera_count is not None:
            self.camera_count = camera_count
        self.last_error = (error[:500] if error else None)
        db.session.add(self)
        db.session.commit()

    def soft_delete(self, actor_id=None):
        self.deleted_at = utcnow()
        self.enabled = False
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'name': self.name,
            'base_url': self.base_url,
            'has_token': self.has_token,
            'status': self.status,
            'last_sync_at': to_epoch_ms(self.last_sync_at),
            'last_error': self.last_error,
            'camera_count': self.camera_count,
            'enabled': bool(self.enabled),
            'created_at': to_epoch_ms(self.created_at),
        }
