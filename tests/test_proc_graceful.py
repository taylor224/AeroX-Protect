"""graceful_stop ladder: stdin 'q' → SIGINT (POSIX) → terminate → kill; never raises."""
import io
import subprocess

from worker.procutil import graceful_stop, spawn


class FakePopen:
    def __init__(self, accept_q=True, accept_terminate=True, with_stdin=True):
        self.stdin = io.BytesIO() if with_stdin else None
        self._alive = True
        self._accept_q = accept_q
        self._accept_terminate = accept_terminate
        self.calls = []

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        self.calls.append(('wait', timeout))
        if self._alive:
            # 'q' takes effect at the first wait after stdin close
            if self._accept_q and self.stdin is not None and self.stdin.closed:
                self._alive = False
                return 0
            raise subprocess.TimeoutExpired(cmd='ffmpeg', timeout=timeout or 0)
        return 0

    def send_signal(self, sig):
        self.calls.append(('signal', sig))

    def terminate(self):
        self.calls.append(('terminate',))
        if self._accept_terminate:
            self._alive = False

    def kill(self):
        self.calls.append(('kill',))
        self._alive = False


def test_quit_via_stdin():
    p = FakePopen(accept_q=True)
    graceful_stop(p, timeout=1)
    assert p.poll() == 0
    assert ('terminate',) not in p.calls and ('kill',) not in p.calls


def test_falls_back_to_terminate():
    p = FakePopen(accept_q=False)
    graceful_stop(p, timeout=0.01)
    assert p.poll() == 0
    assert ('terminate',) in p.calls


def test_falls_back_to_kill():
    p = FakePopen(accept_q=False, accept_terminate=False)
    graceful_stop(p, timeout=0.01)
    assert p.poll() == 0
    assert ('kill',) in p.calls


def test_no_stdin_pipe_still_stops():
    p = FakePopen(accept_q=False, with_stdin=False)
    graceful_stop(p, timeout=0.01)
    assert p.poll() == 0


def test_none_and_dead_are_noops():
    graceful_stop(None)
    p = FakePopen()
    p._alive = False
    graceful_stop(p)
    assert p.calls == []


def test_spawn_opens_stdin_pipe():
    p = spawn(['cat'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert p.stdin is not None
    finally:
        p.stdin.close()
        p.terminate()
        p.wait(timeout=5)


def test_spawn_real_process_graceful_stop():
    p = spawn(['cat'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    graceful_stop(p, timeout=5)   # cat exits on stdin EOF — the 'q' path
    assert p.poll() is not None
