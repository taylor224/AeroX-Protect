"""Visual automation flows: graph validation, engine execution (branching, templating,
fan-out, cycle guard, cooldown), trigger matching, schedule tick, and the /flows API."""
import pytest

from server.exception import InvalidParameterException
from server.model import db
from server.model.camera import Camera
from server.model.flow import Flow
from server.model.flow_run import FlowRun
from server.service import flow_engine
from server.service.trigger_router import TriggerEvent
from tests.conftest import login


def _camera(name='c', host='192.0.2.60') -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, host, 'onvif', 'onvif', True
    db.session.add(c)
    db.session.commit()
    return c


def _trig(**kw):
    base = dict(trigger_type='object', camera_id=5, type='object', subtype='person',
                classes=['person'], score=80, event_id=1, ts=1_700_000_000_000)
    base.update(kw)
    return TriggerEvent(**base)


def _node(nid, ntype, **data):
    return {'id': nid, 'type': ntype, 'position': {'x': 0, 'y': 0}, 'data': data}


def _edge(src, tgt, handle=None):
    return {'id': f'{src}-{tgt}-{handle}', 'source': src, 'target': tgt, 'sourceHandle': handle}


def _flow(graph, name='f', **extra) -> Flow:
    return Flow.create({'name': name, 'graph': graph, **extra})


def _mock_webhook(monkeypatch, status_code=200):
    """Capture inline-webhook sends; returns the list of (url, json) tuples."""
    from server.driver import webhook as webhook_drv
    sent = []

    def fake_request(method, url, **kw):
        sent.append({'method': method, 'url': url, 'json': kw.get('json'), 'params': kw.get('params')})

        class R:
            pass
        R.status_code = status_code
        return R()

    monkeypatch.setattr(webhook_drv, 'ssrf_check', lambda url: (True, ''))
    monkeypatch.setattr(webhook_drv.requests, 'request', fake_request)
    return sent


# ── graph validation ──────────────────────────────────────────────────────────
def test_validate_requires_trigger_node(app_db):
    with pytest.raises(InvalidParameterException):
        flow_engine.validate_graph({'nodes': [_node('a', 'webhook')], 'edges': []})


def test_validate_rejects_unknown_type_and_bad_edges(app_db):
    with pytest.raises(InvalidParameterException):
        flow_engine.validate_graph({'nodes': [_node('t', 'trigger'), _node('x', 'nope')], 'edges': []})
    with pytest.raises(InvalidParameterException):
        flow_engine.validate_graph({'nodes': [_node('t', 'trigger')], 'edges': [_edge('t', 'ghost')]})
    # edge into a trigger node
    with pytest.raises(InvalidParameterException):
        flow_engine.validate_graph({'nodes': [_node('t', 'trigger'), _node('w', 'webhook')],
                                    'edges': [_edge('w', 't')]})
    # handle not valid for the source node type
    with pytest.raises(InvalidParameterException):
        flow_engine.validate_graph({'nodes': [_node('t', 'trigger'), _node('w', 'webhook')],
                                    'edges': [_edge('t', 'w', 'true')]})
    # bad condition op
    with pytest.raises(InvalidParameterException):
        flow_engine.validate_graph({'nodes': [_node('t', 'trigger'),
                                              _node('c', 'condition', clauses=[{'field': 'score', 'op': 'evil'}])],
                                    'edges': []})


def test_validate_accepts_good_graph(app_db):
    flow_engine.validate_graph({
        'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                  _node('c', 'condition', mode='all', clauses=[{'field': 'score', 'op': 'gte', 'value': 50}]),
                  _node('w', 'webhook', url='https://h/x')],
        'edges': [_edge('t', 'c'), _edge('c', 'w', 'true')]})


# ── engine: branching / templating / fan-out ──────────────────────────────────
def test_condition_true_false_branches(app_db, monkeypatch):
    sent = _mock_webhook(monkeypatch)
    graph = {
        'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                  _node('c', 'condition', mode='all', clauses=[{'field': 'score', 'op': 'gte', 'value': 50}]),
                  _node('hi', 'webhook', url='https://h/high'),
                  _node('lo', 'webhook', url='https://h/low')],
        'edges': [_edge('t', 'c'), _edge('c', 'hi', 'true'), _edge('c', 'lo', 'false')]}
    flow = _flow(graph)

    run = flow_engine.run_flow(flow, _trig(score=80))
    assert run.status == 'success'
    assert [s['url'] for s in sent] == ['https://h/high']
    by_node = {r['node_id']: r for r in run.node_results}
    assert by_node['c']['output'] == {'result': True}
    assert 'lo' not in by_node                       # false branch never ran

    sent.clear()
    run2 = flow_engine.run_flow(flow, _trig(score=10))
    assert [s['url'] for s in sent] == ['https://h/low']
    assert {r['node_id'] for r in run2.node_results} == {'t', 'c', 'lo'}


def test_ok_err_branches_on_action_failure(app_db, monkeypatch):
    sent = _mock_webhook(monkeypatch, status_code=500)   # first webhook fails
    graph = {
        'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                  _node('w', 'webhook', url='https://h/first'),
                  _node('ok', 'webhook', url='https://h/ok'),
                  _node('err', 'webhook', url='https://h/err')],
        'edges': [_edge('t', 'w'), _edge('w', 'ok', 'ok'), _edge('w', 'err', 'err')]}
    flow = _flow(graph)
    run = flow_engine.run_flow(flow, _trig())
    urls = [s['url'] for s in sent]
    assert urls == ['https://h/first', 'https://h/err']  # err branch taken, ok skipped
    assert run.status == 'failed'                        # both executed webhooks got 500
    by_node = {r['node_id']: r for r in run.node_results}
    assert by_node['w']['status'] == 'failed' and by_node['err']['status'] == 'failed'


def test_fan_out_and_cycle_guard(app_db, monkeypatch):
    sent = _mock_webhook(monkeypatch)
    graph = {
        'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                  _node('a', 'webhook', url='https://h/a'),
                  _node('b', 'webhook', url='https://h/b'),
                  _node('c', 'webhook', url='https://h/c')],
        'edges': [_edge('t', 'a'), _edge('t', 'b'),      # fan-out from the trigger
                  _edge('a', 'c'), _edge('b', 'c'),      # fan-in (c runs once)
                  _edge('c', 'a')]}                      # cycle back — must not loop
    flow = _flow(graph)
    run = flow_engine.run_flow(flow, _trig())
    assert sorted(s['url'] for s in sent) == ['https://h/a', 'https://h/b', 'https://h/c']
    assert run.status == 'success'


def test_template_rendering(app_db, monkeypatch):
    sent = _mock_webhook(monkeypatch)
    cam = _camera('현관')
    graph = {
        'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                  _node('w', 'webhook', url='https://h/x',
                        body={'msg': '{{trigger.camera_name}}에서 {{trigger.subtype}} 감지',
                              'score': '{{trigger.score}}'})],
        'edges': [_edge('t', 'w')]}
    flow = _flow(graph)
    flow_engine.run_flow(flow, _trig(camera_id=cam.id, score=77))
    assert sent[0]['json']['msg'] == '현관에서 person 감지'
    assert sent[0]['json']['score'] == 77                # whole-string template keeps type


def test_condition_custom_left_template(app_db):
    graph = {
        'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'incoming_webhook'}]),
                  _node('c', 'condition', mode='all',
                        clauses=[{'field': 'custom', 'left': '{{trigger.context.body.door}}',
                                  'op': 'eq', 'value': 'open'}])],
        'edges': [_edge('t', 'c')]}
    flow = _flow(graph)
    trig = TriggerEvent(trigger_type='incoming_webhook', type='incoming_webhook',
                        context={'body': {'door': 'open'}, 'query': {}})
    run = flow_engine.run_flow(flow, trig)
    assert {r['node_id']: r['output'] for r in run.node_results}['c'] == {'result': True}


def test_record_node_starts_manual_recording(app_db):
    cam = _camera()
    graph = {'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                       _node('r', 'record', duration_s=30)],
             'edges': [_edge('t', 'r')]}
    flow = _flow(graph)
    run = flow_engine.run_flow(flow, _trig(camera_id=cam.id))
    rec = {r['node_id']: r for r in run.node_results}['r']
    assert rec['status'] == 'success' and rec['output']['recording_id']
    from server.model.recording import Recording
    assert Recording.get_active_manual(cam.id) is not None


# ── dispatch: matching + cooldown + schedule ──────────────────────────────────
def test_on_trigger_matches_sources(app_db, monkeypatch):
    sent = _mock_webhook(monkeypatch)
    graph = {'nodes': [_node('t', 'trigger', sources=[
                           {'trigger_type': 'object', 'classes': ['person'], 'camera_ids': [5]}]),
                       _node('w', 'webhook', url='https://h/x')],
             'edges': [_edge('t', 'w')]}
    _flow(graph)
    assert len(flow_engine.on_trigger(_trig(camera_id=5, classes=['person']))) == 1
    assert flow_engine.on_trigger(_trig(camera_id=9, classes=['person'])) == []
    assert flow_engine.on_trigger(_trig(camera_id=5, classes=['car'])) == []
    assert len(sent) == 1


def test_on_trigger_cooldown_records_skip(app_db, monkeypatch, redis_client):
    _mock_webhook(monkeypatch)
    graph = {'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                       _node('w', 'webhook', url='https://h/x')],
             'edges': [_edge('t', 'w')]}
    _flow(graph, cooldown_s=60)
    first, = flow_engine.on_trigger(_trig())
    second, = flow_engine.on_trigger(_trig())
    assert first.status == 'success'
    assert second.status == 'skipped' and second.skip_reason == 'cooldown'


def test_schedule_tick_fires_cron_source(app_db, monkeypatch):
    sent = _mock_webhook(monkeypatch)
    graph = {'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'schedule', 'cron': '30 9 * * *'}]),
                       _node('w', 'webhook', url='https://h/x')],
             'edges': [_edge('t', 'w')]}
    _flow(graph)
    from datetime import datetime

    from server.model import KST
    assert flow_engine.tick_schedules(datetime(2026, 7, 1, 9, 30, tzinfo=KST)) == 1
    assert flow_engine.tick_schedules(datetime(2026, 7, 1, 9, 31, tzinfo=KST)) == 0
    assert len(sent) == 1


# ── API ───────────────────────────────────────────────────────────────────────
def _good_graph():
    return {'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'object'}]),
                      _node('w', 'webhook', url='https://h/x')],
            'edges': [_edge('t', 'w')]}


def test_flow_crud_api(client):
    h = login(client)
    res = client.post('/api/v1/flows', headers=h, json={'name': '침입 대응', 'graph': _good_graph()})
    assert res.status_code == 200, res.json
    flow = res.json['data']
    assert flow['incoming_token']

    res = client.get('/api/v1/flows', headers=h)
    assert res.json['data']['count'] == 1

    res = client.put(f"/api/v1/flows/{flow['uuid']}", headers=h,
                     json={'graph': {'nodes': [], 'edges': []}})
    assert res.status_code == 400                        # graph update re-validated

    res = client.post(f"/api/v1/flows/{flow['uuid']}/enable", headers=h, json={'enabled': False})
    assert res.json['data']['enabled'] is False

    res = client.delete(f"/api/v1/flows/{flow['uuid']}", headers=h)
    assert res.status_code == 200
    assert client.get(f"/api/v1/flows/{flow['uuid']}", headers=h).status_code == 404


def test_flow_manual_run_and_runs_api(client, monkeypatch):
    _mock_webhook(monkeypatch)
    h = login(client)
    flow = client.post('/api/v1/flows', headers=h,
                       json={'name': 'run', 'graph': _good_graph()}).json['data']

    res = client.post(f"/api/v1/flows/{flow['uuid']}/run", headers=h, json={})
    assert res.status_code == 200
    run = res.json['data']
    assert run['status'] == 'success'
    assert {r['node_id'] for r in run['node_results']} == {'t', 'w'}

    res = client.get(f"/api/v1/flows/{flow['uuid']}/runs", headers=h)
    assert res.json['data']['count'] == 1
    item = res.json['data']['items'][0]
    assert item['node_statuses'] == {'t': 'success', 'w': 'success'}

    res = client.get(f"/api/v1/flows/{flow['uuid']}/runs/{item['id']}", headers=h)
    assert res.json['data']['node_results'][0]['node_id'] == 't'


def test_flow_incoming_webhook_api(client, monkeypatch):
    _mock_webhook(monkeypatch)
    h = login(client)
    # flow WITHOUT an incoming source → its token URL is a 404
    flow = client.post('/api/v1/flows', headers=h,
                       json={'name': 'no-incoming', 'graph': _good_graph()}).json['data']
    assert client.post(f"/api/v1/automation/flows/incoming/{flow['incoming_token']}",
                       json={}).status_code == 404

    graph = {'nodes': [_node('t', 'trigger', sources=[{'trigger_type': 'incoming_webhook'}]),
                       _node('w', 'webhook', url='https://h/x')],
             'edges': [_edge('t', 'w')]}
    flow2 = client.post('/api/v1/flows', headers=h,
                        json={'name': 'hook', 'graph': graph}).json['data']
    res = client.post(f"/api/v1/automation/flows/incoming/{flow2['incoming_token']}",
                      json={'door': 'open'})
    assert res.status_code == 200 and res.json['data']['status'] == 'success'
    assert client.post('/api/v1/automation/flows/incoming/wrong-token', json={}).status_code == 404


def test_flow_api_requires_auth(client):
    assert client.get('/api/v1/flows').status_code == 401
