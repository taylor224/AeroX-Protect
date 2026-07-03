"""Live-viewer activity tracking (idle-stop gate). Redis = fakeredis from conftest;
fail-open semantics are the critical property — a Redis blip must never black out live."""
import pytest

import server.service.live_activity as la
from server.model.setting import Setting


def test_mark_then_active_roundtrip():
    name = 'cam_act_rt_sub'
    assert la.is_active(name, 60) is False        # nothing marked yet
    la.mark(name, 60)
    assert la.is_active(name, 60) is True


def test_window_zero_disables_gating():
    name = 'cam_act_zero_sub'
    la.mark(name, 0)                              # no-op — nothing written
    from server.service.token import get_redis
    assert get_redis().exists(la.KEY_PREFIX + name) == 0
    assert la.is_active(name, 0) is True          # always-warm mode


def test_mark_ttl_floor():
    """TTL never below 15s even for a tiny window (covers the connect race)."""
    name = 'cam_act_ttl_sub'
    la.mark(name, 5)
    from server.service.token import get_redis
    assert 0 < get_redis().ttl(la.KEY_PREFIX + name) <= 15


def test_is_active_fails_open_on_redis_error(monkeypatch):
    class _Boom:
        def exists(self, *a):
            raise RuntimeError('redis down')

        def set(self, *a, **k):
            raise RuntimeError('redis down')

    import server.service.token as token_mod
    monkeypatch.setattr(token_mod, 'get_redis', lambda: _Boom())
    la.mark('cam_act_err_sub', 60)                          # must not raise
    assert la.is_active('cam_act_err_sub', 60) is True      # fail-open


def test_idle_window_reads_setting(app_db):
    assert la.idle_window() == 300                          # seed default
    Setting.set_value('live_transcode_idle_s', 0)
    assert la.idle_window() == 0
    Setting.set_value('live_transcode_idle_s', 120)
    assert la.idle_window() == 120
