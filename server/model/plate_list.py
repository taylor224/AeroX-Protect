"""License-plate watchlist (PLAN P7 A7). allow/deny entries matched against each read's
folded `plate_key`. Soft-deleted + audited (it's policy data). A `deny` hit raises an `lpr`
event; `allow` is for known/authorized vehicles (suppress or annotate).
"""
from typing import Self

from sqlalchemy import Boolean, Column, String, UniqueConstraint

from server.model import AuditMixin, BaseDB, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

KIND_ALLOW = 'allow'
KIND_DENY = 'deny'
KINDS = (KIND_ALLOW, KIND_DENY)


class PlateListEntry(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'plate_lists'
    __table_args__ = (UniqueConstraint('plate_key', 'kind', name='uq_plate_lists_key_kind'),)

    plate_text = Column(String(24), nullable=False)         # as entered (display)
    plate_key = Column(String(24), nullable=False, index=True)   # folded match key
    kind = Column(String(8), nullable=False, default=KIND_DENY)
    label = Column(String(120), nullable=True)              # "John's car", "stolen", …
    note = Column(String(500), nullable=True)
    action = Column(String(32), nullable=True)              # optional rule hint (open_gate/alert)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, entry_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == entry_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls, kind: str | None = None) -> list[Self]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if kind:
            q = q.filter(cls.kind == kind)
        return q.order_by(cls.created_at.desc()).all()

    @classmethod
    def match(cls, match_key: str) -> Self | None:
        """First enabled entry whose folded key equals the read's folded key (deny wins)."""
        if not match_key:
            return None
        rows = (db.session.query(cls)
                .filter(cls.plate_key == match_key, cls.enabled.is_(True), cls.deleted_at.is_(None))
                .all())
        if not rows:
            return None
        return next((r for r in rows if r.kind == KIND_DENY), rows[0])

    @classmethod
    def create(cls, *, plate_text, plate_key, kind=KIND_DENY, label=None, note=None,
               action=None, actor_id=None) -> Self:
        e = cls()
        e.plate_text, e.plate_key, e.kind = plate_text, plate_key, kind
        e.label, e.note, e.action = label, note, action
        e.created_by_id = e.last_updated_by_id = actor_id
        db.session.add(e)
        db.session.commit()
        return e

    def modify(self, data: dict, actor_id=None) -> Self:
        for f in ('label', 'note', 'action', 'kind'):
            if f in data and data[f] is not None:
                setattr(self, f, data[f])
        if 'enabled' in data:
            self.enabled = bool(data['enabled'])
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self, actor_id=None):
        from server.model import utcnow
        self.deleted_at = utcnow()
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'plate_text': self.plate_text,
            'plate_key': self.plate_key,
            'kind': self.kind,
            'label': self.label,
            'note': self.note,
            'action': self.action,
            'enabled': bool(self.enabled),
            'created_at': to_epoch_ms(self.created_at),
        }
