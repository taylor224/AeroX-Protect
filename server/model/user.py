import uuid
from datetime import timedelta
from typing import Self

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import JSON, Boolean, Column, Integer, String, or_
from sqlalchemy.orm import relationship, selectinload

from server.exception import RowNotFoundException
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

_ph = PasswordHasher()


class User(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'users'

    uuid = Column(String(32), nullable=False, unique=True, index=True)
    login_id = Column(String(190), nullable=False, unique=True, index=True)
    password = Column(String(255), nullable=False)                 # Argon2id hash
    name = Column(String(120), nullable=False)
    email = Column(String(190), nullable=True, index=True)
    phone_number = Column(String(40), nullable=True)

    role_id = Column(BigIntId, nullable=False, index=True)          # logical -> roles.id
    permissions = Column(JSON, nullable=False, default=dict)        # per-user overrides

    language = Column(String(10), nullable=False, default='ko')
    is_active = Column(Boolean, nullable=False, default=True)

    failed_login_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime3, nullable=True)
    last_login_at = Column(DateTime3, nullable=True)
    token_version = Column(Integer, nullable=False, default=0)      # bump to invalidate all tokens

    # logical FK relationship (no DB constraint) — eager-loadable via selectinload
    role = relationship(
        'Role',
        primaryjoin='foreign(User.role_id) == Role.id',
        viewonly=True,
        uselist=False,
    )

    # ── password ────────────────────────────────────────────────────────────
    @staticmethod
    def hash_password(raw: str) -> str:
        return _ph.hash(raw)

    def set_password(self, raw: str):
        self.password = _ph.hash(raw)

    def verify_password(self, raw: str) -> bool:
        try:
            return _ph.verify(self.password, raw)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # ── lock / brute-force ──────────────────────────────────────────────────
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > utcnow()

    def register_failed_login(self, max_failed: int, lock_minutes: int) -> bool:
        """Increment fail counter; lock if threshold reached. Returns True if now locked."""
        self.failed_login_count = (self.failed_login_count or 0) + 1
        locked = False
        if self.failed_login_count >= max_failed:
            self.locked_until = utcnow() + timedelta(minutes=lock_minutes)
            self.failed_login_count = 0
            locked = True
        db.session.add(self)
        db.session.commit()
        return locked

    def register_successful_login(self):
        self.failed_login_count = 0
        self.locked_until = None
        self.last_login_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def unlock(self):
        self.locked_until = None
        self.failed_login_count = 0
        db.session.add(self)
        db.session.commit()

    def bump_token_version(self):
        self.token_version = (self.token_version or 0) + 1
        db.session.add(self)
        db.session.commit()

    # ── queries ───────────────────────────────────────────────────────────────
    @classmethod
    def get_by_id(cls, user_id: int) -> Self:
        data = db.session.query(cls).filter(cls.id == user_id, cls.deleted_at.is_(None)).first()
        if not data:
            raise RowNotFoundException()
        return data

    @classmethod
    def get_by_uuid(cls, user_uuid: str) -> Self:
        data = db.session.query(cls).options(selectinload(cls.role)).filter(
            cls.uuid == user_uuid, cls.deleted_at.is_(None)).first()
        if not data:
            raise RowNotFoundException()
        return data

    @classmethod
    def get_by_login_id(cls, login_id: str) -> Self | None:
        return db.session.query(cls).options(selectinload(cls.role)).filter(
            cls.login_id == login_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def count(cls) -> int:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).count()

    @classmethod
    def get_list(cls, page: int, items_per_page: int, q: str | None,
                 sort: str | None, order: str | None) -> tuple[int, list[Self]]:
        query = db.session.query(cls).options(selectinload(cls.role)).filter(cls.deleted_at.is_(None))
        if q:
            like = '%{}%'.format(q)
            query = query.filter(or_(
                cls.login_id.like(like),
                cls.name.like(like),
                cls.email.like(like),
            ))

        sort_col = {'login_id': cls.login_id, 'name': cls.name, 'created_at': cls.created_at}.get(sort, cls.created_at)
        sort_col = sort_col.asc() if order == 'asc' else sort_col.desc()

        total = query.count()
        rows = query.order_by(sort_col).limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    # ── mutations ─────────────────────────────────────────────────────────────
    @classmethod
    def create(cls, login_id: str, password: str, name: str, role_id: int,
               email: str | None = None, phone_number: str | None = None,
               permissions: dict | None = None, language: str = 'ko',
               created_by_id: int | None = None) -> Self:
        data = cls()
        data.uuid = uuid.uuid4().hex
        data.login_id = login_id
        data.set_password(password)
        data.name = name
        data.email = email
        data.phone_number = phone_number
        data.role_id = role_id
        data.permissions = permissions or {}
        data.language = language or 'ko'
        data.is_active = True
        data.failed_login_count = 0
        data.token_version = 0
        data.created_by_id = created_by_id
        data.last_updated_by_id = created_by_id
        db.session.add(data)
        db.session.commit()
        return data

    def modify(self, *, name=None, email=None, phone_number=None, role_id=None,
               permissions=None, is_active=None, language=None, updated_by_id=None) -> Self:
        if name is not None:
            self.name = name
        if email is not None:
            self.email = email
        if phone_number is not None:
            self.phone_number = phone_number
        if role_id is not None:
            self.role_id = role_id
        if permissions is not None:
            self.permissions = permissions
        if is_active is not None:
            self.is_active = bool(is_active)
        if language is not None:
            self.language = language
        if updated_by_id is not None:
            self.last_updated_by_id = updated_by_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self, deleted_by_id: int | None = None):
        self.deleted_at = utcnow()
        self.last_updated_by_id = deleted_by_id
        db.session.add(self)
        db.session.commit()

    # ── serialization (never expose password) ─────────────────────────────────
    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'uuid': self.uuid,
            'login_id': self.login_id,
            'name': self.name,
            'email': self.email,
            'phone_number': self.phone_number,
            'role': self.role.name if self.role else None,
            'role_id': str(self.role_id),
            'permissions': self.permissions or {},
            'language': self.language or 'ko',
            'is_active': bool(self.is_active),
            'locked_until': to_epoch_ms(self.locked_until),
            'last_login_at': to_epoch_ms(self.last_login_at),
            'created_at': to_epoch_ms(self.created_at),
            'updated_at': to_epoch_ms(self.updated_at),
        }
