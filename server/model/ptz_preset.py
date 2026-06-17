from typing import Self

from sqlalchemy import Column, Integer, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, utcnow


class PtzPreset(SnowflakeMixin, BaseDB):
    """Label/order cache for PTZ presets — presets live in camera firmware; this
    table only mirrors token→name for display (PLAN P1 §4.5)."""
    __tablename__ = 'ptz_presets'

    camera_id = Column(BigIntId, nullable=False, index=True)
    ptz_token = Column(String(64), nullable=True)
    name = Column(String(128), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime3, nullable=False, default=utcnow)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_camera(cls, camera_id: int) -> list[Self]:
        return db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.deleted_at.is_(None)).order_by(cls.sort_order.asc()).all()

    @classmethod
    def upsert(cls, camera_id: int, ptz_token: str, name: str, sort_order: int = 0) -> Self:
        row = db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.ptz_token == ptz_token, cls.deleted_at.is_(None)).first()
        if not row:
            row = cls()
            row.camera_id = camera_id
            row.ptz_token = ptz_token
        row.name = name
        row.sort_order = sort_order
        db.session.add(row)
        db.session.commit()
        return row

    @classmethod
    def remove(cls, camera_id: int, ptz_token: str):
        db.session.query(cls).filter(
            cls.camera_id == camera_id, cls.ptz_token == ptz_token).update(
            {cls.deleted_at: utcnow()}, synchronize_session=False)
        db.session.commit()

    def to_dict(self) -> dict:
        return {'token': self.ptz_token, 'name': self.name, 'sort_order': self.sort_order}
