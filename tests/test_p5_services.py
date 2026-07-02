"""P5 services: clause matching, pairing, api tokens, webhook driver (HMAC/SSRF), cron,
and the trigger→flow→webhook pipeline. (Rule engine + subscription notification router
were retired — flows are the automation surface, see tests/test_flows.py.)"""
import hashlib
import hmac

import pytest

from server.driver import webhook as webhook_drv
from server.model.api_token import ApiToken
from server.model.monitor import Monitor
from server.model.webhook_endpoint import WebhookEndpoint
from server.service import api_token as api_token_svc
from server.service import clause, flow_engine, pairing_code
from server.service.trigger_router import TriggerEvent
from server.util.cron import cron_match


class FakeResp:
    def __init__(self, status):
        self.status_code = status


def _trig(**kw):
    base = dict(trigger_type='event', camera_id=5, type='motion', score=80, event_id=1)
    base.update(kw)
    return TriggerEvent(**base)


# ── clause matching (flow condition nodes) ───────────────────────────────────
def test_clause_ops_whitelist(app_db):
    assert clause.match_clause({'field': 'score', 'op': 'gte', 'value': 70}, _trig(score=80))
    assert not clause.match_clause({'field': 'score', 'op': 'gte', 'value': 90}, _trig(score=80))
    assert clause.match_clause({'field': 'type', 'op': 'in', 'value': ['motion', 'tamper']}, _trig(type='motion'))
    assert not clause.match_clause({'field': 'score', 'op': 'evil', 'value': 1}, _trig())   # unknown op → False
    assert clause.match_clause({'field': 'object_class', 'op': 'in', 'value': ['person']},
                               _trig(classes=['person', 'car']))


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


# ── full pipeline: trigger → flow → webhook action → run log ──────────────────
def test_pipeline_flow_to_webhook(app_db, monkeypatch):
    calls = {'n': 0}

    def fake_post(url, **kw):
        calls['n'] += 1
        return FakeResp(200)

    monkeypatch.setattr(webhook_drv.requests, 'post', fake_post)
    ep = WebhookEndpoint.create({'name': 'hk', 'url': 'http://10.0.0.9/h', 'secret': 'x'})
    from server.model.flow import Flow
    Flow.create({'name': 'motion-hook', 'graph': {
        'nodes': [
            {'id': 't', 'type': 'trigger', 'position': {'x': 0, 'y': 0},
             'data': {'sources': [{'trigger_type': 'event', 'event_types': ['motion']}]}},
            {'id': 'w', 'type': 'webhook', 'position': {'x': 200, 'y': 0},
             'data': {'target_id': int(ep.id)}}],
        'edges': [{'id': 'e', 'source': 't', 'target': 'w', 'sourceHandle': 'out'}]}})
    runs = flow_engine.on_trigger(_trig(type='motion', event_id=500))
    assert len(runs) == 1 and runs[0].status == 'success'
    assert calls['n'] == 1
    by_node = {r['node_id']: r for r in runs[0].node_results}
    assert by_node['w']['status'] == 'success'


def _dashboard():
    from server.model.dashboard import Dashboard
    return Dashboard.create(name='D', layout={'tiles': []}, owner_id=1).id
