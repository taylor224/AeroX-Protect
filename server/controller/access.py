"""Access control — doors, credentials, swipes, event log (PLAN P10). Flag-gated by
`access_control`. Door/credential management needs `access:manage`; live control (manual
unlock + swipe evaluation) needs `access:control`; the event log needs `access:read`.
"""
from datetime import datetime

from server.exception import InvalidParameterException, NoPermissionException, RowNotFoundException
from server.model import UTC
from server.model.access_credential import AccessCredential
from server.model.access_event import AccessEvent
from server.model.door import CONTROLLERS, Door
from server.service import access_control, feature_flag
from server.util.tool import safe_int


def _parse_ms(value) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        return None


def _guard():
    if not feature_flag.is_enabled('access_control'):
        raise NoPermissionException('feature_disabled')


class AccessController:
    # ── doors ─────────────────────────────────────────────────────────────────
    @classmethod
    def list_doors(cls) -> list[dict]:
        _guard()
        return [d.to_dict() for d in Door.list_all()]

    @classmethod
    def create_door(cls, data: dict, actor) -> dict:
        _guard()
        if not (data.get('name') or '').strip():
            raise InvalidParameterException('name required')
        if data.get('controller_type') and data['controller_type'] not in CONTROLLERS:
            raise InvalidParameterException('invalid controller_type')
        return Door.create(data, actor.id).to_dict()

    @classmethod
    def update_door(cls, door_id, data: dict, actor) -> dict:
        _guard()
        door = Door.get_by_id(door_id)
        if not door:
            raise RowNotFoundException()
        if data.get('controller_type') and data['controller_type'] not in CONTROLLERS:
            raise InvalidParameterException('invalid controller_type')
        return door.modify(data, actor.id).to_dict()

    @classmethod
    def delete_door(cls, door_id, actor):
        _guard()
        door = Door.get_by_id(door_id)
        if not door:
            raise RowNotFoundException()
        door.soft_delete(actor.id)

    # ── control ───────────────────────────────────────────────────────────────
    @classmethod
    def unlock(cls, door_id, actor) -> dict:
        _guard()
        door = Door.get_by_id(door_id)
        if not door:
            raise RowNotFoundException()
        return access_control.unlock_door(door, source='manual')

    @classmethod
    def swipe(cls, door_id, data: dict) -> dict:
        _guard()
        door = Door.get_by_id(door_id)
        if not door:
            raise RowNotFoundException()
        card = (data.get('card_number') or '').strip()
        if not card:
            raise InvalidParameterException('card_number required')
        return access_control.process_swipe(door, card, data.get('pin'), source=data.get('source') or 'api')

    # ── credentials ───────────────────────────────────────────────────────────
    @classmethod
    def list_credentials(cls, args) -> list[dict]:
        _guard()
        return [c.to_dict() for c in AccessCredential.list_all(q=args.get('q'))]

    @classmethod
    def create_credential(cls, data: dict, actor) -> dict:
        _guard()
        if not (data.get('card_number') or '').strip() or not (data.get('holder_name') or '').strip():
            raise InvalidParameterException('card_number and holder_name required')
        if AccessCredential.find_by_card(str(data['card_number']).strip()):
            raise InvalidParameterException('card already registered')
        payload = {**data, 'valid_from': _parse_ms(data.get('valid_from')),
                   'valid_until': _parse_ms(data.get('valid_until'))}
        return AccessCredential.create(payload, actor.id).to_dict()

    @classmethod
    def update_credential(cls, cred_id, data: dict, actor) -> dict:
        _guard()
        cred = AccessCredential.get_by_id(cred_id)
        if not cred:
            raise RowNotFoundException()
        patch = dict(data)
        if 'valid_from' in data:
            patch['valid_from'] = _parse_ms(data.get('valid_from'))
        if 'valid_until' in data:
            patch['valid_until'] = _parse_ms(data.get('valid_until'))
        return cred.modify(patch, actor.id).to_dict()

    @classmethod
    def delete_credential(cls, cred_id, actor):
        _guard()
        cred = AccessCredential.get_by_id(cred_id)
        if not cred:
            raise RowNotFoundException()
        cred.soft_delete(actor.id)

    # ── events ────────────────────────────────────────────────────────────────
    @classmethod
    def list_events(cls, args) -> list[dict]:
        _guard()
        door_id = safe_int(args.get('door_id')) if args.get('door_id') else None
        limit = min(safe_int(args.get('limit'), 100) or 100, 500)
        return [e.to_dict() for e in AccessEvent.recent(door_id=door_id, limit=limit)]
