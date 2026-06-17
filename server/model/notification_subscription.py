"""Per-user notification subscription + policy (PLAN P5 §4.7): channel filters, priority
floor, mute/snooze, batching window, quiet hours (KST)."""
from datetime import datetime
from typing import Self

from sqlalchemy import JSON, Boolean, Column, SmallInteger, String

from server.model import UTC, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db

CHANNEL_PUSH = 'push'
CHANNEL_EMAIL = 'email'
CHANNEL_WEBHOOK = 'webhook'
CHANNEL_INAPP = 'inapp'
CHANNEL_SMS = 'sms'                                       # P6 N1 — Twilio
CHANNELS = (CHANNEL_PUSH, CHANNEL_EMAIL, CHANNEL_WEBHOOK, CHANNEL_INAPP, CHANNEL_SMS)

PRIORITY_RANK = {'low': 0, 'normal': 1, 'high': 2, 'critical': 3}


class NotificationSubscription(SnowflakeMixin, TimestampMixin, BaseDB):
    __tablename__ = 'notification_subscriptions'

    user_id = Column(BigIntId, nullable=False)
    channel = Column(String(16), nullable=False)
    event_types = Column(JSON, nullable=True)
    camera_ids = Column(JSON, nullable=True)
    object_classes = Column(JSON, nullable=True)
    min_priority = Column(String(8), nullable=False, default='normal')
    muted = Column(Boolean, nullable=False, default=False)
    muted_until = Column(DateTime3, nullable=True)
    batch_window_s = Column(SmallInteger, nullable=False, default=0)
    quiet_hours = Column(JSON, nullable=True)
    webhook_endpoint_id = Column(BigIntId, nullable=True)
    sms_to = Column(String(32), nullable=True)           # P6 N1 — recipient phone (E.164)
    enabled = Column(Boolean, nullable=False, default=True)

    @classmethod
    def get_by_id(cls, sub_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == sub_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_for_user(cls, user_id: int) -> list[Self]:
        return db.session.query(cls).filter(
            cls.user_id == user_id, cls.deleted_at.is_(None)).order_by(cls.channel.asc()).all()

    @classmethod
    def active_all(cls) -> list[Self]:
        """All enabled subscriptions across users (router matches in memory)."""
        return db.session.query(cls).filter(cls.deleted_at.is_(None), cls.enabled.is_(True)).all()

    @classmethod
    def create(cls, user_id: int, data: dict) -> Self:
        s = cls()
        s.user_id = user_id
        cls._apply(s, data)
        db.session.add(s)
        db.session.commit()
        return s

    def modify(self, data: dict) -> Self:
        self._apply(self, data)
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def _apply(s, data):
        for f in ('channel', 'event_types', 'camera_ids', 'object_classes', 'min_priority', 'muted',
                  'batch_window_s', 'quiet_hours', 'webhook_endpoint_id', 'sms_to', 'enabled'):
            if f in data and data[f] is not None:
                setattr(s, f, data[f])
        if 'muted_until' in data:                # explicit null clears the snooze
            s.muted_until = s._coerce_dt(data['muted_until'])

    @staticmethod
    def _coerce_dt(value):
        """API clients send epoch ms; the column is a naive-UTC DATETIME."""
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)

    def to_dict(self) -> dict:
        from server.model import to_epoch_ms
        return {
            'id': str(self.id), 'channel': self.channel, 'event_types': self.event_types,
            'camera_ids': self.camera_ids, 'object_classes': self.object_classes,
            'min_priority': self.min_priority, 'muted': bool(self.muted),
            'muted_until': to_epoch_ms(self.muted_until), 'batch_window_s': self.batch_window_s,
            'quiet_hours': self.quiet_hours,
            'webhook_endpoint_id': str(self.webhook_endpoint_id) if self.webhook_endpoint_id else None,
            'sms_to': self.sms_to,
            'enabled': bool(self.enabled),
        }
