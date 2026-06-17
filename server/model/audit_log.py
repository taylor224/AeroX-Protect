from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Column, String, or_

from server.model import BaseDB, BigIntId, DateTime3, SnowflakeMixin, db, to_epoch_ms, utcnow

# action vocabulary (security + access log, unified)
ACTION_LOGIN_SUCCESS = 'login_success'
ACTION_LOGIN_FAILED = 'login_failed'
ACTION_LOGOUT = 'logout'
ACTION_TOKEN_REFRESH = 'token_refresh'
ACTION_TOKEN_REUSE = 'token_reuse_detected'
ACTION_ACCOUNT_LOCKED = 'account_locked'
ACTION_PASSWORD_CHANGED = 'password_changed'
ACTION_PERMISSION_DENIED = 'permission_denied'
ACTION_USER_CREATED = 'user_created'
ACTION_USER_UPDATED = 'user_updated'
ACTION_USER_DELETED = 'user_deleted'
ACTION_ROLE_UPDATED = 'role_updated'


class AuditLog(SnowflakeMixin, BaseDB):
    __tablename__ = 'audit_logs'

    action = Column(String(80), nullable=False, index=True)
    target = Column(String(190), nullable=True, index=True)
    user_id = Column(BigIntId, nullable=True, index=True)
    method = Column(String(10), nullable=True)
    path = Column(String(500), nullable=True)
    ip = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime3, nullable=False, default=utcnow, index=True)

    @classmethod
    def record(cls, action: str, target: str | None = None, user_id: int | None = None,
               method: str | None = None, path: str | None = None, ip: str | None = None,
               user_agent: str | None = None, detail: dict | None = None) -> Self:
        data = cls()
        data.action = action
        data.target = target
        data.user_id = user_id
        data.method = method
        data.path = path
        data.ip = ip
        data.user_agent = (user_agent or '')[:255] or None
        data.detail = detail
        db.session.add(data)
        db.session.commit()
        return data

    @classmethod
    def count_recent(cls, action: str, target: str, since: datetime) -> int:
        return db.session.query(cls).filter(
            cls.action == action, cls.target == target, cls.created_at >= since).count()

    @classmethod
    def get_list(cls, page: int, items_per_page: int, action: str | None, q: str | None,
                 date_from: datetime | None, date_to: datetime | None) -> tuple[int, list[Self]]:
        query = db.session.query(cls)
        if action:
            query = query.filter(cls.action == action)
        if q:
            like = '%{}%'.format(q)
            query = query.filter(or_(cls.target.like(like), cls.path.like(like)))
        if date_from:
            query = query.filter(cls.created_at >= date_from)
        if date_to:
            query = query.filter(cls.created_at <= date_to)

        total = query.count()
        rows = query.order_by(cls.created_at.desc()).limit(items_per_page).offset((page - 1) * items_per_page).all()
        return total, rows

    def to_dict(self) -> dict:
        return {
            'id': str(self.id),
            'action': self.action,
            'target': self.target,
            'user_id': str(self.user_id) if self.user_id else None,
            'method': self.method,
            'path': self.path,
            'ip': self.ip,
            'user_agent': self.user_agent,
            'detail': self.detail,
            'created_at': to_epoch_ms(self.created_at),
        }
