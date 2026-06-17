"""SSRF guard for discovery/probe targets (PLAN P1 §13)."""
import ipaddress
import socket

# Cloud metadata + loopback/link-local are always blocked.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network('127.0.0.0/8'),
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('169.254.0.0/16'),   # link-local incl. 169.254.169.254 metadata
    ipaddress.ip_network('fe80::/10'),
    ipaddress.ip_network('0.0.0.0/8'),
]


class UnsafeHostError(Exception):
    pass


def resolve_host(host: str) -> ipaddress._BaseAddress:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeHostError('cannot resolve host: %s' % e)
    return ipaddress.ip_address(info[0][4][0])


def validate_probe_host(host: str) -> None:
    """Raise UnsafeHostError for loopback/link-local/metadata/multicast targets.

    Private LAN ranges (where cameras live) and public IPs are allowed; only the
    dangerous internal ranges are blocked.
    """
    if not host or not host.strip():
        raise UnsafeHostError('empty host')
    addr = resolve_host(host.strip())
    if addr.is_multicast or addr.is_unspecified:
        raise UnsafeHostError('disallowed address: %s' % addr)
    for net in _BLOCKED_NETWORKS:
        if addr.version == net.version and addr in net:
            raise UnsafeHostError('blocked address range: %s' % addr)
