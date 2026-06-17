import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, String, or_
from sqlalchemy.orm import aliased

from server.exception import RowNotFoundException
from server.model import (
    AuditMixin,
    BaseDB,
    BigIntId,
    SnowflakeMixin,
    TimestampMixin,
    db,
    to_epoch_ms,
    utcnow,
)

RATIO_FIT = 'fit'
RATIO_STRETCH = 'stretch'
RATIO_CROP = 'crop'
RATIO_MODES = (RATIO_FIT, RATIO_STRETCH, RATIO_CROP)


class Dashboard(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'dashboards'

    uuid = Column(String(32), nullable=False, unique=True, index=True, default=lambda: uuid_lib.uuid4().hex)
    name = Column(String(200), nullable=False)
    description = Column(String(512), nullable=True)
    layout = Column(JSON, nullable=False, default=dict)
    owner_id = Column(BigIntId, nullable=False, index=True)
    is_shared = Column(Boolean, nullable=False, default=False)
    default_ratio_mode = Column(String(8), nullable=False, default=RATIO_FIT)

    @classmethod
    def get_by_uuid(cls, dashboard_uuid: str) -> Self:
        data = db.session.query(cls).filter(cls.uuid == dashboard_uuid, cls.deleted_at.is_(None)).first()
        if not data:
            raise RowNotFoundException()
        return data

    @classmethod
    def get_by_id(cls, dashboard_id: int) -> Self | None:
        return db.session.query(cls).filter(cls.id == dashboard_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_accessible(cls, user_id: int, is_admin: bool) -> list[Self]:
        """Dashboards the user owns or has an ACL row for (admin sees all)."""
        if is_admin:
            return db.session.query(cls).filter(cls.deleted_at.is_(None)).order_by(cls.name.asc()).all()
        from server.model.dashboard_acl import DashboardAcl
        acl = aliased(DashboardAcl)
        return (
            db.session.query(cls)
            .outerjoin(acl, (acl.dashboard_id == cls.id) & (acl.user_id == user_id))
            .filter(cls.deleted_at.is_(None), or_(cls.owner_id == user_id, acl.id.isnot(None)))
            .order_by(cls.name.asc())
            .all()
        )

    @classmethod
    def create(cls, name, layout, owner_id, description=None, default_ratio_mode=RATIO_FIT,
               is_shared=False, created_by_id=None) -> Self:
        d = cls()
        d.uuid = uuid_lib.uuid4().hex
        d.name = name
        d.description = description
        d.layout = layout
        d.owner_id = owner_id
        d.is_shared = is_shared
        d.default_ratio_mode = default_ratio_mode
        d.created_by_id = created_by_id
        d.last_updated_by_id = created_by_id
        db.session.add(d)
        db.session.commit()
        return d

    def modify(self, *, name=None, description=None, layout=None, default_ratio_mode=None,
               is_shared=None, updated_by_id=None) -> Self:
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description
        if layout is not None:
            self.layout = layout
        if default_ratio_mode is not None:
            self.default_ratio_mode = default_ratio_mode
        if is_shared is not None:
            self.is_shared = bool(is_shared)
        if updated_by_id is not None:
            self.last_updated_by_id = updated_by_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self, deleted_by_id=None):
        self.deleted_at = utcnow()
        self.last_updated_by_id = deleted_by_id
        db.session.add(self)
        db.session.commit()

    def to_dict(self, with_layout: bool = True, acl: list | None = None) -> dict:
        data = {
            'uuid': self.uuid,
            'name': self.name,
            'description': self.description,
            'owner_id': str(self.owner_id),
            'is_shared': bool(self.is_shared),
            'default_ratio_mode': self.default_ratio_mode,
            'created_at': to_epoch_ms(self.created_at),
            'updated_at': to_epoch_ms(self.updated_at),
        }
        if with_layout:
            data['layout'] = self.layout or {}
        if acl is not None:
            data['acl'] = acl
        return data
