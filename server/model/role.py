from typing import Self

from sqlalchemy import JSON, Boolean, Column, String

from server.exception import RowNotFoundException
from server.model import AuditMixin, BaseDB, SnowflakeMixin, TimestampMixin, db


class Role(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'roles'

    name = Column(String(50), nullable=False, unique=True, index=True)   # admin / user
    display_name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    permissions = Column(JSON, nullable=False, default=dict)             # base permission map
    is_system = Column(Boolean, nullable=False, default=False)           # system roles can't be deleted

    @classmethod
    def get_by_id(cls, role_id: int) -> Self:
        data = db.session.query(cls).filter(cls.id == role_id, cls.deleted_at.is_(None)).first()
        if not data:
            raise RowNotFoundException()
        return data

    @classmethod
    def get_by_name(cls, name: str) -> Self | None:
        return db.session.query(cls).filter(cls.name == name, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_all(cls) -> list[Self]:
        return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(cls.name.asc()).all()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'permissions': self.permissions or {},
            'is_system': bool(self.is_system),
        }
