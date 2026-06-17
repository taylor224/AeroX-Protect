"""Trigger normalization (PLAN P5 §6.1). Every input source (P3 event_outbox row, P4 object,
schedule cron, manual API) → one TriggerEvent dataclass the rule evaluator consumes."""
from dataclasses import asdict, dataclass, field


@dataclass
class TriggerEvent:
    trigger_type: str
    camera_id: int | None = None
    type: str | None = None
    subtype: str | None = None
    score: int | None = None
    classes: list = field(default_factory=list)
    bbox: list | None = None
    zone: int | None = None
    ts: int | None = None              # epoch ms (UTC)
    event_id: int | None = None
    snapshot_path: str | None = None
    region: dict | None = None
    raw_ref: str | None = None
    identity_id: int | None = None     # P7 face: matched identity (for face-of-person rules)
    identity_name: str | None = None
    device_id: int | None = None       # system_event: the device (action target / io) involved
    context: dict = field(default_factory=dict)

    def serialize(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, d: dict) -> 'TriggerEvent':
        return cls(**d)


def from_outbox(row) -> TriggerEvent:
    """P3 event_outbox row → TriggerEvent. Object events (P4) carry the class in subtype;
    face events carry the matched identity in raw (face-of-person rules)."""
    p = row.payload or {}
    is_object = p.get('type') == 'object'
    classes = [p['subtype']] if (is_object and p.get('subtype')) else []
    raw = p.get('raw') or {}
    identity_id = raw.get('identity_id')
    return TriggerEvent(
        trigger_type='object' if is_object else 'event',
        camera_id=int(row.camera_id) if row.camera_id else None,
        type=p.get('type'), subtype=p.get('subtype'), score=p.get('score'),
        classes=classes, ts=p.get('start_ts'),
        event_id=int(row.event_id) if row.event_id else None,
        region=p.get('region'), snapshot_path=p.get('snapshot_path'),
        identity_id=int(identity_id) if str(identity_id or '').isdigit() else None,
        identity_name=raw.get('identity'))


def from_system_event(event_type: str, camera_id=None, attrs=None) -> TriggerEvent:
    """Device/system lifecycle (camera online/offline, config change, IO input, …)."""
    from server.model import to_epoch_ms, utcnow
    attrs = attrs or {}
    return TriggerEvent(
        trigger_type='system_event', type=event_type, camera_id=camera_id,
        ts=to_epoch_ms(utcnow()), device_id=attrs.get('device_id'), context=attrs)


def from_incoming(rule, body=None, query=None) -> TriggerEvent:
    """Inbound-webhook trigger: the HTTP body/query become the rule context."""
    from server.model import to_epoch_ms, utcnow
    return TriggerEvent(
        trigger_type='incoming_webhook', type='incoming_webhook',
        ts=to_epoch_ms(utcnow()), context={'body': body or {}, 'query': query or {}})


def from_manual(camera_id=None, context=None) -> TriggerEvent:
    from server.model import to_epoch_ms, utcnow
    return TriggerEvent(trigger_type='manual', camera_id=camera_id, ts=to_epoch_ms(utcnow()),
                        context=context or {})


def from_schedule(camera_id=None) -> TriggerEvent:
    from server.model import to_epoch_ms, utcnow
    return TriggerEvent(trigger_type='schedule', camera_id=camera_id, ts=to_epoch_ms(utcnow()))
