"""Vendor detection + driver assembly (PLAN P1 §5.4)."""
from server.driver.base import CameraDriver, DriverAuthError, DriverError
from server.driver.composite import CompositeDriver
from server.driver.isapi import IsapiDriver
from server.driver.onvif import OnvifDriver
from server.driver.sunapi import SunapiDriver

DRIVERS = {'isapi': IsapiDriver, 'sunapi': SunapiDriver, 'onvif': OnvifDriver}


def detect_vendor(host, *, http_port=80, onvif_port=80, rtsp_port=554,
                  username=None, password=None, use_https=False, channel=1,
                  verify_tls=True, timeout=6) -> tuple[str, str]:
    """Probe vendor signatures fast-first. Returns (vendor, driver_name).

    Order: Hikvision ISAPI → Hanwha SUNAPI → ONVIF (manufacturer) → unknown.
    A 401 from a vendor endpoint still identifies the vendor (auth fixable later).
    """
    conn = dict(http_port=http_port, onvif_port=onvif_port, rtsp_port=rtsp_port,
                username=username, password=password, use_https=use_https,
                channel=channel, verify_tls=verify_tls, timeout=timeout)

    for vendor, driver_name, cls in (('hikvision', 'isapi', IsapiDriver), ('hanwha', 'sunapi', SunapiDriver)):
        try:
            cls(host, **conn).get_device_info()
            return vendor, driver_name
        except DriverAuthError:
            return vendor, driver_name        # vendor confirmed, creds wrong
        except DriverError:
            continue

    try:
        info = OnvifDriver(host, **conn).get_device_info()
        return info.vendor, 'onvif'
    except DriverAuthError:
        return 'onvif', 'onvif'
    except DriverError:
        pass

    return 'unknown', 'onvif'


def build_driver(driver_name: str, host, **conn) -> CameraDriver:
    """Vendor driver wrapped with an ONVIF fallback (CompositeDriver)."""
    cls = DRIVERS.get(driver_name, OnvifDriver)
    primary = cls(host, **conn)
    fallback = OnvifDriver(host, **conn) if cls is not OnvifDriver else None
    return CompositeDriver(primary, fallback)
