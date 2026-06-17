"""Automation rule (PLAN P5 §4.1): JSON trigger/condition/actions evaluated when an
event/object/schedule/manual trigger arrives. trigger_type is a column (index-narrowed
candidate set); detail matching is JSON in-memory (rule_evaluator)."""
import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, SmallInteger, String

from server.model import AuditMixin, BaseDB, BigIntId, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

TRIGGER_EVENT = 'event'
TRIGGER_OBJECT = 'object'
TRIGGER_SCHEDULE = 'schedule'
TRIGGER_MANUAL = 'manual'
TRIGGER_SYSTEM = 'system_event'          # device/system lifecycle (camera online/offline, IO input, …)
TRIGGER_INCOMING = 'incoming_webhook'    # fired by an inbound HTTP call to the rule's hook URL
TRIGGER_TYPES = (TRIGGER_EVENT, TRIGGER_OBJECT, TRIGGER_SCHEDULE, TRIGGER_MANUAL,
                 TRIGGER_SYSTEM, TRIGGER_INCOMING)

DEDUP_RULE = 'rule'
DEDUP_CAMERA = 'camera'
DEDUP_TARGET = 'target'


class Rule(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'rules'

    uuid = Column(String(32), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    priority = Column(SmallInteger, nullable=False, default=0)
    stop_on_match = Column(Boolean, nullable=False, default=False)
    trigger_type = Column(String(16), nullable=False)
    trigger = Column(JSON, nullable=False, default=dict)
    condition = Column(JSON, nullable=False, default=dict)
    actions = Column(JSON, nullable=False, default=list)
    cooldown_s = Column(SmallInteger, nullable=False, default=30)
    debounce_s = Column(SmallInteger, nullable=False, default=0)
    dedup_scope = Column(String(16), nullable=False, default=DEDUP_CAMERA)
    max_per_hour = Column(SmallInteger, nullable=True)
    incoming_token = Column(String(40), nullable=True, unique=True, index=True)  # incoming_webhook trigger
    last_triggered_ts = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, rule_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == rule_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_uuid(cls, rule_uuid) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == rule_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def active_for(cls, trigger_type: str) -> list[Self]:
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True), cls.trigger_type == trigger_type
        ).order_by(cls.priority.desc(), cls.id.asc()).all()

    @classmethod
    def get_by_incoming_token(cls, token: str) -> Self | None:
        if not token:
            return None
        return db.session.query(cls).filter(
            cls.incoming_token == token, cls.deleted_at.is_(None),
            cls.trigger_type == TRIGGER_INCOMING).first()

    @classmethod
    def list_rules(cls, *, trigger_type=None, enabled=None, page=1, items_per_page=50) -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if trigger_type:
            q = q.filter(cls.trigger_type == trigger_type)
        if enabled is not None:
            q = q.filter(cls.enabled.is_(bool(enabled)))
        total = q.count()
        rows = q.order_by(cls.priority.desc(), cls.created_at.desc()).limit(items_per_page).offset(
            (page - 1) * items_per_page).all()
        return total, rows

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        r = cls()
        r.uuid = uuid_lib.uuid4().hex
        cls._apply(r, data)
        r._ensure_incoming_token()
        r.created_by_id = actor_id
        r.last_updated_by_id = actor_id
        db.session.add(r)
        db.session.commit()
        return r

    def modify(self, data: dict, actor_id=None) -> Self:
        self._apply(self, data)
        self._ensure_incoming_token()
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def _ensure_incoming_token(self):
        """An incoming_webhook rule needs an unguessable token in its hook URL; other
        trigger types don't keep one."""
        if self.trigger_type == TRIGGER_INCOMING:
            if not self.incoming_token:
                self.incoming_token = uuid_lib.uuid4().hex
        else:
            self.incoming_token = None

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    @staticmethod
    def _apply(r, data):
        for f in ('name', 'description', 'enabled', 'priority', 'stop_on_match', 'trigger_type',
                  'trigger', 'condition', 'actions', 'cooldown_s', 'debounce_s', 'dedup_scope', 'max_per_hour'):
            if f in data and data[f] is not None:
                setattr(r, f, data[f])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'uuid': self.uuid, 'name': self.name, 'description': self.description,
            'enabled': bool(self.enabled), 'priority': self.priority, 'stop_on_match': bool(self.stop_on_match),
            'trigger_type': self.trigger_type, 'trigger': self.trigger, 'condition': self.condition,
            'actions': self.actions, 'cooldown_s': self.cooldown_s, 'debounce_s': self.debounce_s,
            'dedup_scope': self.dedup_scope, 'max_per_hour': self.max_per_hour,
            'incoming_token': self.incoming_token,
            'last_triggered_ts': to_epoch_ms(self.last_triggered_ts), 'created_at': to_epoch_ms(self.created_at),
        }
