"""Access credential (PLAN P10). A badge/card (and optional PIN) assigned to a holder.
`access_group` must match a door's group to open it; `valid_from`/`valid_until` bound
validity. May link to a P7 `FaceIdentity` for unified person management. The PIN is stored
only as a sha256+pepper hash; the card number is an identifier (stored plain). Soft-deleted
+ audited.
"""
import hashlib
from datetime import datetime
from typing import Self

from sqlalchemy import Boolean, Column, String, or_

import config
from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms, utcnow


def hash_pin(pin: str) -> str:
    return hashlib.sha256(('%s:pin:%s' % (config.SECRET_KEY, pin)).encode()).hexdigest()


class AccessCredential(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'access_credentials'

    card_number = Column(String(64), nullable=False, index=True)
    holder_name = Column(String(120), nullable=False)
    identity_id = Column(BigIntId, nullable=True)           # optional link to FaceIdentity
    access_group = Column(String(64), nullable=False, default='default')
    pin_hash = Column(String(64), nullable=True)
    valid_from = Column(DateTime3, nullable=True)
    valid_until = Column(DateTime3, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, cred_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == cred_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def find_by_card(cls, card_number: str) -> Self | None:
        # normalize like create() stores it — otherwise a >64-char card never matches
        normalized = str(card_number or '').strip()[:64]
        return db.session.query(cls).filter(
            cls.card_number == normalized, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls, q: str | None = None) -> list[Self]:
        query = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if q:
            like = '%{}%'.format(q)
            query = query.filter(or_(cls.holder_name.like(like), cls.card_number.like(like)))
        return query.order_by(cls.holder_name.asc()).all()

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        c = cls()
        c.card_number = str(data['card_number']).strip()[:64]
        c.holder_name = data['holder_name']
        c.identity_id = data.get('identity_id')
        c.access_group = data.get('access_group') or 'default'
        c.pin_hash = hash_pin(str(data['pin'])) if data.get('pin') else None
        c.valid_from = data.get('valid_from')
        c.valid_until = data.get('valid_until')
        c.created_by_id = c.last_updated_by_id = actor_id
        db.session.add(c)
        db.session.commit()
        return c

    def modify(self, data: dict, actor_id=None) -> Self:
        for f in ('holder_name', 'identity_id', 'access_group'):
            if f in data and data[f] is not None:
                setattr(self, f, data[f])
        for f in ('valid_from', 'valid_until'):     # nullable — present key clears (lifts expiry)
            if f in data:
                setattr(self, f, data[f])
        if 'pin' in data:
            self.pin_hash = hash_pin(str(data['pin'])) if data['pin'] else None
        if 'enabled' in data:
            self.enabled = bool(data['enabled'])
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def verify_pin(self, pin: str | None) -> bool:
        if self.pin_hash is None:
            return True                       # no PIN set on this credential
        return pin is not None and hash_pin(str(pin)) == self.pin_hash

    def is_valid_at(self, now: datetime) -> bool:
        if self.valid_from is not None and now < self.valid_from:
            return False
        if self.valid_until is not None and now > self.valid_until:
            return False
        return True

    def soft_delete(self, actor_id=None):
        self.deleted_at = utcnow()
        self.enabled = False
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'card_number': self.card_number,
            'holder_name': self.holder_name,
            'identity_id': str(self.identity_id) if self.identity_id else None,
            'access_group': self.access_group,
            'has_pin': self.pin_hash is not None,
            'valid_from': to_epoch_ms(self.valid_from),
            'valid_until': to_epoch_ms(self.valid_until),
            'enabled': bool(self.enabled),
            'created_at': to_epoch_ms(self.created_at),
        }
