"""Child output capture: pipe-pump thread → rotating file + in-memory ring buffer."""
import collections
import logging
import logging.handlers
import threading

from . import env


class ChildLog:
    """One per supervised service. The child's stdout+stderr (merged) is pumped
    line-by-line into data\\logs\\<name>.log (32MB × 5) and a 500-line ring served
    by the control API's /v1/logs/<name>."""

    def __init__(self, name: str, max_bytes: int = 32 * 1024 * 1024, backups: int = 5):
        self.name = name
        self.ring: collections.deque[str] = collections.deque(maxlen=500)
        env.LOGS.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger('axp.child.%s' % name)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            handler = logging.handlers.RotatingFileHandler(
                env.LOGS / ('%s.log' % name), maxBytes=max_bytes,
                backupCount=backups, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            self._logger.addHandler(handler)

    def write(self, line: str):
        line = line.rstrip('\r\n')
        if not line:
            return
        self.ring.append(line)
        self._logger.info('%s', line)

    def pump(self, pipe) -> threading.Thread:
        """Detached reader thread; exits when the child closes its end."""
        def _run():
            try:
                for raw in iter(pipe.readline, b''):
                    self.write(raw.decode('utf-8', 'replace'))
            except (OSError, ValueError):
                pass
            finally:
                try:
                    pipe.close()
                except OSError:
                    pass
        t = threading.Thread(target=_run, name='log-%s' % self.name, daemon=True)
        t.start()
        return t

    def tail(self, n: int = 200) -> list[str]:
        return list(self.ring)[-n:]
