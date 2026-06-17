"""Remote-portal TURN/STUN configuration (PLAN P9). A single global row holding the ICE
servers handed to WebRTC clients so live/playback works from outside the LAN. The TURN
`auth_secret` (coturn `static-auth-secret`) is Fernet-encrypted and never returned — clients
get short-lived HMAC credentials derived from it, not the secret itself.
"""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import VARBINARY as MYSQL_VARBINARY

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

EncBytes = LargeBinary(512).with_variant(MYSQL_VARBINARY(512), 'mysql')

DEFAULT_STUN = ['stun:stun.l.google.com:19302']
_FIELDS = ('enabled', 'stun_urls', 'turn_host', 'turn_port', 'turn_protocol', 'turn_tls',
           'realm', 'ttl_seconds')


class TurnConfig(SnowflakeMixin, BaseDB):
    __tablename__ = 'turn_config'

    singleton = Column(Boolean, nullable=False, default=True, unique=True)   # exactly one row
    enabled = Column(Boolean, nullable=False, default=False)
    stun_urls = Column(JSON, nullable=True)                 # list[str]
    turn_host = Column(String(255), nullable=True)
    turn_port = Column(Integer, nullable=False, default=3478)
    turn_protocol = Column(String(8), nullable=False, default='udp')   # udp | tcp
    turn_tls = Column(Boolean, nullable=False, default=False)           # turns: (TLS)
    realm = Column(String(120), nullable=True)
    ttl_seconds = Column(Integer, nullable=False, default=3600)
    auth_secret_enc = Column(EncBytes, nullable=True)
    cred_key_id = Column(String(32), nullable=True)
    last_updated_by_id = Column(BigIntId, nullable=True)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    # ── secret (never returned) ───────────────────────────────────────────────
    def set_secret(self, secret: str | None):
        from server.util import crypto
        if secret:
            self.auth_secret_enc, self.cred_key_id = crypto.encrypt_credential(secret)

    def get_secret(self) -> str | None:
        from server.util import crypto
        return crypto.decrypt_credential(self.auth_secret_enc, self.cred_key_id) if self.auth_secret_enc else None

    @property
    def has_secret(self) -> bool:
        return self.auth_secret_enc is not None

    @classmethod
    def get(cls) -> Self | None:
        return db.session.query(cls).filter(cls.singleton.is_(True)).first()

    @classmethod
    def ensure(cls) -> Self:
        row = cls.get()
        if row is None:
            row = cls()
            row.singleton = True
            row.stun_urls = list(DEFAULT_STUN)
            db.session.add(row)
            db.session.commit()
        return row

    @classmethod
    def update(cls, data: dict, actor_id=None) -> Self:
        row = cls.ensure()
        for f in _FIELDS:
            if f in data and data[f] is not None:
                setattr(row, f, data[f])
        if 'auth_secret' in data and data['auth_secret']:
            row.set_secret(data['auth_secret'])
        row.last_updated_by_id = actor_id
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self) -> dict:
        return {
            'enabled': bool(self.enabled),
            'stun_urls': self.stun_urls or list(DEFAULT_STUN),
            'turn_host': self.turn_host,
            'turn_port': self.turn_port,
            'turn_protocol': self.turn_protocol,
            'turn_tls': bool(self.turn_tls),
            'realm': self.realm,
            'ttl_seconds': self.ttl_seconds,
            'has_secret': self.has_secret,
            'updated_at': to_epoch_ms(self.updated_at),
        }
