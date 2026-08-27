"""Cross-platform ffmpeg child-process helpers (recorder + encoder node).

ffmpeg's graceful-stop contract differs by OS: on POSIX, SIGINT makes ffmpeg
flush and finalize the current output (same as pressing 'q'), but Windows has no
SIGINT for child processes — Popen.send_signal(SIGINT) raises ValueError there,
which used to leak orphaned ffmpeg.exe processes. The one portable channel is
ffmpeg's own stdin 'q' command, so spawn() always opens a stdin pipe and
graceful_stop() tries 'q' first, then SIGINT (POSIX only), then terminate/kill.

Lives under worker/ (not server/util/) because the encoder node image ships only
the worker/ package.
"""
import os
import subprocess

__all__ = ['spawn', 'graceful_stop']


def spawn(cmd: list[str], **kwargs) -> subprocess.Popen:
    """subprocess.Popen with a stdin pipe (graceful 'q' channel) and no console
    window on Windows. Raises OSError like Popen does."""
    kwargs.setdefault('stdin', subprocess.PIPE)
    if os.name == 'nt':
        kwargs['creationflags'] = (kwargs.get('creationflags', 0)
                                   | getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return subprocess.Popen(cmd, **kwargs)


def _wait(popen: subprocess.Popen, timeout: float) -> bool:
    try:
        popen.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return True


def graceful_stop(popen: subprocess.Popen | None, timeout: float = 5.0):
    """Stop an ffmpeg process, letting it flush its current output. Never raises.

    Ladder: stdin 'q' → SIGINT (POSIX, for procs spawned without a stdin pipe)
    → terminate() → kill().
    """
    try:
        if popen is None or popen.poll() is not None:
            return
        if popen.stdin is not None:
            try:
                popen.stdin.write(b'q')
                popen.stdin.flush()
                popen.stdin.close()
            except (OSError, ValueError):
                pass
            if _wait(popen, timeout):
                return
        if os.name != 'nt':
            import signal
            try:
                popen.send_signal(signal.SIGINT)
            except OSError:
                pass
            if _wait(popen, timeout if popen.stdin is None else 2.0):
                return
        try:
            popen.terminate()
        except OSError:
            pass
        if _wait(popen, 2.0):
            return
        try:
            popen.kill()
        except OSError:
            pass
        _wait(popen, 2.0)
    except Exception:
        pass
