"""Known-face registry (PLAN P7 A8 — `persons`). A named identity with one-or-more
reference face embeddings; observed faces are matched against these by cosine similarity.
Privacy-sensitive (PLAN §435): carries an explicit `consent` flag + soft delete (right to
erasure). Raw embeddings are NOT returned in to_dict (only counts/metadata).
"""
from typing import Self

from sqlalchemy import JSON, Boolean, Column, Integer, String

from server.model import AuditMixin, BaseDB, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms, utcnow


class FaceIdentity(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'face_identities'

    name = Column(String(120), nullable=False)
    note = Column(String(500), nullable=True)
    external_ref = Column(String(64), nullable=True)        # link to an HR/visitor id
    consent = Column(Boolean, nullable=False, default=False)  # explicit enrollment consent
    consent_at = Column(DateTime3, nullable=True)
    retention_days = Column(Integer, nullable=True)          # null = keep until erased
    enabled = Column(Boolean, nullable=False, default=True)
    backend = Column(String(16), nullable=True)             # embedder tag (must match to compare)
    dim = Column(Integer, nullable=True)
    embeddings = Column(JSON, nullable=True)                # list[list[float]] reference vectors

    @classmethod
    def get_by_id(cls, identity_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == identity_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_all(cls) -> list[Self]:
        return (db.session.query(cls).filter(cls.deleted_at.is_(None))
                .order_by(cls.name.asc()).all())

    @classmethod
    def list_enabled_with_embeddings(cls) -> list[Self]:
        """Match pool. Consent is required — a revoked identity must stop matching
        immediately, not only at enrollment time."""
        return (db.session.query(cls)
                .filter(cls.deleted_at.is_(None), cls.enabled.is_(True),
                        cls.consent.is_(True), cls.embeddings.isnot(None))
                .all())

    @classmethod
    def create(cls, *, name, note=None, consent=False, retention_days=None, actor_id=None) -> Self:
        e = cls()
        e.name, e.note, e.consent = name, note, bool(consent)
        e.consent_at = utcnow() if consent else None
        e.retention_days = retention_days
        e.created_by_id = e.last_updated_by_id = actor_id
        db.session.add(e)
        db.session.commit()
        return e

    def modify(self, data: dict, actor_id=None) -> Self:
        for f in ('name', 'note', 'external_ref', 'retention_days'):
            if f in data and data[f] is not None:
                setattr(self, f, data[f])
        if 'enabled' in data:
            self.enabled = bool(data['enabled'])
        if 'consent' in data:
            self.consent = bool(data['consent'])
            self.consent_at = utcnow() if self.consent else None
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def add_embedding(self, vector: list[float], backend: str, dim: int) -> Self:
        """Append a reference embedding. The first one fixes backend/dim; later ones must match."""
        if self.backend and (self.backend != backend or self.dim != dim):
            raise ValueError('embedding backend/dim mismatch')
        self.backend, self.dim = backend, dim
        self.embeddings = (self.embeddings or []) + [list(vector)]
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self, actor_id=None):
        self.deleted_at = utcnow()
        self.embeddings = None          # erase biometric data on delete (right to erasure)
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'name': self.name,
            'note': self.note,
            'external_ref': self.external_ref,
            'consent': bool(self.consent),
            'consent_at': to_epoch_ms(self.consent_at),
            'retention_days': self.retention_days,
            'enabled': bool(self.enabled),
            'backend': self.backend,
            'embedding_count': len(self.embeddings or []),    # never expose raw vectors
            'created_at': to_epoch_ms(self.created_at),
        }
