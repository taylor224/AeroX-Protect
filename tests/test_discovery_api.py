from tests.conftest import login


def test_probe_returns_capabilities(client, monkeypatch):
    h = login(client)
    from server.controller import discovery as dc
    monkeypatch.setattr(dc.capability_probe, 'probe', lambda host, **kw: {
        'host': host, 'vendor': 'hikvision', 'driver': 'isapi', 'model': 'DS-2CD2386G2',
        'ptz_supported': True, 'streams': [], 'reachable': {'vendor_api': True}})
    r = client.post('/api/v1/discovery/probe', headers=h,
                    json={'host': '192.168.1.50', 'username': 'admin', 'password': 'x'})
    assert r.status_code == 200
    assert r.json['data']['vendor'] == 'hikvision'


def test_probe_blocks_loopback(client):
    h = login(client)
    assert client.post('/api/v1/discovery/probe', headers=h, json={'host': '127.0.0.1'}).status_code == 400


def test_probe_blocks_cloud_metadata(client):
    h = login(client)
    assert client.post('/api/v1/discovery/probe', headers=h,
                       json={'host': '169.254.169.254'}).status_code == 400


def test_probe_requires_discover_permission(client):
    from tests.conftest import create_user
    h = login(client)
    create_user(client, h, 'nodisc', {'cameras': ['read']})
    vh = login(client, 'nodisc', 'viewer1234!')
    assert client.post('/api/v1/discovery/probe', headers=vh, json={'host': '192.168.1.5'}).status_code == 403


# ── Hikvision SADP parsing + multi-protocol aggregation ──────────────────────
SADP_SAMPLE = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<ProbeMatch><Uuid>ABC</Uuid><Types>inquiry</Types>'
    b'<DeviceType>1</DeviceType><DeviceDescription>DS-2CD2386G2-IU</DeviceDescription>'
    b'<DeviceSN>DS-2CD2386G2-IU20240101AAWR123</DeviceSN>'
    b'<CommandPort>8000</CommandPort><HttpPort>80</HttpPort>'
    b'<MAC>11-22-33-44-55-66</MAC><IPv4Address>192.168.1.64</IPv4Address></ProbeMatch>'
)


def test_parse_sadp_extracts_device():
    from server.service import discovery
    d = discovery.parse_sadp(SADP_SAMPLE)
    assert d['host'] == '192.168.1.64'
    assert d['model'] == 'DS-2CD2386G2-IU' and d['manufacturer'] == 'hikvision'
    assert d['hardware'].startswith('DS-2CD2386G2') and d['http_port'] == '80'
    assert d['source'] == 'sadp'


def test_parse_sadp_rejects_non_sadp():
    from server.service import discovery
    assert discovery.parse_sadp(b'not xml') is None
    assert discovery.parse_sadp(b'<Probe><Types>inquiry</Types></Probe>') is None  # no IPv4Address


def test_discover_all_merges_onvif_and_sadp(monkeypatch):
    from server.service import discovery
    monkeypatch.setattr(discovery, 'ws_discovery', lambda timeout=4: [
        {'host': '192.168.1.64', 'manufacturer': 'Hikvision', 'model': None, 'source': 'onvif'},
        {'host': '192.168.1.70', 'manufacturer': 'Hanwha', 'model': 'XND', 'source': 'onvif'},
    ])
    monkeypatch.setattr(discovery, 'sadp_discovery', lambda timeout=4: [
        {'host': '192.168.1.64', 'manufacturer': 'hikvision', 'model': 'DS-2CD', 'source': 'sadp'},
        {'host': '192.168.1.99', 'manufacturer': 'hikvision', 'model': 'DS-7700', 'source': 'sadp'},
    ])
    out = {d['host']: d for d in discovery.discover_all()}
    assert set(out) == {'192.168.1.64', '192.168.1.70', '192.168.1.99'}   # union, deduped
    assert out['192.168.1.64']['source'] == 'onvif'                       # onvif entry wins
    assert out['192.168.1.64']['model'] == 'DS-2CD'                       # …enriched by sadp model
    assert out['192.168.1.99']['source'] == 'sadp'                        # sadp-only device added
