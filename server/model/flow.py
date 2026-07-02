"""Automation flow — a visual node graph (n8n-style) designed in the flow editor.
`graph` holds the canvas verbatim ({nodes, edges}); execution starts at trigger node(s)
and walks branch edges (condition true/false, action ok/err). Matching + execution live
in server/service/flow_engine."""
import uuid as uuid_lib
from typing import Self

from sqlalchemy import JSON, Boolean, Column, SmallInteger, String

from server.model import AuditMixin, BaseDB, DateTime3, SnowflakeMixin, TimestampMixin, db, to_epoch_ms

NODE_TRIGGER = 'trigger'
NODE_CONDITION = 'condition'
NODE_DELAY = 'delay'
# action node types map 1:1 onto action_runner action types, except `record`
# (flow-only: fixed-duration manual recording)
ACTION_NODE_TYPES = ('webhook', 'push', 'email', 'sms', 'record',
                     'camera_enable', 'camera_disable', 'speaker', 'io')
NODE_TYPES = (NODE_TRIGGER, NODE_CONDITION, NODE_DELAY) + ACTION_NODE_TYPES

# branch handles a node may route out of (None on an edge = the default branch)
NODE_HANDLES = {
    NODE_TRIGGER: ('out',),
    NODE_CONDITION: ('true', 'false'),
}
DEFAULT_HANDLES = ('ok', 'err')      # every action/delay node

MAX_NODES = 100
MAX_EDGES = 300


class Flow(SnowflakeMixin, TimestampMixin, AuditMixin, BaseDB):
    __tablename__ = 'flows'

    uuid = Column(String(32), nullable=False, unique=True)
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    graph = Column(JSON, nullable=False, default=dict)          # {nodes: [...], edges: [...]}
    cooldown_s = Column(SmallInteger, nullable=False, default=0)
    incoming_token = Column(String(40), nullable=True, unique=True, index=True)
    last_run_ts = Column(DateTime3, nullable=True)

    @classmethod
    def get_by_id(cls, flow_id) -> Self | None:
        return db.session.query(cls).filter(cls.id == flow_id, cls.deleted_at.is_(None)).first()

    @classmethod
    def get_by_uuid(cls, flow_uuid) -> Self | None:
        return db.session.query(cls).filter(cls.uuid == flow_uuid, cls.deleted_at.is_(None)).first()

    @classmethod
    def active(cls) -> list[Self]:
        return db.session.query(cls).filter(
            cls.deleted_at.is_(None), cls.enabled.is_(True)).order_by(cls.id.asc()).all()

    @classmethod
    def get_by_incoming_token(cls, token: str) -> Self | None:
        if not token:
            return None
        return db.session.query(cls).filter(
            cls.incoming_token == token, cls.deleted_at.is_(None)).first()

    @classmethod
    def list_flows(cls, *, enabled=None, page=1, items_per_page=50) -> tuple[int, list[Self]]:
        q = db.session.query(cls).filter(cls.deleted_at.is_(None))
        if enabled is not None:
            q = q.filter(cls.enabled.is_(bool(enabled)))
        total = q.count()
        rows = q.order_by(cls.created_at.desc()).limit(items_per_page).offset(
            (page - 1) * items_per_page).all()
        return total, rows

    @classmethod
    def create(cls, data: dict, actor_id=None) -> Self:
        f = cls()
        f.uuid = uuid_lib.uuid4().hex
        # the token IS the credential of the unauthenticated incoming-hook URL — mint once,
        # keep for the flow's lifetime so saved URLs never break
        f.incoming_token = uuid_lib.uuid4().hex
        cls._apply(f, data)
        f.created_by_id = actor_id
        f.last_updated_by_id = actor_id
        db.session.add(f)
        db.session.commit()
        return f

    def modify(self, data: dict, actor_id=None) -> Self:
        self._apply(self, data)
        self.last_updated_by_id = actor_id
        db.session.add(self)
        db.session.commit()
        return self

    def soft_delete(self):
        from server.model import utcnow
        self.deleted_at = utcnow()
        db.session.add(self)
        db.session.commit()

    def trigger_nodes(self) -> list[dict]:
        return [n for n in (self.graph or {}).get('nodes', []) if n.get('type') == NODE_TRIGGER]

    @staticmethod
    def _apply(f, data):
        for k in ('name', 'description', 'enabled', 'graph', 'cooldown_s'):
            if k in data and data[k] is not None:
                setattr(f, k, data[k])

    def to_dict(self) -> dict:
        return {
            'id': str(self.id), 'uuid': self.uuid, 'name': self.name, 'description': self.description,
            'enabled': bool(self.enabled), 'graph': self.graph or {'nodes': [], 'edges': []},
            'cooldown_s': self.cooldown_s, 'incoming_token': self.incoming_token,
            'last_run_ts': to_epoch_ms(self.last_run_ts), 'created_at': to_epoch_ms(self.created_at),
        }
