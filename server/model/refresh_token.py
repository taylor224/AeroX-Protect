from datetime import datetime
from typing import Self

from sqlalchemy import Column, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, utcnow


class RefreshToken(SnowflakeMixin, BaseDB):
    """Active refresh-token families for rotation + reuse (theft) detection.

    Runs alongside the Redis jti denylist: Redis covers fast access-token checks,
    this table tracks the refresh rotation chain so a replayed (already-rotated)
    token can be detected and its whole family revoked.
    """
    __tablename__ = 'refresh_tokens'

    user_id = Column(BigIntId, nullable=False, index=True)
    jti = Column(String(36), nullable=False, unique=True, index=True)
    family_id = Column(String(36), nullable=False, index=True)
    issued_at = Column(DateTime3, nullable=False)
    expires_at = Column(DateTime3, nullable=False, index=True)
    rotated_to_jti = Column(String(36), nullable=True)
    revoked_at = Column(DateTime3, nullable=True)
    user_agent = Column(String(255), nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def create(cls, user_id: int, jti: str, family_id: str, issued_at: datetime,
               expires_at: datetime, user_agent: str | None, ip: str | None) -> Self:
        data = cls()
        data.user_id = user_id
        data.jti = jti
        data.family_id = family_id
        data.issued_at = issued_at
        data.expires_at = expires_at
        data.user_agent = user_agent
        data.ip = ip
        db.session.add(data)
        db.session.commit()
        return data

    @classmethod
    def get_by_jti(cls, jti: str) -> Self | None:
        return db.session.query(cls).filter(cls.jti == jti).first()

    def mark_rotated(self, next_jti: str):
        self.rotated_to_jti = next_jti
        self.revoked_at = utcnow()
        db.session.add(self)
        db.session.commit()

    @classmethod
    def revoke_family(cls, family_id: str):
        """Theft response: revoke every still-active token in a rotation chain."""
        now = utcnow()
        rows = db.session.query(cls).filter(cls.family_id == family_id, cls.revoked_at.is_(None)).all()
        for row in rows:
            row.revoked_at = now
            db.session.add(row)
        db.session.commit()
        return rows

    @classmethod
    def revoke_all_for_user(cls, user_id: int):
        now = utcnow()
        db.session.query(cls).filter(cls.user_id == user_id, cls.revoked_at.is_(None)).update(
            {cls.revoked_at: now}, synchronize_session=False)
        db.session.commit()

    @classmethod
    def delete_expired(cls, before: datetime) -> int:
        deleted = db.session.query(cls).filter(cls.expires_at < before).delete(synchronize_session=False)
        db.session.commit()
        return deleted

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.rotated_to_jti is None and self.expires_at > utcnow()
