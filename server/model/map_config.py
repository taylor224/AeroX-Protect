"""Map provider configuration (P6 L6 maps). A single global row choosing the geo base
layer: OpenStreetMap (default, key-less) or Google Maps. The Google Maps JS API key is a
client-side key (HTTP-referrer restricted) that the browser SDK needs, so unlike the TURN
secret it IS returned to authenticated map users — but stored Fernet-encrypted at rest.
"""
from typing import Self

from sqlalchemy import Boolean, Column, LargeBinary, String
from sqlalchemy.dialects.mysql import VARBINARY as MYSQL_VARBINARY

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

EncBytes = LargeBinary(512).with_variant(MYSQL_VARBINARY(512), 'mysql')

PROVIDER_OSM = 'osm'
PROVIDER_GOOGLE = 'google'
PROVIDERS = (PROVIDER_OSM, PROVIDER_GOOGLE)


class MapConfig(SnowflakeMixin, BaseDB):
    __tablename__ = 'map_config'

    singleton = Column(Boolean, nullable=False, default=True, unique=True)   # exactly one row
    provider = Column(String(16), nullable=False, default=PROVIDER_OSM)
    google_api_key_enc = Column(EncBytes, nullable=True)
    cred_key_id = Column(String(32), nullable=True)
    last_updated_by_id = Column(BigIntId, nullable=True)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)

    def set_key(self, key: str | None):
        from server.util import crypto
        if key:
            self.google_api_key_enc, self.cred_key_id = crypto.encrypt_credential(key)
        else:                                  # empty string clears the stored key
            self.google_api_key_enc, self.cred_key_id = None, None

    def get_key(self) -> str | None:
        from server.util import crypto
        return crypto.decrypt_credential(self.google_api_key_enc, self.cred_key_id) if self.google_api_key_enc else None

    @property
    def has_key(self) -> bool:
        return self.google_api_key_enc is not None

    @classmethod
    def get(cls) -> Self | None:
        return db.session.query(cls).filter(cls.singleton.is_(True)).first()

    @classmethod
    def ensure(cls) -> Self:
        row = cls.get()
        if row is None:
            row = cls()
            row.singleton = True
            row.provider = PROVIDER_OSM
            db.session.add(row)
            db.session.commit()
        return row

    @classmethod
    def update(cls, data: dict, actor_id=None) -> Self:
        row = cls.ensure()
        if data.get('provider') in PROVIDERS:
            row.provider = data['provider']
        if 'google_api_key' in data:           # present key (incl. '') sets/clears it
            row.set_key(data['google_api_key'])
        row.last_updated_by_id = actor_id
        db.session.add(row)
        db.session.commit()
        return row

    def to_dict(self, with_key: bool = False) -> dict:
        out = {
            'provider': self.provider,
            'has_key': self.has_key,
            'updated_at': to_epoch_ms(self.updated_at),
        }
        if with_key:
            out['google_api_key'] = self.get_key()       # client SDK needs the key
        return out
