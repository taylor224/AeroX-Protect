"""Vendor detection + capability probing orchestration (PLAN P1 §5.2, §5.4)."""
from server.driver import factory
from server.driver.base import DriverAuthError, DriverError


def probe(host, *, http_port=80, onvif_port=80, rtsp_port=554, username=None, password=None,
          use_https=False, channel=1, verify_tls=True, timeout=6) -> dict:
    """Detect vendor and probe device info / streams / capabilities (no DB write).

    Raises DriverAuthError if credentials are rejected (caller maps to 'unauthorized').
    Returns the probe result dict (PLAN §5.2 example shape).
    """
    conn = dict(http_port=http_port, onvif_port=onvif_port, rtsp_port=rtsp_port,
                username=username, password=password, use_https=use_https,
                channel=channel, verify_tls=verify_tls, timeout=timeout)

    vendor, driver_name = factory.detect_vendor(host, **conn)
    driver = factory.build_driver(driver_name, host, **conn)

    reachable = {'onvif': driver_name == 'onvif', 'vendor_api': False, 'rtsp': None}
    result = {
        'host': host, 'vendor': vendor, 'driver': driver_name,
        'model': None, 'firmware': None, 'serial': None,
        'ptz_supported': False, 'audio_supported': False,
        'snapshot_url': None, 'streams': [], 'capabilities': None, 'reachable': reachable,
    }

    if vendor == 'unknown':
        result['error'] = 'vendor_not_detected'
        return result

    info = driver.get_device_info()   # DriverAuthError propagates to caller
    reachable['vendor_api'] = True
    result.update(model=info.model, firmware=info.firmware, serial=info.serial)

    try:
        caps = driver.get_capabilities()
        result['capabilities'] = caps.to_dict()
        result['streams'] = [s.to_dict() for s in caps.streams]
        result['ptz_supported'] = bool(caps.ptz.get('supported'))
        result['audio_supported'] = bool(caps.audio.get('input') or caps.audio.get('output'))
        result['snapshot_url'] = caps.snapshot.get('url')
    except DriverError as e:
        result['error'] = 'capability_probe_failed: %s' % e

    return result


def probe_range(hosts: list[str], **kwargs) -> list[dict]:
    """Sequentially probe a list of hosts (IP range). Auth/unreachable per host captured."""
    results = []
    for host in hosts:
        try:
            results.append(probe(host, **kwargs))
        except DriverAuthError:
            results.append({'host': host, 'vendor': 'unknown', 'reachable': {'vendor_api': False},
                            'error': 'unauthorized'})
        except DriverError as e:
            results.append({'host': host, 'vendor': 'unknown', 'error': str(e)})
    return results
