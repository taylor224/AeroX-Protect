from server.driver.base import DriverAuthError, DriverUnreachable
from server.exception import InvalidParameterException
from server.service import capability_probe, discovery
from server.util.net import UnsafeHostError, validate_probe_host
from server.util.tool import safe_int


class DiscoveryController:
    @classmethod
    def discover_onvif(cls, timeout: int = 4) -> list[dict]:
        # ONVIF WS-Discovery + Hikvision SADP, merged (covers Hikvision/Hanwha/Tapo via ONVIF,
        # plus Hikvision even when ONVIF is off)
        return discovery.discover_all(timeout=min(max(timeout, 1), 10))

    @classmethod
    def probe(cls, data: dict) -> dict:
        host = (data.get('host') or '').strip()
        if not host:
            raise InvalidParameterException('host is required')
        try:
            validate_probe_host(host)
        except UnsafeHostError as e:
            raise InvalidParameterException('unsafe host: %s' % e)

        conn = dict(
            http_port=safe_int(data.get('http_port'), 80),
            onvif_port=safe_int(data.get('onvif_port'), 80),
            rtsp_port=safe_int(data.get('rtsp_port'), 554),
            username=data.get('username'),
            password=data.get('password'),
            use_https=bool(data.get('use_https')),
            channel=safe_int(data.get('channel'), 1),
            verify_tls=data.get('verify_tls', True),
        )
        try:
            return capability_probe.probe(host, **conn)
        except DriverAuthError:
            return {'host': host, 'vendor': 'unknown', 'status': 'unauthorized',
                    'reachable': {'vendor_api': False}, 'error': 'unauthorized'}
        except DriverUnreachable as e:
            return {'host': host, 'vendor': 'unknown', 'status': 'offline',
                    'reachable': {'vendor_api': False}, 'error': str(e)}
