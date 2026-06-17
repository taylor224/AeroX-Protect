from server.exception import InvalidParameterException, RowNotFoundException
from server.model.rule import TRIGGER_TYPES, Rule
from server.model.rule_execution import RuleExecution
from server.service import rule_dispatcher, rule_evaluator, trigger_router
from server.util.tool import safe_int


def _bool(v):
    return {'true': True, 'false': False}.get(str(v).lower()) if v is not None else None


class RuleController:
    @classmethod
    def list_rules(cls, args) -> dict:
        total, rows = Rule.list_rules(
            trigger_type=args.get('trigger_type'), enabled=_bool(args.get('enabled')),
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))
        return {'count': total, 'items': [r.to_dict() for r in rows]}

    @classmethod
    def get(cls, rule_uuid: str) -> dict:
        return cls._require(rule_uuid).to_dict()

    @classmethod
    def create(cls, data: dict, actor) -> dict:
        cls._validate(data)
        return Rule.create(data, actor.id).to_dict()

    @classmethod
    def update(cls, rule_uuid: str, data: dict, actor) -> dict:
        rule = cls._require(rule_uuid)
        if data.get('trigger_type'):
            cls._validate({**rule.to_dict(), **data})
        return rule.modify(data, actor.id).to_dict()

    @classmethod
    def delete(cls, rule_uuid: str):
        cls._require(rule_uuid).soft_delete()

    @classmethod
    def enable(cls, rule_uuid: str, enabled: bool, actor) -> dict:
        return cls._require(rule_uuid).modify({'enabled': bool(enabled)}, actor.id).to_dict()

    @classmethod
    def trigger(cls, rule_uuid: str, data: dict, actor) -> dict:
        rule = cls._require(rule_uuid)
        trig = trigger_router.from_manual(
            camera_id=safe_int(data.get('camera_id'), None) if data.get('camera_id') else None,
            context=data.get('context'))
        trig.trigger_type = 'manual'
        ex = rule_dispatcher.fire_rule(rule, trig)
        return {'execution_id': str(ex.id), 'status': ex.status, 'action_results': ex.action_results}

    @classmethod
    def fire_incoming(cls, token: str, body: dict | None, query: dict | None) -> dict:
        """Inbound-webhook trigger: look up the rule by its hook token and run it. Returns a
        minimal result (no rule internals leaked to an unauthenticated caller)."""
        rule = Rule.get_by_incoming_token(token)
        if not rule or not rule.enabled:
            raise RowNotFoundException()
        trig = trigger_router.from_incoming(rule, body=body, query=query)
        ex = rule_dispatcher.fire_rule(rule, trig)
        return {'status': ex.status}

    @classmethod
    def test(cls, rule_uuid: str, data: dict) -> dict:
        """Dry-run: evaluate against a synthetic trigger built from the rule's own config."""
        rule = cls._require(rule_uuid)
        t = rule.trigger or {}
        trig = trigger_router.TriggerEvent(
            trigger_type=rule.trigger_type,
            camera_id=safe_int(data.get('camera_id'), None) if data.get('camera_id') else None,
            type=(t.get('event_types') or ['object' if rule.trigger_type == 'object' else 'motion'])[0]
            if rule.trigger_type == 'event' else ('object' if rule.trigger_type == 'object' else None),
            subtype=(t.get('classes') or [None])[0] if rule.trigger_type == 'object' else None,
            classes=t.get('classes') or [], score=t.get('min_confidence') or 100,
            event_id=None)
        res = rule_evaluator.evaluate(rule, trig)
        return {'matched': res.matched, 'skip_reason': res.reason}

    @classmethod
    def executions(cls, rule_uuid: str, args) -> dict:
        rule = cls._require(rule_uuid)
        total, rows = RuleExecution.list_logs(
            rule_id=rule.id, status=args.get('status'),
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))
        return {'count': total, 'items': [e.to_dict() for e in rows]}

    @classmethod
    def all_executions(cls, args) -> dict:
        total, rows = RuleExecution.list_logs(
            rule_id=safe_int(args.get('rule_id'), None) if args.get('rule_id') else None,
            camera_id=safe_int(args.get('camera_id'), None) if args.get('camera_id') else None,
            status=args.get('status'),
            page=max(1, safe_int(args.get('page'), 1)),
            items_per_page=min(200, max(1, safe_int(args.get('items_per_page'), 50))))
        return {'count': total, 'items': [e.to_dict() for e in rows]}

    @staticmethod
    def _require(rule_uuid) -> Rule:
        rule = Rule.get_by_uuid(rule_uuid)
        if not rule:
            raise RowNotFoundException()
        return rule

    @staticmethod
    def _validate(data):
        if data.get('trigger_type') not in TRIGGER_TYPES:
            raise InvalidParameterException('trigger_type must be one of %s' % (TRIGGER_TYPES,))
        if not data.get('name'):
            raise InvalidParameterException('name required')
        if 'actions' in data and not isinstance(data['actions'], list):
            raise InvalidParameterException('actions must be a list')
