"""Encoder-node HTTP surface: admin CRUD (permission-gated) + node protocol
join→heartbeat→assignments(etag/304). Mirrors test_p4_api.py."""
from tests.conftest import create_user, login


def _join_node(client, h, name='enc-test', payload=None):
    cr = client.post('/api/v1/encoding-nodes', headers=h, json={'name': name})
    join_token = cr.json['data']['join_token']
    node = cr.json['data']['node']
    jr = client.post('/api/v1/encode/nodes/join', headers={'Authorization': 'Bearer ' + join_token},
                     json=payload or {'name': name, 'hwaccel': 'none', 'max_sessions': 4,
                                      'endpoint': 'http://enc:8098'})
    nh = {'Authorization': 'Bearer ' + jr.json['data']['node_token']}
    return node, nh


def test_node_join_heartbeat_assignments(client, mock_go2rtc):
    h = login(client)
    node, nh = _join_node(client, h)

    hb = client.post('/api/v1/encode/nodes/heartbeat', headers=nh, json={'status': 'online'})
    assert hb.status_code == 200 and 'assignments_etag' in hb.json['data']

    asg = client.get('/api/v1/encode/nodes/assignments', headers=nh)
    assert asg.status_code == 200 and 'items' in asg.json['data']

    etag = asg.json['data']['etag']
    asg304 = client.get('/api/v1/encode/nodes/assignments', headers={**nh, 'If-None-Match': etag})
    assert asg304.status_code == 304


def test_join_token_is_one_time(client, mock_go2rtc):
    h = login(client)
    cr = client.post('/api/v1/encoding-nodes', headers=h, json={'name': 'e'})
    join_token = cr.json['data']['join_token']
    jh = {'Authorization': 'Bearer ' + join_token}
    assert client.post('/api/v1/encode/nodes/join', headers=jh, json={}).status_code == 200
    assert client.post('/api/v1/encode/nodes/join', headers=jh, json={}).status_code == 401


def test_node_token_required(client, mock_go2rtc):
    assert client.post('/api/v1/encode/nodes/heartbeat', json={}).status_code == 401
    assert client.get('/api/v1/encode/nodes/assignments').status_code == 401


def test_encoding_nodes_requires_manage(client, mock_go2rtc):
    h = login(client)
    create_user(client, h, 'enc_noperm', {'detections': ['read']})
    vh = login(client, 'enc_noperm', 'viewer1234!')
    assert client.get('/api/v1/encoding-nodes', headers=vh).status_code == 403
    assert client.post('/api/v1/encoding-nodes', headers=vh, json={'name': 'x'}).status_code == 403


def test_node_crud_drain_delete(client, mock_go2rtc):
    h = login(client)
    node, _nh = _join_node(client, h)

    lst = client.get('/api/v1/encoding-nodes', headers=h)
    row = next(n for n in lst.json['data']['items'] if n['id'] == node['id'])
    assert row['status'] == 'online' and row['max_sessions'] == 4

    up = client.put(f"/api/v1/encoding-nodes/{node['id']}", headers=h,
                    json={'endpoint': 'http://10.0.0.5:8098', 'max_sessions': 6})
    assert up.status_code == 200 and up.json['data']['max_sessions'] == 6

    assert client.post(f"/api/v1/encoding-nodes/{node['id']}/drain", headers=h, json={}).status_code == 200
    lst = client.get('/api/v1/encoding-nodes', headers=h)
    row = next(n for n in lst.json['data']['items'] if n['id'] == node['id'])
    assert row['status'] == 'draining'

    assert client.delete(f"/api/v1/encoding-nodes/{node['id']}", headers=h).status_code == 200
    lst = client.get('/api/v1/encoding-nodes', headers=h)
    assert all(n['id'] != node['id'] for n in lst.json['data']['items'])


def test_assignments_admin_view_and_rebalance(client, mock_go2rtc):
    h = login(client)
    _join_node(client, h)
    lst = client.get('/api/v1/encoding-nodes/assignments', headers=h)
    assert lst.status_code == 200 and 'items' in lst.json['data']
    rb = client.post('/api/v1/encoding-nodes/assignments/rebalance', headers=h, json={})
    assert rb.status_code == 200 and 'assigned' in rb.json['data']
