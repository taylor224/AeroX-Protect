"""Web-admin CLIP model installer (semantic search A1 follow-up)."""
import pytest

from tests.conftest import create_user, login


@pytest.fixture(autouse=True)
def _reset_installer_state():
    from server.service import ai_model_setup
    with ai_model_setup._lock:
        ai_model_setup._state.update(phase='idle', variant=None, error=None)
        ai_model_setup._state['log'].clear()
    yield
    with ai_model_setup._lock:
        ai_model_setup._state.update(phase='idle', variant=None, error=None)
        ai_model_setup._state['log'].clear()


# ── status ────────────────────────────────────────────────────────────────────
def test_model_status_unsupported_by_default(client):
    h = login(client)
    r = client.get('/api/v1/search/semantic/model', headers=h)
    assert r.status_code == 200
    data = r.json['data']
    assert data['supported'] is False
    assert data['installed'] is False
    assert data['phase'] == 'idle'
    assert data['backend'] in ('hash', 'clip')


def test_model_status_flag_gate(client):
    h = login(client)
    client.put('/api/v1/feature-flags/semantic_search', headers=h, json={'enabled': False})
    assert client.get('/api/v1/search/semantic/model', headers=h).status_code == 403


# ── install endpoint ──────────────────────────────────────────────────────────
def test_install_501_when_unsupported(client):
    h = login(client)
    r = client.post('/api/v1/search/semantic/model/install', headers=h, json={'variant': 'cpu'})
    assert r.status_code == 501


def test_install_starts_and_conflicts(client, monkeypatch, tmp_path):
    import config
    from server.service import ai_model_setup
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(tmp_path / 'extras'))
    monkeypatch.setattr(ai_model_setup, '_run', lambda variant: None)  # don't spawn pip

    h = login(client)
    r = client.post('/api/v1/search/semantic/model/install', headers=h, json={'variant': 'cpu'})
    assert r.status_code == 200 and r.json['data']['started'] is True
    # job thread was a no-op but state says installing → second start conflicts
    r2 = client.post('/api/v1/search/semantic/model/install', headers=h, json={'variant': 'cpu'})
    assert r2.status_code == 409

    status = client.get('/api/v1/search/semantic/model', headers=h).json['data']
    assert status['supported'] is True
    assert status['phase'] == 'installing'
    assert status['variant'] == 'cpu'


def test_install_bad_variant(client, monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(tmp_path / 'extras'))
    h = login(client)
    r = client.post('/api/v1/search/semantic/model/install', headers=h, json={'variant': 'tpu'})
    assert r.status_code == 400


def test_install_requires_settings_update(client, monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(tmp_path / 'extras'))
    h = login(client)
    create_user(client, h, 'clip_u', {'ai': ['semantic_search']})  # can search, not install
    vh = login(client, 'clip_u', 'viewer1234!')
    r = client.post('/api/v1/search/semantic/model/install', headers=vh, json={'variant': 'cpu'})
    assert r.status_code == 403


# ── install job ───────────────────────────────────────────────────────────────
class _FakePip:
    def __init__(self, code: int, lines=('Collecting torch', 'Installing collected packages')):
        self.stdout = iter(line + '\n' for line in lines)
        self._code = code

    def wait(self):
        return self._code


def test_run_success_activates_clip(monkeypatch, tmp_path, app_db):
    import config
    from server.service import ai_model_setup, semantic_embed
    extras = tmp_path / 'extras'
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(extras))
    monkeypatch.setattr(ai_model_setup.subprocess, 'Popen', lambda *a, **k: _FakePip(0))
    monkeypatch.setattr(semantic_embed, 'reset', lambda: None)
    monkeypatch.setattr(semantic_embed, 'active_backend', lambda: 'clip')

    ai_model_setup._state['phase'] = 'installing'
    ai_model_setup._run('cpu')
    st = ai_model_setup.status()
    assert st['phase'] == 'done'
    assert extras.is_dir()
    assert any('Collecting torch' in line for line in st['log'])


def test_run_pip_failure(monkeypatch, tmp_path, app_db):
    import config
    from server.service import ai_model_setup
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(tmp_path / 'extras'))
    monkeypatch.setattr(ai_model_setup.subprocess, 'Popen',
                        lambda *a, **k: _FakePip(1, ('ERROR: no matching distribution',)))

    ai_model_setup._state['phase'] = 'installing'
    ai_model_setup._run('cpu')
    st = ai_model_setup.status()
    assert st['phase'] == 'error'
    assert 'pip exited 1' in st['error']


def test_run_activation_failure(monkeypatch, tmp_path, app_db):
    import config
    from server.service import ai_model_setup, semantic_embed
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(tmp_path / 'extras'))
    monkeypatch.setattr(ai_model_setup.subprocess, 'Popen', lambda *a, **k: _FakePip(0))
    monkeypatch.setattr(semantic_embed, 'reset', lambda: None)
    monkeypatch.setattr(semantic_embed, 'active_backend', lambda: 'hash')  # deps ok, import not

    ai_model_setup._state['phase'] = 'installing'
    ai_model_setup._run('cpu')
    assert ai_model_setup.status()['phase'] == 'error'


def test_extras_dir_defaults_from_axp_home(monkeypatch, tmp_path):
    """Native installs (old launcher included) get the installer via AXP_HOME alone."""
    import importlib

    import config as cfg
    monkeypatch.setenv('AXP_HOME', str(tmp_path))
    monkeypatch.delenv('AXP_AI_EXTRAS_DIR', raising=False)
    monkeypatch.delenv('HF_HOME', raising=False)
    try:
        importlib.reload(cfg)
        assert cfg.AI_EXTRAS_DIR == str(tmp_path / 'extras' / 'site-packages-ai')
        assert cfg.os.environ['HF_HOME'] == str(tmp_path / 'extras' / 'hf-cache')

        monkeypatch.setenv('AXP_AI_EXTRAS_DIR', str(tmp_path / 'elsewhere'))
        importlib.reload(cfg)
        assert cfg.AI_EXTRAS_DIR == str(tmp_path / 'elsewhere')  # explicit env wins

        monkeypatch.delenv('AXP_AI_EXTRAS_DIR')
        monkeypatch.delenv('AXP_HOME')
        importlib.reload(cfg)
        assert cfg.AI_EXTRAS_DIR is None  # Docker: unsupported
    finally:
        monkeypatch.delenv('AXP_HOME', raising=False)
        monkeypatch.delenv('AXP_AI_EXTRAS_DIR', raising=False)
        importlib.reload(cfg)


def test_installed_detection(monkeypatch, tmp_path):
    import config
    from server.service import ai_model_setup
    extras = tmp_path / 'extras'
    monkeypatch.setattr(config, 'AI_EXTRAS_DIR', str(extras))
    assert ai_model_setup.installed() is False
    (extras / 'open_clip').mkdir(parents=True)
    (extras / 'torch').mkdir()
    assert ai_model_setup.installed() is True
