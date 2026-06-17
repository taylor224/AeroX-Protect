"""ONVIF PullPoint event source (PLAN §6.1) via onvif-zeep. Structural — exercised
against real/simulated ONVIF; the parsing of PullMessages → message dicts is the
reusable part fed to event_normalizer.normalize_onvif()."""
import logging
import time

from server.driver.event_base import EventSource

logger = logging.getLogger(__name__)


def parse_pull_messages(messages) -> list[dict]:
    """zeep NotificationMessage[] → [{topic, data, utc_time, property_operation, channel}]."""
    out = []
    for msg in messages or []:
        topic = ''
        try:
            topic = str(getattr(msg.Topic, '_value_1', '') or '')
        except Exception:
            pass
        data = {}
        utc_time = None
        operation = None
        try:
            nmsg = msg.Message._value_1
            operation = getattr(nmsg, 'PropertyOperation', None)
            utc_time = getattr(nmsg, 'UtcTime', None)
            for item in (getattr(getattr(nmsg, 'Data', None), 'SimpleItem', None) or []):
                data[getattr(item, 'Name', '')] = getattr(item, 'Value', '')
        except Exception:
            pass
        out.append({'topic': topic, 'data': data,
                    'utc_time': str(utc_time) if utc_time else None,
                    'property_operation': operation})
    return out


class OnvifEventSource(EventSource):
    def __init__(self, host, http_port=80, onvif_port=80, username=None, password=None,
                 use_https=False, channel=1):
        self.host = host
        self.onvif_port = onvif_port
        self.username = username
        self.password = password
        self.channel = channel
        self._camera = None
        self._pullpoint = None
        self._renew_at = None
        self._healthy = False

    def open(self) -> None:
        from onvif import ONVIFCamera
        self._camera = ONVIFCamera(self.host, self.onvif_port, self.username or '', self.password or '')
        events = self._camera.create_events_service()
        events.CreatePullPointSubscription()
        self._pullpoint = self._camera.create_pullpoint_service()
        self._renew_at = int(time.time() * 1000) + 3600_000
        self._healthy = True

    def poll(self, timeout_s: float) -> list[dict]:
        if self._pullpoint is None:
            return []
        try:
            resp = self._pullpoint.PullMessages(
                {'Timeout': 'PT%dS' % int(timeout_s), 'MessageLimit': 50})
            return parse_pull_messages(getattr(resp, 'NotificationMessage', None))
        except Exception as e:
            logger.debug('onvif pull failed: %s', e)
            self._healthy = False
            return []

    def renew(self) -> None:
        try:
            self._pullpoint.Renew({'TerminationTime': 'PT1H'})
            self._renew_at = int(time.time() * 1000) + 3600_000
        except Exception:
            self._healthy = False

    def close(self) -> None:
        try:
            if self._pullpoint:
                self._pullpoint.Unsubscribe()
        except Exception:
            pass
        self._healthy = False

    @property
    def needs_renew_at(self):
        return self._renew_at

    @property
    def healthy(self) -> bool:
        return self._healthy

    @property
    def source_name(self) -> str:
        return 'onvif'
