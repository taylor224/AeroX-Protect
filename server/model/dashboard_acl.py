from typing import Self

from sqlalchemy import Column, String, UniqueConstraint

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, utcnow

ACCESS_VIEW = 'view'
ACCESS_EDIT = 'edit'


class DashboardAcl(SnowflakeMixin, BaseDB):
    __tablename__ = 'dashboard_acl'
    __table_args__ = (UniqueConstraint('dashboard_id', 'user_id', name='uq_dacl'),)

    dashboard_id = Column(BigIntId, nullable=False, index=True)
    user_id = Column(BigIntId, nullable=False, index=True)
    access = Column(String(8), nullable=False, default=ACCESS_VIEW)   # view/edit
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def get_access(cls, dashboard_id: int, user_id: int) -> str | None:
        row = db.session.query(cls).filter(
            cls.dashboard_id == dashboard_id, cls.user_id == user_id).first()
        return row.access if row else None

    @classmethod
    def list_for_dashboard(cls, dashboard_id: int) -> list[Self]:
        return db.session.query(cls).filter(cls.dashboard_id == dashboard_id).all()

    @classmethod
    def upsert(cls, dashboard_id: int, user_id: int, access: str) -> Self:
        row = db.session.query(cls).filter(
            cls.dashboard_id == dashboard_id, cls.user_id == user_id).first()
        if not row:
            row = cls()
            row.dashboard_id = dashboard_id
            row.user_id = user_id
        row.access = access
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def remove(cls, dashboard_id: int, user_id: int):
        db.session.query(cls).filter(
            cls.dashboard_id == dashboard_id, cls.user_id == user_id).delete(synchronize_session=False)
        db.session.commit()

    @classmethod
    def delete_for_dashboard(cls, dashboard_id: int):
        db.session.query(cls).filter(cls.dashboard_id == dashboard_id).delete(synchronize_session=False)
        db.session.commit()

    def to_dict(self) -> dict:
        return {'user_id': str(self.user_id), 'access': self.access}
