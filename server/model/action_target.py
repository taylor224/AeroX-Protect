"""Action target registry (PLAN P5 §4.3): speaker / io / email endpoints. Credentials are
Fernet-encrypted (util.crypto); never returned in DTOs."""
import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, LargeBinary, String

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms
from server.util import crypto

TYPE_SPEAKER = 'speaker'
TYPE_IO = 'io'
TYPE_EMAIL = 'email'
TYPES = (TYPE_SPEAKER, TYPE_IO, TYPE_EMAIL)


class ActionTarget(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'action_targets'

    uuid = Column(String(32), nullable=False, unique=True)
    type = Column(String(16), nullable=False)
    name = Column(String(120), nullable=False)
    vendor = Column(String(40), nullable=True)
    protocol = Column(String(24), nullable=False)
    host = Column(String(190), nullable=True)
    port = Column(Integer, nullable=True)
    config = Column(JSON, nullable=False, default=dict)
    username_enc = Column(LargeBinary(512), nullable=True)
    password_enc = Column(LargeBinary(512), nullable=True)
    cred_key_id = Column(String(16), nullable=True)
    camera_id = Column(BigIntId, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    status = Column(String(16), nullable=False, default='unknown')
    last_checked_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, target_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == target_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_uuid(cls, target_uuid) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == target_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for(cls, type_filter=None) -> list[Self]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if type_filter:
            q = q.filter(cls.type == type_filter)
        return q.order_by(cls.type.asc(), cls.name.asc()).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        t = cls()
        t.uuid = uuid_lib.uuid4().hex
        cls._apply(t, data)
        t.created_by_id = actor_id
        t.last_updated_by_id = actor_id
        db.session.add(t)
        db.session.commit()
        return t

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

    def set_credentials(self, username: str | None, password: str | None):
        if username is not None:
            self.username_enc, self.cred_key_id = crypto.encrypt_credential(username)
        if password is not None:
            self.password_enc, kid = crypto.encrypt_credential(password)
            self.cred_key_id = kid

    def get_credentials(self) -> tuple[str | None, str | None]:
        return (crypto.decrypt_credential(self.username_enc, self.cred_key_id),
                crypto.decrypt_credential(self.password_enc, self.cred_key_id))

    @staticmethod
    def _apply(t, data):
        for f in ('type', 'name', 'vendor', 'protocol', 'host', 'port', 'config', 'camera_id', 'enabled'):
            if f in data and data[f] is not None:
                setattr(t, f, data[f])
        if 'username' in data or 'password' in data:
            t.set_credentials(data.get('username'), data.get('password'))

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'uuid': self.uuid, 'type': self.type, 'name': self.name,
            'vendor': self.vendor, 'protocol': self.protocol, 'host': self.host, 'port': self.port,
            'config': self.config, 'camera_id': str(self.camera_id) if self.camera_id else None,
            'enabled': bool(self.enabled), 'status': self.status,
            'has_credentials': bool(self.password_enc), 'last_checked_at': to_epoch_ms(self.last_checked_at),
        }
