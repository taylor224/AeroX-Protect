"""Keep-warm consumers for live transcodes (2026-06-14; idle-stop 2026-07-03).

go2rtc runs the H.265→H.264 live transcode on-demand and stops it when the last viewer
leaves, so every viewer cold-starts ffmpeg and waits for a keyframe (visible breakup). The
recorder supervisor holds one throwaway consumer open per live_transcode camera to keep the
transcode running — but only while someone actually watches (live_activity gate): idle
cameras drop their warm consumer so go2rtc stops the transcode and frees the CPU. These
exercise the deterministic logic with subprocess.Popen mocked — real ffmpeg/go2rtc are
unavailable here.
"""
import server.service.live_activity as la
from worker.recorder import supervisor as sup


class _Stream:
    def __init__(self, sid, role, full=False, live=False, enabled=True):
        self.id, self.role = sid, role
        self.is_default_full, self.is_default_live = full, live
        self.enabled = enabled
        self.go2rtc_name = 'cam_%s' % role


class _Cam:
    def __init__(self, cid, streams, transcode=True):
        self.id, self.streams, self.live_transcode = cid, streams, transcode


class _Popen:
    def __init__(self, *a, **k):
        self.pid = 7777
        self.args = a[0] if a else None

    def poll(self):
        return None                          # pretend still running

    def send_signal(self, sig):
        pass

    def wait(self, timeout=None):
        return 0


def _activity(monkeypatch, active=True, window=300):
    """Standard warm-tick harness: viewer-poll off, activity forced."""
    monkeypatch.setattr(sup.RecorderSupervisor, '_refresh_viewer_activity',
                        lambda self, cam, stream, w: None)
    monkeypatch.setattr(la, 'idle_window', lambda: window)
    monkeypatch.setattr(la, 'is_active', lambda name, w=None: active)


def test_warm_stream_selection():
    s = sup.RecorderSupervisor()
    main = _Stream(10, 'main', full=True)
    sub = _Stream(11, 'sub', live=True)

    # live_transcode on + a default-live stream → warm that stream
    assert s._warm_stream(_Cam(1, [main, sub], transcode=True)).id == 11
    # live_transcode OFF → nothing to keep warm (copy stream cold-starts cheaply)
    assert s._warm_stream(_Cam(2, [main, sub], transcode=False)) is None
    # no default-live stream → nothing to warm
    assert s._warm_stream(_Cam(3, [main], transcode=True)) is None
    # a disabled default-live stream is not warmed
    assert s._warm_stream(_Cam(4, [main, _Stream(12, 'sub', live=True, enabled=False)])) is None


def test_keepwarm_cmd_is_copy_to_null():
    cmd = sup.ffmpeg.build_keepwarm_cmd('rtsp://go2rtc:8554/cam_x_sub')
    assert 'rtsp://go2rtc:8554/cam_x_sub' in cmd
    assert '-c' in cmd and 'copy' in cmd            # demux only, no decode
    assert cmd[-3:] == ['-f', 'null', '-']          # discarded to the null muxer
    assert '-rtsp_transport' in cmd and 'tcp' in cmd


def test_tick_warm_starts_only_transcode_cameras(monkeypatch):
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
    _activity(monkeypatch, active=True)
    transcode = _Cam(200, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    copy_cam = _Cam(201, [_Stream(20, 'main', full=True, live=True)], transcode=False)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [transcode, copy_cam]))

    s = sup.RecorderSupervisor()
    s._tick_warm()
    assert 200 in s.warm_procs                      # transcode camera kept warm
    assert 201 not in s.warm_procs                  # copy camera not warmed

    # turning live_transcode off stops the keep-warm consumer on the next tick
    transcode.live_transcode = False
    s._tick_warm()
    assert 200 not in s.warm_procs


def test_tick_warm_independent_of_recording_schedule(monkeypatch):
    """Keep-warm uses get_all_enabled directly, so live stays warm even when recording is
    schedule-OFF for the camera (live is viewable regardless of recording)."""
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
    _activity(monkeypatch, active=True)
    cam = _Cam(300, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [cam]))
    s = sup.RecorderSupervisor()
    s._tick_warm()                                  # no _desired_cameras / schedule involved
    assert 300 in s.warm_procs


def test_dead_warm_consumer_respawns(monkeypatch):
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
    _activity(monkeypatch, active=True)
    cam = _Cam(400, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [cam]))
    s = sup.RecorderSupervisor()
    s._tick_warm()
    first = s.warm_procs[400]

    # simulate the consumer dying; next tick should backoff-gate then respawn
    class _Dead(_Popen):
        def poll(self):
            return 1
    first.popen = _Dead()
    first.next_retry = 0          # elapse the backoff gate immediately
    s._tick_warm()
    assert 400 in s.warm_procs and s.warm_procs[400].restart_count >= 1


# ── idle-stop gate (2026-07-03) ───────────────────────────────────────────────
def test_tick_warm_stops_idle_camera(monkeypatch):
    """No viewer within the idle window → the warm consumer is released so go2rtc's
    on-demand transcode stops naturally (CPU freed)."""
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
    _activity(monkeypatch, active=True)
    cam = _Cam(500, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [cam]))
    s = sup.RecorderSupervisor()
    s._tick_warm()
    assert 500 in s.warm_procs

    monkeypatch.setattr(la, 'is_active', lambda name, w=None: False)   # viewers gone
    s._tick_warm()
    assert 500 not in s.warm_procs

    monkeypatch.setattr(la, 'is_active', lambda name, w=None: True)    # viewer returns
    s._tick_warm()
    assert 500 in s.warm_procs


def test_idle_window_zero_keeps_always_warm(monkeypatch):
    """live_transcode_idle_s=0 restores the old always-warm behavior (is_active is True
    with no activity key at all)."""
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
    monkeypatch.setattr(sup.RecorderSupervisor, '_refresh_viewer_activity',
                        lambda self, cam, stream, w: None)
    monkeypatch.setattr(la, 'idle_window', lambda: 0)   # real is_active, window 0
    cam = _Cam(600, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [cam]))
    s = sup.RecorderSupervisor()
    s._tick_warm()
    assert 600 in s.warm_procs


def test_consumer_poll_marks_activity_excluding_warm_self(monkeypatch):
    """go2rtc consumer polling re-marks activity for long watches — but the keep-warm
    consumer itself must not count as a viewer."""
    import server.driver.go2rtc as g2

    marked = []
    monkeypatch.setattr(la, 'mark', lambda name, w=None: marked.append(name))

    class _Drv:
        consumers = 1

        def __init__(self):
            pass

        def stream_status(self, name):
            return {'producers': 1, 'consumers': _Drv.consumers, 'online': True}

    monkeypatch.setattr(g2, 'Go2rtcDriver', _Drv)
    s = sup.RecorderSupervisor()
    cam = _Cam(700, [], transcode=True)
    stream = _Stream(11, 'sub', live=True)

    s.warm_procs[700] = object()          # warm proc running → 1 self-consumer
    _Drv.consumers = 1                    # only the warm proc → no real viewer
    s._refresh_viewer_activity(cam, stream, 300)
    assert marked == []

    _Drv.consumers = 2                    # warm proc + one real viewer
    s._refresh_viewer_activity(cam, stream, 300)
    assert marked == [stream.go2rtc_name]


def test_tick_warm_skips_offloaded_camera(monkeypatch):
    """A camera whose live transcode is published by an encoder node has no local go2rtc
    ffmpeg to keep warm — the push producer runs regardless of consumers."""
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
    _activity(monkeypatch, active=True)
    monkeypatch.setattr(sup.RecorderSupervisor, '_encode_offloaded', staticmethod(lambda cam: True))
    cam = _Cam(800, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [cam]))
    s = sup.RecorderSupervisor()
    s._tick_warm()
    assert 800 not in s.warm_procs
