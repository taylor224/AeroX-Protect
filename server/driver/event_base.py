"""Event-source abstraction (PLAN §5.4). One per camera; the subscription worker
drives open()/poll()/renew()/close(). Reuses P1 driver auth/credentials."""
from abc import ABC, abstractmethod


class EventSource(ABC):
    @abstractmethod
    def open(self) -> None:
        ...

    @abstractmethod
    def poll(self, timeout_s: float) -> list[dict]:
        """Return a batch of raw vendor event dicts (empty = heartbeat)."""

    def renew(self) -> None:
        return None

    @abstractmethod
    def close(self) -> None:
        ...

    @property
    def needs_renew_at(self) -> int | None:
        return None

    @property
    def healthy(self) -> bool:
        return True

    @property
    def source_name(self) -> str:
        return 'none'


def select_protocol(camera) -> str:
    """Pick an event protocol from the camera driver/capabilities."""
    driver = (camera.driver or '').lower()
    caps = camera.capabilities or {}
    transport = (caps.get('events', {}) or {}).get('transport', '') if isinstance(caps, dict) else ''
    if driver == 'isapi' or transport == 'isapi_alertstream':
        return 'isapi_alertstream'
    if driver == 'sunapi' or transport == 'sunapi_eventstatus':
        return 'sunapi'
    return 'onvif_pullpoint'


def make_event_source(camera) -> EventSource | None:
    """Build the right EventSource for a camera (None if events unsupported)."""
    protocol = select_protocol(camera)
    username, password = camera.get_credentials()
    conn = dict(host=camera.host, http_port=camera.http_port or 80, onvif_port=camera.onvif_port or 80,
                username=username, password=password, use_https=camera.use_https, channel=camera.channel)
    if protocol == 'isapi_alertstream':
        from server.driver.isapi_event import IsapiEventSource
        return IsapiEventSource(**conn)
    if protocol == 'sunapi':
        from server.driver.sunapi_event import SunapiEventSource
        return SunapiEventSource(**conn)
    from server.driver.onvif_event import OnvifEventSource
    return OnvifEventSource(**conn)
