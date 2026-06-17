"""Keep-warm consumers for live transcodes (2026-06-14).

go2rtc runs the H.265→H.264 live transcode on-demand and stops it when the last viewer
leaves, so every viewer cold-starts ffmpeg and waits for a keyframe (visible breakup). The
recorder supervisor holds one throwaway consumer open per live_transcode camera to keep the
transcode running. These exercise the deterministic logic (stream selection + tick
convergence) with subprocess.Popen mocked — real ffmpeg/go2rtc are unavailable here.
"""
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
    cam = _Cam(300, [_Stream(10, 'main', full=True), _Stream(11, 'sub', live=True)], transcode=True)
    monkeypatch.setattr(sup.Camera, 'get_all_enabled', staticmethod(lambda: [cam]))
    s = sup.RecorderSupervisor()
    s._tick_warm()                                  # no _desired_cameras / schedule involved
    assert 300 in s.warm_procs


def test_dead_warm_consumer_respawns(monkeypatch):
    monkeypatch.setattr(sup.subprocess, 'Popen', _Popen)
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
