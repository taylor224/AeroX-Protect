"""P6 N1 — Twilio SMS notification channel (HTTP, no SDK)."""
import config
from tests.conftest import login


class _Resp:
    def __init__(self, status=201, sid='SM1'):
        self.status_code = status
        self.content = b'{"sid":"%s"}' % sid.encode()
        self.text = ''
        self._sid = sid

    def json(self):
        return {'sid': self._sid}


def _twilio_on(monkeypatch):
    monkeypatch.setattr(config, 'TWILIO_ACCOUNT_SID', 'AC123')
    monkeypatch.setattr(config, 'TWILIO_AUTH_TOKEN', 'tok')
    monkeypatch.setattr(config, 'TWILIO_FROM_NUMBER', '+15550000000')


def test_sms_driver_posts_to_twilio(monkeypatch):
    from server.driver import sms
    _twilio_on(monkeypatch)
    calls = {}

    def fake_post(url, **kw):
        calls.update(url=url, data=kw.get('data'), auth=kw.get('auth'))
        return _Resp()

    monkeypatch.setattr(sms.requests, 'post', fake_post)
    r = sms.send_event_to('+15551234567', {'type': 'motion', 'camera_id': '1', 'ts': 1700000000000})
    assert r['status'] == 'success' and r['sid'] == 'SM1'
    assert calls['auth'] == ('AC123', 'tok')
    assert calls['data']['To'] == '+15551234567' and calls['data']['From'] == '+15550000000'
    assert 'Accounts/AC123/Messages.json' in calls['url']


def test_sms_skips_when_unconfigured(monkeypatch):
    from server.driver import sms
    monkeypatch.setattr(config, 'TWILIO_ACCOUNT_SID', None)
    assert sms.send_event_to('+1', {})['status'] == 'skipped'


def test_sms_skips_without_recipient():
    from server.driver import sms
    assert sms.send_event_to('', {})['status'] == 'skipped'


def test_sms_subscription_and_router_dispatch(client, monkeypatch):
    from server.driver import sms
    from server.service import notification_router
    _twilio_on(monkeypatch)
    monkeypatch.setattr(sms.requests, 'post', lambda *a, **k: _Resp(status=201))

    h = login(client)
    cr = client.post('/api/v1/notification-subscriptions', headers=h, json={
        'channel': 'sms', 'sms_to': '+15551234567', 'event_types': ['motion'], 'min_priority': 'normal'})
    assert cr.status_code == 200, cr.json
    assert cr.json['data']['sms_to'] == '+15551234567' and cr.json['data']['channel'] == 'sms'

    counts = notification_router.route_event(
        {'id': '1', 'type': 'motion', 'camera_id': '1', 'ts': 1700000000000})
    assert counts['sms'] >= 1


def test_sms_dispatch_respects_flag(client, monkeypatch):
    from server.driver import sms
    from server.service import notification_router
    _twilio_on(monkeypatch)
    monkeypatch.setattr(sms.requests, 'post', lambda *a, **k: _Resp())

    h = login(client)
    client.post('/api/v1/notification-subscriptions', headers=h, json={
        'channel': 'sms', 'sms_to': '+15551234567', 'event_types': ['motion']})
    client.put('/api/v1/feature-flags/sms_notifications', headers=h, json={'enabled': False})
    counts = notification_router.route_event(
        {'id': '2', 'type': 'motion', 'camera_id': '1', 'ts': 1700000000000})
    assert counts['sms'] == 0     # flag off → no SMS


# ── DB-stored Twilio config (admin UI) ───────────────────────────────────────
def test_twilio_config_db_overrides_env(app_db, monkeypatch):
    """set_config persists; get_config decrypts the token and DB wins over env."""
    import config
    from server.service import twilio_config
    monkeypatch.setattr(config, 'TWILIO_ACCOUNT_SID', 'ENV_SID')   # env present…
    monkeypatch.setattr(config, 'TWILIO_AUTH_TOKEN', 'ENV_TOK')
    monkeypatch.setattr(config, 'TWILIO_FROM_NUMBER', '+1ENV')

    st = twilio_config.set_config(account_sid='AC_DB', auth_token='secret-tok', from_number='+15550001111')
    assert st['configured'] is True and st['has_token'] is True
    assert 'auth_token' not in st and 'secret-tok' not in str(st)   # status never leaks the token

    cfg = twilio_config.get_config()
    assert cfg['account_sid'] == 'AC_DB'                            # …DB overrides env
    assert cfg['auth_token'] == 'secret-tok'                       # decrypted round-trip
    assert cfg['from_number'] == '+15550001111'

    # stored ciphertext is not the plaintext
    from server.model.setting import Setting
    row = Setting.get_value('twilio')
    assert row['auth_token_enc'] and row['auth_token_enc'] != 'secret-tok'

    # clearing the token (empty string) wipes it; SID untouched (None = leave)
    twilio_config.set_config(auth_token='')
    assert twilio_config.get_config()['auth_token'] == 'ENV_TOK'    # falls back to env
    assert twilio_config.get_config()['account_sid'] == 'AC_DB'


def test_twilio_settings_api(client):
    h = login(client)
    assert client.get('/api/v1/settings/twilio', headers=h).json['data']['configured'] is False
    up = client.put('/api/v1/settings/twilio', headers=h, json={
        'account_sid': 'AC_API', 'auth_token': 'apitok', 'from_number': '+15559998888'})
    assert up.status_code == 200, up.json
    assert up.json['data']['configured'] is True and up.json['data']['account_sid'] == 'AC_API'
    assert 'apitok' not in str(up.json)                            # token never returned
    got = client.get('/api/v1/settings/twilio', headers=h).json['data']
    assert got['has_token'] is True and got['from_number'] == '+15559998888'
