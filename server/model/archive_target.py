"""Archive targets (PLAN P6 M2): an off-box destination (S3 / SMB / local) for offloading
protected/event footage. Non-secret config (bucket/prefix/host/path) is plain JSON; access
keys / passwords are Fernet ciphertext (never returned). Mirrors action_target's secret
handling.
"""
import json
from typing import Self

from sqlalchemy import JSON, Boolean, Column, LargeBinary, String, desc

from server.model import AuditMixin, BaseDB, SnowflakeMixin, TimestampMixin, db

TYPE_S3 = 's3'
TYPE_SMB = 'smb'
TYPE_LOCAL = 'local'
TYPES = (TYPE_S3, TYPE_SMB, TYPE_LOCAL)


class ArchiveTarget(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'archive_targets'

    name = Column(String(120), nullable=False)
    type = Column(String(8), nullable=False)
    config = Column(JSON, nullable=True)            # bucket/prefix/region/endpoint (s3); host/share/path (smb); path (local)
    enc_config = Column(LargeBinary, nullable=True)  # Fernet({access_key,secret_key} | {username,password})
    enc_key_id = Column(String(50), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, target_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == target_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(desc(cls.created_at)).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        t = cls()
        t.name = data['name']
        t.type = data['type']
        t.config = data.get('config') or {}
        t.set_secrets(data.get('secrets'))
        t.enabled = data.get('enabled', True)
        t.created_by_id = actor_id
        t.last_updated_by_id = actor_id
        db.session.add(t)
        db.session.commit()
        return t

    def modify(self, data: dict, actor_id=None) -> Self:
        for f in ('name', 'type', 'config', 'enabled'):
            if f in data and data[f] is not None:
                setattr(self, f, data[f])
        if data.get('secrets') is not None:
            self.set_secrets(data['secrets'])
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def set_secrets(self, secrets: dict | None):
        if not secrets:
            return
        from server.util.crypto import encrypt_credential
        self.enc_config, self.enc_key_id = encrypt_credential(json.dumps(secrets))

    def get_secrets(self) -> dict:
        if not self.enc_config:
            return {}
        from server.util.crypto import decrypt_credential
        raw = decrypt_credential(self.enc_config, self.enc_key_id)
        try:
            return json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            return {}

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'name': self.name,
            'type': self.type,
            'config': self.config,
            'has_secrets': self.enc_config is not None,
            'enabled': bool(self.enabled),
        }
