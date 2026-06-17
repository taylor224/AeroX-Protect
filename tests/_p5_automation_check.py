"""Manual P5 e2e against the live stack: rule (event motion → webhook) fires from a simulated
event via the outbox consumer and delivers a signed POST to a local receiver; monitor pairing
(create→code→claim→/monitor/me scope→revoke→401); external API token (scope→/ext→revoke→401).

A tiny host HTTP receiver captures the webhook; the backend container reaches it via
host.docker.internal (dev SSRF guard allows private). Run:
    .venv/bin/python tests/_p5_automation_check.py
"""
import hashlib
import hmac
import http.server
import json
import socket
import sys
import threading
import time

import requests

BACKEND = 'http://localhost:10000/api/v1'
ok = fail = 0
RECEIVED = []


def check(label, cond, extra=''):
    global ok, fail
    ok, fail = (ok + 1, fail) if cond else (ok, fail + 1)
    print(('  ✓ ' if cond else '  ✗ FAIL: ') + label + (('  — ' + extra) if extra and not cond else ''))


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        RECEIVED.append({'headers': dict(self.headers), 'body': body})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


def _free_port():
    s = socket.socket()
    s.bind(('0.0.0.0', 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
HOOK_URL = 'http://host.docker.internal:%d/hook' % PORT
SECRET = 's3cr3t-p5'
print('— webhook receiver on host port %d' % PORT)

print('— login')
token = requests.post(f'{BACKEND}/auth/login',
                      json={'login_id': 'admin', 'password': 'admin1234!'}).json()['data']['access_token']
H = {'Authorization': f'Bearer {token}'}

# ── webhook target + delivery test ──────────────────────────────────────────────
print('— create webhook + test delivery (HMAC)')
wh = requests.post(f'{BACKEND}/webhooks', headers=H, json={'name': 'sink', 'url': HOOK_URL, 'secret': SECRET})
hook = wh.json().get('data', {})
check('webhook created', wh.status_code == 200 and hook.get('uuid'))
RECEIVED.clear()
tr = requests.post(f"{BACKEND}/webhooks/{hook['uuid']}/test", headers=H, json={})
check('test delivery success', tr.status_code == 200 and tr.json()['data'].get('status') == 'success', tr.text[:200])
time.sleep(0.5)
check('receiver got the POST', len(RECEIVED) >= 1)
if RECEIVED:
    rec = RECEIVED[-1]
    ts = rec['headers'].get('X-Axp-Timestamp', '')
    expect = hmac.new(SECRET.encode(), (ts + '.').encode() + rec['body'], hashlib.sha256).hexdigest()
    check('HMAC signature valid', rec['headers'].get('X-Axp-Signature') == 'sha256=' + expect)

# ── rule fires from a simulated event via the outbox consumer ────────────────────
print('— create camera + rule (event motion → webhook)')
cam = requests.post(f'{BACKEND}/cameras', headers=H, json={
    'name': 'RuleCam', 'host': '192.0.2.77', 'vendor': 'onvif', 'driver': 'onvif',
    'rtsp_port': 554, 'username': 'admin', 'password': 'secret',
    'streams': [{'role': 'main', 'rtsp_path': '/main'}]}).json()['data']
rule = requests.post(f'{BACKEND}/rules', headers=H, json={
    'name': 'motion-webhook', 'trigger_type': 'event', 'trigger': {'event_types': ['motion']},
    'condition': {}, 'actions': [{'type': 'webhook', 'target_id': int(hook['id'])}], 'cooldown_s': 0})
check('rule created', rule.status_code == 200, rule.text[:200])
rule_uuid = rule.json().get('data', {}).get('uuid')

print('— simulate motion event → outbox → rule → webhook (waiting for consumer beat)')
RECEIVED.clear()
requests.post(f'{BACKEND}/events/simulate', headers=H,
              json={'camera_uuid': cam['uuid'], 'type': 'motion', 'score': 80})
fired = False
for _ in range(8):
    time.sleep(3)
    if RECEIVED:
        fired = True
        break
check('rule delivered webhook from event', fired)
ex = requests.get(f'{BACKEND}/rule-executions', headers=H, params={'rule_id': rule.json()['data']['id']})
exitems = ex.json().get('data', {}).get('items', []) if ex.status_code == 200 else []
check('rule execution logged success', any(e['status'] == 'success' for e in exitems), str(exitems[:1]))

print('— manual fire endpoint')
mf = requests.post(f'{BACKEND}/rules/{rule_uuid}/trigger', headers=H, json={})
check('manual trigger success', mf.status_code == 200 and mf.json()['data']['status'] == 'success')

# ── monitor pairing ─────────────────────────────────────────────────────────────
print('— monitor pairing: create → code → claim → /monitor/me → revoke → 401')
dash = requests.post(f'{BACKEND}/dashboards', headers=H,
                     json={'name': 'KioskDash', 'layout': {'grid': {'cols': 12, 'rows': 8}, 'cells': [], 'ratio_mode': 'fit'}})
dash_uuid = dash.json().get('data', {}).get('uuid')
check('dashboard created', dash.status_code == 200 and dash_uuid)
mon = requests.post(f'{BACKEND}/monitors', headers=H, json={'name': 'lobby-tv', 'dashboard_uuid': dash_uuid})
mon_uuid = mon.json().get('data', {}).get('uuid')
check('monitor created', mon.status_code == 200 and mon_uuid)
pc = requests.post(f'{BACKEND}/monitors/{mon_uuid}/pair-code', headers=H, json={})
code = pc.json().get('data', {}).get('code')
check('pair code (6 digit, 60s)', bool(code) and len(code) == 6 and pc.json()['data']['expires_in'] == 60)
claim = requests.post(f'{BACKEND}/pairing/claim', json={'code': code})
mtoken = claim.json().get('data', {}).get('access_token')
check('claim → monitor token', claim.status_code == 200 and bool(mtoken))
me = requests.get(f'{BACKEND}/monitor/me', headers={'Authorization': f'Bearer {mtoken}'})
check('monitor /me scoped to dashboard', me.status_code == 200 and me.json()['data']['dashboard']['uuid'] == dash_uuid)
check('claim reuse rejected', requests.post(f'{BACKEND}/pairing/claim', json={'code': code}).status_code == 400)
requests.post(f'{BACKEND}/monitors/{mon_uuid}/revoke', headers=H, json={})
check('revoke invalidates monitor token',
      requests.get(f'{BACKEND}/monitor/me', headers={'Authorization': f'Bearer {mtoken}'}).status_code == 401)

# ── external API token ──────────────────────────────────────────────────────────
print('— external API token: scope → /ext/events → revoke → 401')
at = requests.post(f'{BACKEND}/api-tokens', headers=H,
                   json={'name': 'HA', 'scopes': {'events': ['read'], 'state': ['read']}})
raw = at.json().get('data', {}).get('token')
at_uuid = at.json().get('data', {}).get('uuid')
check('api token issued (axp_ prefix)', bool(raw) and raw.startswith('axp_'))
ev = requests.get(f'{BACKEND}/ext/events', headers={'Authorization': f'Bearer {raw}'})
check('ext events with token', ev.status_code == 200 and 'items' in ev.json().get('data', {}))
st = requests.get(f'{BACKEND}/ext/state', headers={'X-API-Key': raw})
check('ext state (X-API-Key)', st.status_code == 200 and 'cameras' in st.json().get('data', {}))
requests.post(f'{BACKEND}/api-tokens/{at_uuid}/revoke', headers=H, json={})
check('revoked token → 401',
      requests.get(f'{BACKEND}/ext/events', headers={'Authorization': f'Bearer {raw}'}).status_code == 401)

print('— cleanup')
requests.delete(f"{BACKEND}/rules/{rule_uuid}", headers=H)
requests.delete(f"{BACKEND}/cameras/{cam['uuid']}", headers=H)
server.shutdown()

print('\nRESULT: %d passed, %d failed' % (ok, fail))
sys.exit(1 if fail else 0)
