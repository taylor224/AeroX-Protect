"""Camera network discovery (PLAN P1 §7.1).

Two protocols, aggregated by `discover_all()`:
  - ONVIF WS-Discovery (multicast 239.255.255.250:3702) — covers any ONVIF camera that has
    ONVIF enabled: Hikvision, Hanwha/Wisenet, Tapo (newer firmware, ONVIF turned on in the app), etc.
  - Hikvision SADP (multicast 239.255.255.250:37020) — finds Hikvision devices even when ONVIF
    is disabled, and reports model/serial/ports.
Both are multicast and only reach the backend's own L2 segment (Docker bridge does NOT forward
them — needs host/macvlan networking to see LAN cameras). Each is best-effort and never raises.
"""
import logging
import re

logger = logging.getLogger(__name__)


def _parse_scopes(scopes: list[str]) -> dict:
    """Extract manufacturer/model/hardware/name from ONVIF scope URIs."""
    out: dict[str, str] = {}
    keys = {
        'name': r'onvif://www\.onvif\.org/name/(.+)',
        'hardware': r'onvif://www\.onvif\.org/hardware/(.+)',
        'manufacturer': r'onvif://www\.onvif\.org/manufacturer/(.+)',
        'model': r'onvif://www\.onvif\.org/model/(.+)',
    }
    for scope in scopes:
        for key, pattern in keys.items():
            m = re.search(pattern, scope)
            if m:
                from urllib.parse import unquote
                out[key] = unquote(m.group(1))
    return out


def _host_from_xaddr(xaddr: str) -> str | None:
    from urllib.parse import urlparse
    try:
        return urlparse(xaddr).hostname
    except Exception:
        return None


def ws_discovery(timeout: int = 4) -> list[dict]:
    """Run WS-Discovery once; return normalized device list. Best-effort (multicast
    only reaches the same L2 segment — other subnets use manual probe)."""
    try:
        from wsdiscovery.discovery import ThreadedWSDiscovery
        from wsdiscovery.scope import Scope  # noqa: F401
    except ImportError as e:  # pragma: no cover
        logger.warning('wsdiscovery not available: %s', e)
        return []

    wsd = ThreadedWSDiscovery()
    devices = []
    try:
        wsd.start()
        services = wsd.searchServices(timeout=timeout)
        seen = set()
        for svc in services:
            xaddrs = list(svc.getXAddrs() or [])
            scopes = [str(s.getValue()) if hasattr(s, 'getValue') else str(s) for s in (svc.getScopes() or [])]
            host = next((h for h in (_host_from_xaddr(x) for x in xaddrs) if h), None)
            if not host or host in seen:
                continue
            seen.add(host)
            meta = _parse_scopes(scopes)
            devices.append({
                'host': host,
                'xaddrs': xaddrs,
                'name': meta.get('name'),
                'manufacturer': meta.get('manufacturer'),
                'model': meta.get('model'),
                'hardware': meta.get('hardware'),
            })
    except Exception as e:
        logger.warning('ws_discovery failed: %s', e)
    finally:
        try:
            wsd.stop()
        except Exception:
            pass
    for d in devices:
        d.setdefault('source', 'onvif')
    return devices


# ── Hikvision SADP (Search Active Devices Protocol) ──────────────────────────
SADP_MCAST = '239.255.255.250'
SADP_PORT = 37020


def _sadp_tag(text: str, name: str) -> str | None:
    m = re.search(r'<%s>(.*?)</%s>' % (name, name), text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else None


def parse_sadp(data: bytes) -> dict | None:
    """Parse one SADP ProbeMatch datagram into a normalized device dict (None if not SADP)."""
    text = data.decode('utf-8', 'replace')
    if 'IPv4Address' not in text:
        return None
    host = _sadp_tag(text, 'IPv4Address')
    if not host:
        return None
    model = _sadp_tag(text, 'DeviceDescription')
    return {
        'host': host,
        'xaddrs': [],
        'name': _sadp_tag(text, 'DeviceName') or model,
        'manufacturer': 'hikvision',
        'model': model,
        'hardware': _sadp_tag(text, 'DeviceSN'),
        'http_port': _sadp_tag(text, 'HttpPort'),
        'source': 'sadp',
    }


def sadp_discovery(timeout: int = 4) -> list[dict]:
    """Hikvision SADP multicast inquiry. Best-effort; returns [] on any socket/permission error."""
    import socket
    import struct
    import time
    import uuid as uuidlib

    probe = ('<?xml version="1.0" encoding="utf-8"?>'
             '<Probe><Uuid>%s</Uuid><Types>inquiry</Types></Probe>' % str(uuidlib.uuid4()).upper())
    devices: list[dict] = []
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.bind(('', SADP_PORT))
        mreq = struct.pack('4sl', socket.inet_aton(SADP_MCAST), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.sendto(probe.encode(), (SADP_MCAST, SADP_PORT))
        sock.settimeout(min(timeout, 2))
        seen: set[str] = set()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(8192)
            except socket.timeout:
                break
            dev = parse_sadp(data)
            if dev and dev['host'] not in seen:
                seen.add(dev['host'])
                devices.append(dev)
    except Exception as e:
        logger.warning('sadp_discovery failed: %s', e)
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    return devices


def discover_all(timeout: int = 4) -> list[dict]:
    """Run every discovery method and merge by host (ONVIF entry wins; SADP enriches/adds)."""
    by_host: dict[str, dict] = {}
    for d in ws_discovery(timeout):
        if d.get('host'):
            by_host[d['host']] = d
    for d in sadp_discovery(timeout):
        ex = by_host.get(d['host'])
        if ex is None:
            by_host[d['host']] = d
        else:                                   # enrich the ONVIF entry with SADP model/serial
            if not ex.get('model'):
                ex['model'] = d.get('model')
            if not ex.get('manufacturer'):
                ex['manufacturer'] = d.get('manufacturer')
    return list(by_host.values())
