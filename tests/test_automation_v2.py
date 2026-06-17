"""Automation enhancements: new trigger types (system_event, incoming_webhook), face/object
triggers, AND/OR correlation, inline webhook action, new actions (camera enable/disable, sms),
and the system-event emitter wiring."""
from server.model import db, utcnow
from server.model.camera import Camera
from server.model.rule import Rule
from server.service import rule_dispatcher, rule_evaluator
from server.service.trigger_router import TriggerEvent
from tests.conftest import login


def _camera(name='c', host='192.0.2.50') -> Camera:
    c = Camera()
    c.name, c.host, c.vendor, c.driver, c.is_enabled = name, host, 'onvif', 'onvif', True
    db.session.add(c)
    db.session.commit()
    return c


def _trig(**kw):
    base = dict(trigger_type='event', camera_id=5, type='motion', score=80, event_id=1)
    base.update(kw)
    return TriggerEvent(**base)


# ── new trigger types match ───────────────────────────────────────────────────
def test_system_event_trigger_matches(app_db):
    r = Rule.create({'name': 'off', 'trigger_type': 'system_event',
                     'trigger': {'event_types': ['camera_offline']}, 'actions': [], 'cooldown_s': 0})
    assert rule_evaluator.evaluate(r, _trig(trigger_type='system_event', type='camera_offline')).matched
    assert rule_evaluator.evaluate(r, _trig(trigger_type='system_event', type='camera_online')).reason == 'condition_false'


def test_face_identity_trigger(app_db):
    r = Rule.create({'name': 'vip', 'trigger_type': 'event',
                     'trigger': {'event_types': ['face'], 'identity_ids': [42]}, 'actions': [], 'cooldown_s': 0})
    # specific person on ANY camera (no camera_ids condition) → matches
    assert rule_evaluator.evaluate(r, _trig(type='face', identity_id=42, camera_id=7)).matched
    assert rule_evaluator.evaluate(r, _trig(type='face', identity_id=99, camera_id=7)).reason == 'condition_false'


def test_object_on_specific_camera(app_db):
    r = Rule.create({'name': 'person-cam5', 'trigger_type': 'object',
                     'trigger': {'classes': ['person']}, 'condition': {'camera_ids': [5]},
                     'actions': [], 'cooldown_s': 0})
    assert rule_evaluator.evaluate(r, _trig(trigger_type='object', type='object', classes=['person'], camera_id=5)).matched
    assert rule_evaluator.evaluate(r, _trig(trigger_type='object', type='object', classes=['person'], camera_id=8)).reason == 'condition_false'


# ── AND/OR multi-event correlation ────────────────────────────────────────────
def test_correlation_all_of(app_db, redis_client):
    from server.service import correlation
    now = 1_700_000_000_000
    # record a motion on cam 5 "just now"
    correlation.record(_trig(type='motion', camera_id=5, ts=now))
    r = Rule.create({'name': 'corr', 'trigger_type': 'system_event',
                     'trigger': {'event_types': ['io_input_on']},
                     'condition': {'correlate': {'window_s': 60, 'mode': 'all',
                                                 'events': [{'type': 'motion', 'camera': 'any'}]}},
                     'actions': [], 'cooldown_s': 0})
    # io_input_on within the window WITH a recent motion → matches
    assert rule_evaluator.evaluate(r, _trig(trigger_type='system_event', type='io_input_on', ts=now + 5000)).matched
    # the same trigger long after the motion window → correlation unmet
    assert rule_evaluator.evaluate(
        r, _trig(trigger_type='system_event', type='io_input_on', ts=now + 120_000)).reason == 'correlation_unmet'


def test_correlation_any_of(app_db, redis_client):
    from server.service import correlation
    now = 1_700_000_000_000
    correlation.record(_trig(type='tamper', camera_id=5, ts=now))
    r = Rule.create({'name': 'corr-any', 'trigger_type': 'event', 'trigger': {'event_types': ['motion']},
                     'condition': {'correlate': {'window_s': 60, 'mode': 'any',
                                                 'events': [{'type': 'glassbreak'}, {'type': 'tamper'}]}},
                     'actions': [], 'cooldown_s': 0})
    assert rule_evaluator.evaluate(r, _trig(type='motion', ts=now + 1000)).matched


# ── inline webhook action ─────────────────────────────────────────────────────
def test_inline_webhook_action(app_db, monkeypatch):
    from server.driver import webhook as webhook_drv
    sent = {}

    def fake_request(method, url, **kw):
        sent['method'] = method
        sent['url'] = url
        sent['json'] = kw.get('json')
        sent['headers'] = kw.get('headers')
        sent['auth'] = kw.get('auth')

        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(webhook_drv, 'ssrf_check', lambda url: (True, ''))
    monkeypatch.setattr(webhook_drv.requests, 'request', fake_request)

    from server.service import action_runner
    action = {'type': 'webhook', 'params': {
        'url': 'https://hook.example.com/x', 'method': 'POST', 'body_type': 'json',
        'headers': {'X-Custom': '1'}, 'auth': {'type': 'bearer', 'token': 'abc'}}}
    res = action_runner.run(action, _trig(type='motion'))
    assert res['status'] == 'success'
    assert sent['method'] == 'POST' and sent['url'] == 'https://hook.example.com/x'
    assert sent['headers']['X-Custom'] == '1' and sent['headers']['Authorization'] == 'Bearer abc'
    assert sent['json']['type'] == 'motion'                      # event payload sent as body


def test_inline_webhook_get_with_basic_auth(app_db, monkeypatch):
    from server.driver import webhook as webhook_drv
    sent = {}

    def fake_request(method, url, **kw):
        sent.update(method=method, params=kw.get('params'), auth=kw.get('auth'))

        class R:
            status_code = 204
        return R()

    monkeypatch.setattr(webhook_drv, 'ssrf_check', lambda url: (True, ''))
    monkeypatch.setattr(webhook_drv.requests, 'request', fake_request)
    from server.service import action_runner
    action = {'type': 'webhook', 'params': {'url': 'https://h/x', 'method': 'GET',
                                            'auth': {'type': 'basic', 'username': 'u', 'password': 'p'}}}
    res = action_runner.run(action, _trig(type='motion'))
    assert res['status'] == 'success' and sent['method'] == 'GET'
    assert sent['auth'] == ('u', 'p')


def test_inline_webhook_ssrf_blocked(app_db, monkeypatch):
    monkeypatch.setattr('config.WEBHOOK_ALLOW_PRIVATE', False)
    from server.service import action_runner
    action = {'type': 'webhook', 'params': {'url': 'http://169.254.169.254/latest/'}}
    res = action_runner.run(action, _trig())
    assert res['status'] == 'failed' and res['error'].startswith('ssrf_blocked')


# ── new actions ───────────────────────────────────────────────────────────────
def test_camera_disable_enable_action(app_db, mock_go2rtc):
    cam = _camera()
    from server.service import action_runner
    res = action_runner.run({'type': 'camera_disable', 'params': {'camera_id': cam.id}}, _trig())
    assert res['status'] == 'success'
    assert Camera.get_by_id(cam.id).is_enabled is False
    res = action_runner.run({'type': 'camera_enable'}, _trig(camera_id=cam.id))
    assert res['status'] == 'success' and Camera.get_by_id(cam.id).is_enabled is True


def test_sms_action_gated_by_flag(app_db, monkeypatch):
    from server.service import action_runner, feature_flag
    monkeypatch.setattr(feature_flag, 'is_enabled', lambda key: False)
    res = action_runner.run({'type': 'sms', 'params': {'to': '+15550001111'}}, _trig())
    assert res['status'] == 'skipped'


# ── incoming webhook trigger ──────────────────────────────────────────────────
def test_incoming_webhook_token_and_fire(client, monkeypatch):
    h = login(client)
    cr = client.post('/api/v1/rules', headers=h, json={
        'name': 'inbound', 'trigger_type': 'incoming_webhook', 'actions': []})
    assert cr.status_code == 200, cr.json
    token = cr.json['data']['incoming_token']
    assert token and len(token) == 32

    fired = {}
    from server.service import rule_dispatcher as rd
    orig = rd.fire_rule

    def _capture(rule, trig):
        fired['t'] = trig
        return orig(rule, trig)

    monkeypatch.setattr(rd, 'fire_rule', _capture)

    # unauthenticated call with the token fires the rule
    r = client.post('/api/v1/automation/incoming/%s' % token, json={'hello': 'world'})
    assert r.status_code == 200
    assert fired['t'].trigger_type == 'incoming_webhook'
    assert fired['t'].context['body'] == {'hello': 'world'}

    # bad token → 404
    assert client.post('/api/v1/automation/incoming/deadbeef', json={}).status_code == 404


def test_incoming_token_cleared_when_trigger_type_changes(app_db):
    r = Rule.create({'name': 'x', 'trigger_type': 'incoming_webhook', 'actions': []})
    assert r.incoming_token is not None
    r.modify({'trigger_type': 'event'})
    assert r.incoming_token is None


# ── emitter wiring ────────────────────────────────────────────────────────────
def test_automation_emit_runs_matching_rule(app_db, monkeypatch):
    cam = _camera()
    ran = {}
    from server.service import action_runner
    monkeypatch.setattr(action_runner, 'run_all', lambda rule, trig: ran.setdefault('rule', rule.name) or [])
    Rule.create({'name': 'cam-down', 'trigger_type': 'system_event',
                 'trigger': {'event_types': ['camera_offline']},
                 'condition': {'camera_ids': [cam.id]}, 'actions': [{'type': 'webhook', 'params': {'url': 'x'}}],
                 'cooldown_s': 0})
    from server.service import automation_events
    automation_events.emit('camera_offline', camera_id=cam.id)
    assert ran.get('rule') == 'cam-down'


def test_email_action_inline_recipient(app_db, monkeypatch):
    """Email action takes an inline recipient (no pre-registered target needed)."""
    from server.driver import email as email_drv
    sent = {}

    def _send(to, payload):
        sent['to'] = to
        return {'status': 'success'}

    monkeypatch.setattr(email_drv, 'send_event_to', _send)
    from server.service import action_runner
    res = action_runner.run({'type': 'email', 'params': {'to': 'ops@example.com'}}, _trig(type='motion'))
    assert res['status'] == 'success' and sent['to'] == 'ops@example.com'


def test_push_action_custom_title_message(app_db, monkeypatch):
    """Push action carries a custom title/message into the dispatched payload."""
    from server.service import notification_router
    captured = {}
    monkeypatch.setattr(notification_router, '_dispatch_push',
                        lambda uid, payload, prio: captured.update(payload) or 1)
    from server.model.notification_subscription import NotificationSubscription
    NotificationSubscription.create(1, {'channel': 'push'})
    notification_router.push_for_trigger(_trig(type='motion'),
                                         {'title': '현관 침입', 'message': '확인하세요'})
    assert captured.get('title') == '현관 침입' and captured.get('message') == '확인하세요'
