"""Cached remote cameras from federated members (PLAN P8). A local snapshot of each
member's camera list (refreshed on sync) so the hub can render an aggregated grid without
a live round-trip per request. Derived data → no soft delete; replaced wholesale per member.
"""
from typing import Self

from sqlalchemy import Boolean, Column, Index, String, UniqueConstraint

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow


class FederationCamera(SnowflakeMixin, BaseDB):
    __tablename__ = 'federation_cameras'
    __table_args__ = (
        UniqueConstraint('member_id', 'remote_uuid', name='uq_fed_cam_member_remote'),
        Index('idx_fed_cam_member', 'member_id'),
    )

    member_id = Column(BigIntId, nullable=False)
    remote_uuid = Column(String(64), nullable=False)
    name = Column(String(200), nullable=False)
    status = Column(String(16), nullable=True)
    online = Column(Boolean, nullable=False, default=False)
    last_sync_at = Column(DateTime3, nullable=False, default=utcnow)

    @classmethod
    def replace_for_member(cls, member_id: int, cameras: list[dict]) -> int:
        """Swap the member's cached cameras for a fresh snapshot. Returns the new count."""
        db.session.query(cls).filter(cls.member_id == member_id).delete(synchronize_session=False)
        now = utcnow()
        for c in cameras:
            row = cls()
            row.member_id = member_id
            row.remote_uuid = str(c.get('uuid') or '')[:64]
            row.name = str(c.get('name') or '')[:200]
            row.status = (c.get('status') or None)
            row.online = bool(c.get('online'))
            row.last_sync_at = now
            db.session.add(row)
        db.session.commit()
        return len(cameras)

    @classmethod
    def for_members(cls, member_ids: list[int]) -> list[Self]:
        if not member_ids:
            return []
        return (db.session.query(cls).filter(cls.member_id.in_(member_ids))
                .order_by(cls.member_id, cls.name).all())

    @classmethod
    def delete_for_member(cls, member_id: int):
        db.session.query(cls).filter(cls.member_id == member_id).delete(synchronize_session=False)
        db.session.commit()

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'member_id': str(self.member_id),
            'remote_uuid': self.remote_uuid,
            'name': self.name,
            'status': self.status,
            'online': bool(self.online),
            'last_sync_at': to_epoch_ms(self.last_sync_at),
        }
