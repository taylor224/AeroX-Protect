"""System/device lifecycle events → automation rules (system_event trigger).

`emit()` is called from anywhere a notable device state change happens (camera health
flip, config change, doorbell ring, IO input edge, device reachability). It builds a
`system_event` TriggerEvent and runs the rule engine. Best-effort: emitting must NEVER break
the caller (a camera-health pass, a config save), so all failures are swallowed + logged.
"""
import logging

logger = logging.getLogger(__name__)

# Catalog of system events (name → human description). Surfaced to the rule-builder UI.
EVENTS = {
    'camera_online': '카메라 연결됨',
    'camera_offline': '카메라 연결 끊김',
    'camera_config_changed': '카메라 설정 변경됨',
    'camera_motion': '카메라 모션 감지',
    'doorbell_ring': '인터폰 벨 울림',
    'io_input_on': 'IO 입력 활성화',
    'io_input_off': 'IO 입력 비활성화',
    'device_online': '장치 연결됨',
    'device_offline': '장치 연결 끊김',
}


def emit(event_type: str, camera_id=None, attrs: dict | None = None) -> None:
    """Fire a system_event trigger through the rule engine. Synchronous + best-effort."""
    try:
        from server.service import rule_dispatcher, trigger_router
        trig = trigger_router.from_system_event(event_type, camera_id=camera_id, attrs=attrs or {})
        rule_dispatcher.on_trigger(trig)
    except Exception:                       # noqa: BLE001 — never break the caller
        logger.exception('automation emit failed (%s)', event_type)
