"""Access-control decision engine (PLAN P10). `evaluate` is a pure decision over a door +
card (+ PIN); `process_swipe` runs the full flow: decide → log an AccessEvent → on grant
drive the lock open → raise a P3 `access` event (→ outbox→rules/notify). `unlock_door` is a
manual momentary unlock. Flag-gated by `access_control`.
"""
import logging

from server.model import utcnow
from server.model.access_credential import AccessCredential
from server.model.access_event import DECISION_DENIED, DECISION_GRANTED, AccessEvent
from server.model.door import Door
from server.model.event import TYPE_ACCESS

logger = logging.getLogger(__name__)


def evaluate(door: Door, card_number: str, pin: str | None = None) -> dict:
    """Pure decision. Returns {decision, reason, credential}."""
    if not door.enabled:
        return {'decision': DECISION_DENIED, 'reason': 'door_disabled', 'credential': None}
    cred = AccessCredential.find_by_card((card_number or '').strip())
    if cred is None:
        return {'decision': DECISION_DENIED, 'reason': 'unknown_card', 'credential': None}
    if not cred.enabled:
        return {'decision': DECISION_DENIED, 'reason': 'card_disabled', 'credential': cred}
    if not cred.is_valid_at(utcnow()):
        return {'decision': DECISION_DENIED, 'reason': 'expired', 'credential': cred}
    if door.access_group != 'public' and cred.access_group != door.access_group:
        return {'decision': DECISION_DENIED, 'reason': 'wrong_group', 'credential': cred}
    if door.require_pin:
        # a PIN-less credential must not satisfy a require_pin door —
        # verify_pin() returns True when no PIN is set (that path is for PIN-less doors)
        if cred.pin_hash is None or not cred.verify_pin(pin):
            return {'decision': DECISION_DENIED, 'reason': 'bad_pin', 'credential': cred}
    return {'decision': DECISION_GRANTED, 'reason': 'ok', 'credential': cred}


def process_swipe(door: Door, card_number: str, pin: str | None = None, source: str = 'reader') -> dict:
    """Full swipe flow: decide, log, unlock-on-grant, raise event. Returns the AccessEvent dict."""
    result = evaluate(door, card_number, pin)
    cred = result['credential']
    granted = result['decision'] == DECISION_GRANTED

    if granted:
        _drive_unlock(door)

    ev = AccessEvent.record(
        door_id=door.id, decision=result['decision'], reason=result['reason'],
        credential_id=(cred.id if cred else None), card_number=(card_number or '').strip()[:64],
        holder_name=(cred.holder_name if cred else None), source=source)

    _raise_event(door, result, cred, ev)
    return {**ev.to_dict(), 'granted': granted}


def unlock_door(door: Door, source: str = 'manual') -> dict:
    """Manual momentary unlock (no card). Logs + raises a granted access event."""
    _drive_unlock(door)
    ev = AccessEvent.record(door_id=door.id, decision=DECISION_GRANTED, reason='manual_unlock', source=source)
    return {**ev.to_dict(), 'lock_state': door.lock_state}


# ── internals ─────────────────────────────────────────────────────────────────
def _drive_unlock(door: Door):
    from server.driver import door as door_drv
    try:
        res = door_drv.unlock(door, door.unlock_seconds)
    except Exception:
        logger.exception('door unlock failed door=%s', door.id)
        return
    # Only reflect UNLOCKED if the relay actually actuated. 'skipped' (deferred controller)
    # or 'failed' means the door never opened — leave lock_state as-is.
    if res.get('status') != 'ok':
        if res.get('status') == 'skipped':
            logger.info('door unlock skipped (controller deferred) door=%s', door.id)
        return
    # Momentary pulse: stamp the unlock so the effective state auto-relocks after
    # `unlock_seconds` at read time (no broker round-trip on the swipe path).
    door.mark_unlocked()


def _raise_event(door: Door, result: dict, cred, access_event):
    if not door.camera_id:
        return                              # P3 events are camera-scoped; the AccessEvent row is the SSOT
    from server.service import event_pipeline
    try:
        event_pipeline.ingest_object(door.camera_id, {
            'type': TYPE_ACCESS, 'state': 'pulse', 'subtype': result['decision'],
            'source': 'access',
            'dedup_extra': '%s:%s' % (door.id, access_event.card_number or ''),  # per door+card
            'raw': {'door': door.name, 'door_id': str(door.id), 'reason': result['reason'],
                    'holder': cred.holder_name if cred else None, 'access_event_id': str(access_event.id)}})
    except Exception:
        # access logging must never fail on the event side; the AccessEvent row is the SSOT
        logger.exception('access event raise failed door=%s', door.id)
