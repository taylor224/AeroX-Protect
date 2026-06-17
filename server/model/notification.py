"""In-app notification + delivery record (PLAN P5 §4.9), high-frequency. The in-app center
polls these; channels_sent records push/email/webhook outcomes."""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, String

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow


class Notification(SnowflakeMixin, BaseDB):
    __tablename__ = 'notifications'

    user_id = Column(BigIntId, nullable=False)
    event_id = Column(BigIntId, nullable=True)
    rule_id = Column(BigIntId, nullable=True)
    camera_id = Column(BigIntId, nullable=True)
    type = Column(String(32), nullable=False)
    priority = Column(String(8), nullable=False, default='normal')
    title = Column(String(200), nullable=False)
    body = Column(String(500), nullable=True)
    snapshot_path = Column(String(512), nullable=True)
    deeplink = Column(String(255), nullable=True)
    channels_sent = Column(JSON, nullable=True)
    read_at = Column(DateTime3, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    deleted_at = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, notif_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == notif_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def create(cls, **fields) -> Self:
        n = cls()
        for k, v in fields.items():
            setattr(n, k, v)
        db.session.add(n)
        db.session.commit()
        return n

    @classmethod
    def list_for_user(cls, user_id: int, unread_only=False, page=1, items_per_page=30) -> tuple[int, int, list[Self]]:
        base = db.session.query(cls).filter(cls.user_id == user_id, cls.deleted_at.is_(None))
        unread = base.filter(cls.read_at.is_(None)).count()
        q = base.filter(cls.read_at.is_(None)) if unread_only else base
        total = q.count()
        rows = q.order_by(cls.created_at.desc()).limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, unread, rows

    @classmethod
    def mark_read(cls, notif_id: int, user_id: int) -> bool:
        n = db.session.query(cls).filter(cls.id == notif_id, cls.user_id == user_id).update(
            {cls.read_at: utcnow()}, synchronize_session=False)
        db.session.commit()
        return n == 1

    @classmethod
    def mark_all_read(cls, user_id: int) -> int:
        n = db.session.query(cls).filter(
            cls.user_id == user_id, cls.read_at.is_(None), cls.deleted_at.is_(None)).update(
            {cls.read_at: utcnow()}, synchronize_session=False)
        db.session.commit()
        return n

    @classmethod
    def purge_older_than(cls, cutoff: datetime) -> int:
        n = db.session.query(cls).filter(cls.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return n

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'event_id': str(self.event_id) if self.event_id else None,
            'rule_id': str(self.rule_id) if self.rule_id else None,
            'camera_id': str(self.camera_id) if self.camera_id else None, 'type': self.type,
            'priority': self.priority, 'title': self.title, 'body': self.body,
            'deeplink': self.deeplink, 'channels_sent': self.channels_sent,
            'read_at': to_epoch_ms(self.read_at), 'created_at': to_epoch_ms(self.created_at),
        }
