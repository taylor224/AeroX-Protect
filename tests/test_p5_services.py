"""P5 services: rule evaluator, pairing, api tokens, webhook driver (HMAC/SSRF), notification
router, cron, and the outbox→rule→action pipeline."""
import hashlib
import hmac
import json

import pytest

from server.driver import webhook as webhook_drv
from server.model import db, utcnow
from server.model.api_token import ApiToken
from server.model.monitor import Monitor
from server.model.notification import Notification
from server.model.notification_subscription import NotificationSubscription
from server.model.rule import Rule
from server.model.webhook_endpoint import WebhookEndpoint
from server.service import api_token as api_token_svc
from server.service import notification_router, pairing_code, rule_dispatcher, rule_evaluator
from server.service.trigger_router import TriggerEvent
from server.util.cron import cron_match


class FakeResp:
    def __init__(self, status):
        self.status_code = status


def _trig(**kw):
    base = dict(trigger_type='event', camera_id=5, type='motion', score=80, event_id=1)
    base.update(kw)
    return TriggerEvent(**base)


# ── rule evaluator ───────────────────────────────────────────────────────────
def test_evaluate_event_type_match(app_db):
    r = Rule.create({'name': 'm', 'trigger_type': 'event', 'trigger': {'event_types': ['motion']},
                     'actions': [], 'cooldown_s': 0})
    assert rule_evaluator.evaluate(r, _trig(type='motion')).matched
    assert rule_evaluator.evaluate(r, _trig(type='tamper')).reason == 'condition_false'


def test_evaluate_object_confidence(app_db):
    r = Rule.create({'name': 'p', 'trigger_type': 'object', 'trigger': {'classes': ['person'], 'min_confidence': 60},
                     'actions': [], 'cooldown_s': 0})
    assert rule_evaluator.evaluate(r, _trig(trigger_type='object', type='object', classes=['person'], score=80)).matched
    assert rule_evaluator.evaluate(r, _trig(trigger_type='object', type='object', classes=['person'], score=40)).reason == 'condition_false'


def test_evaluate_condition_camera_and_clause(app_db):
    r = Rule.create({'name': 'c', 'trigger_type': 'event', 'trigger': {},
                     'condition': {'camera_ids': [5], 'all_of': [{'field': 'score', 'op': 'gte', 'value': 70}]},
                     'actions': [], 'cooldown_s': 0})
    assert rule_evaluator.evaluate(r, _trig(camera_id=5, score=80)).matched
    assert rule_evaluator.evaluate(r, _trig(camera_id=9, score=80)).reason == 'condition_false'
    assert rule_evaluator.evaluate(r, _trig(camera_id=5, score=50)).reason == 'condition_false'


def test_cooldown_and_idempotency(app_db):
    r = Rule.create({'name': 'cd', 'trigger_type': 'event', 'trigger': {}, 'actions': [],
                     'cooldown_s': 60, 'dedup_scope': 'camera'})
    trig = _trig(camera_id=5, event_id=100)
    assert rule_evaluator.evaluate(r, trig).matched
    rule_evaluator.mark_cooldown(r, trig)
    assert rule_evaluator.evaluate(r, _trig(camera_id=5, event_id=101)).reason == 'cooldown'
    # idempotency: first claim wins, duplicate loses
    assert rule_evaluator.claim_idempotency(r, trig) is True
    assert rule_evaluator.claim_idempotency(r, trig) is False


def test_time_ranges_kst():
    # Mon 2026-06-08 09:00 KST = 00:00 UTC → epoch ms
    import datetime
    from server.model import KST
    ts = int(datetime.datetime(2026, 6, 8, 9, 0, tzinfo=KST).timestamp() * 1000)
    assert rule_evaluator.in_time_ranges(ts, [{'dow': [1], 'start': '08:00', 'end': '18:00'}])
    assert not rule_evaluator.in_time_ranges(ts, [{'dow': [1], 'start': '10:00', 'end': '18:00'}])


# ── cron ─────────────────────────────────────────────────────────────────────
def test_cron_match():
    import datetime
    mon9 = datetime.datetime(2026, 6, 8, 9, 0)        # Monday 09:00
    assert cron_match('0 9 * * 1-5', mon9)
    assert not cron_match('0 9 * * 6,0', mon9)
    assert cron_match('*/15 * * * *', datetime.datetime(2026, 6, 8, 9, 30))
    assert not cron_match('*/15 * * * *', datetime.datetime(2026, 6, 8, 9, 31))


# ── pairing ──────────────────────────────────────────────────────────────────
def test_pairing_issue_claim_once(app_db):
    d_id = _dashboard()
    m = Monitor.create('lobby', d_id)
    issued = pairing_code.issue(m)
    code = issued['code']
    assert len(code) == 6 and code.isdigit()
    monitor, pair = pairing_code.claim(code)
    assert monitor.uuid == m.uuid and pair['access_token']
    with pytest.raises(ValueError):
        pairing_code.claim(code)                       # one-time — already consumed


def test_pairing_wrong_code(app_db):
    with pytest.raises(ValueError):
        pairing_code.claim('000000')


# ── api tokens ───────────────────────────────────────────────────────────────
def test_api_token_verify_scope_revoke(app_db):
    tok, raw = ApiToken.issue('HA', {'events': ['read'], 'state': ['read']})
    assert api_token_svc.verify(raw).id == tok.id
    assert tok.has_scope('events', 'read') and not tok.has_scope('events', 'write')
    tok.revoke()
    assert api_token_svc.verify(raw) is None
    assert api_token_svc.verify('axp_bogus') is None


# ── webhook driver ───────────────────────────────────────────────────────────
def test_webhook_hmac_and_delivery(app_db, monkeypatch):
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None, verify=None, allow_redirects=None):
        captured['url'] = url
        captured['data'] = data
        captured['headers'] = headers
        return FakeResp(200)

    monkeypatch.setattr(webhook_drv.requests, 'post', fake_post)
    ep = WebhookEndpoint.create({'name': 'hk', 'url': 'http://10.0.0.5/hook', 'secret': 's3cret'})
    res = webhook_drv.deliver(ep, {'type': 'motion', 'camera_id': '5'})
    assert res['status'] == 'success' and res['signature_sent']
    # verify HMAC: sha256(ts.body)
    ts = captured['headers']['X-Axp-Timestamp']
    expect = hmac.new(b's3cret', (ts + '.').encode() + captured['data'], hashlib.sha256).hexdigest()
    assert captured['headers']['X-Axp-Signature'] == 'sha256=' + expect


def test_webhook_ssrf_guard(app_db, monkeypatch):
    monkeypatch.setattr('config.WEBHOOK_ALLOW_PRIVATE', False)
    assert webhook_drv.ssrf_check('http://169.254.169.254/latest/')[0] is False   # metadata
    assert webhook_drv.ssrf_check('http://10.0.0.1/')[0] is False                  # private
    assert webhook_drv.ssrf_check('ftp://x/')[0] is False                          # scheme
    assert webhook_drv.ssrf_check('http://8.8.8.8/')[0] is True                    # public


def test_webhook_ssrf_metadata_blocked_even_when_private_allowed(app_db, monkeypatch):
    # cloud-metadata / loopback must stay blocked even with the LAN opt-in flag on
    monkeypatch.setattr('config.WEBHOOK_ALLOW_PRIVATE', True)
    assert webhook_drv.ssrf_check('http://169.254.169.254/latest/meta-data/')[0] is False
    assert webhook_drv.ssrf_check('http://127.0.0.1:6379/')[0] is False
    assert webhook_drv.ssrf_check('http://10.0.0.9/hook')[0] is True               # LAN allowed when opted in
    # unresolvable host fails closed
    assert webhook_drv.ssrf_check('http://no-such-host.invalid/')[0] is False


def test_webhook_retry_classification():
    assert webhook_drv.is_retryable({'status': 'failed', 'http_status': 503})
    assert webhook_drv.is_retryable({'status': 'failed', 'error': 'timeout'})
    assert not webhook_drv.is_retryable({'status': 'failed', 'http_status': 400})
    assert not webhook_drv.is_retryable({'status': 'success', 'http_status': 200})


# ── notification router ──────────────────────────────────────────────────────
def test_notification_routing_and_mute(app_db):
    uid = 1
    NotificationSubscription.create(uid, {'channel': 'inapp', 'event_types': ['motion']})
    payload = {'id': '777', 'camera_id': '5', 'type': 'motion', 'subtype': 'motion', 'ts': None}
    counts = notification_router.route_event(payload)
    assert counts['inapp'] == 1
    total, unread, _ = Notification.list_for_user(uid)
    assert total >= 1 and unread >= 1
    # mute → suppressed
    sub = NotificationSubscription.list_for_user(uid)[0]
    sub.modify({'muted': True})
    assert notification_router.route_event({**payload, 'id': '778'})['inapp'] == 0


def test_notification_priority_floor(app_db):
    NotificationSubscription.create(1, {'channel': 'inapp', 'min_priority': 'critical'})
    # a 'high' priority object event is below the 'critical' floor → suppressed
    counts = notification_router.route_event({'id': '9', 'camera_id': '5', 'type': 'object', 'subtype': 'person', 'ts': None})
    assert counts['inapp'] == 0


# ── full pipeline: trigger → rule → webhook action → execution log ────────────
def test_pipeline_rule_to_webhook(app_db, monkeypatch):
    calls = {'n': 0}

    def fake_post(url, **kw):
        calls['n'] += 1
        return FakeResp(200)

    monkeypatch.setattr(webhook_drv.requests, 'post', fake_post)
    ep = WebhookEndpoint.create({'name': 'hk', 'url': 'http://10.0.0.9/h', 'secret': 'x'})
    Rule.create({'name': 'motion-hook', 'trigger_type': 'event', 'trigger': {'event_types': ['motion']},
                 'actions': [{'type': 'webhook', 'target_id': int(ep.id)}], 'cooldown_s': 0})
    execs = rule_dispatcher.on_trigger(_trig(type='motion', event_id=500))
    assert len(execs) == 1 and execs[0].status == 'success'
    assert calls['n'] == 1
    assert execs[0].action_results[0]['type'] == 'webhook'


def _dashboard():
    from server.model.dashboard import Dashboard
    return Dashboard.create(name='D', layout={'tiles': []}, owner_id=1).id
