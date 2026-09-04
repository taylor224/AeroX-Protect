"""Service supervisor: ordered start with readiness gates, crash restart with
backoff, graceful stop ladder (CTRL_BREAK → timeout → kill → Job Object)."""
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from . import LAUNCHER_VERSION, env, health, mariadb_init, procs
from .logs import ChildLog

logger = logging.getLogger(__name__)

BACKOFF_START = 1.0
BACKOFF_MAX = 60.0
CRASHLOOP_WINDOW_S = 600.0
CRASHLOOP_LIMIT = 10
CRASHLOOP_RETRY_S = 300.0   # crashlooping ≠ dead: retry every 5 min (dependency may heal)
HEALTHY_RESET_S = 120.0
READY_TIMEOUT_S = 90.0


@dataclass
class ServiceSpec:
    name: str
    cmd: Callable[[dict], list[str]]              # cfg -> argv
    env: Callable[[dict], dict] | None = None     # cfg -> child env (None = launcher env)
    cwd: Callable[[], str] | None = None
    ready: Callable[[dict], bool] | None = None   # cfg -> bool
    pre_start: Callable[[dict], None] | None = None
    post_ready: Callable[[dict], None] | None = None
    stop: Callable[[dict, subprocess.Popen], bool] | None = None  # graceful; fallback ctrl_break
    graceful_timeout: float = 15.0
    app_tier: bool = False    # stopped/started by the updater; infra tier stays up
    optional: bool = False    # absence of the binary is not an error (detector)
    exists: Callable[[], bool] | None = None


@dataclass
class ServiceState:
    spec: ServiceSpec
    popen: subprocess.Popen | None = None
    log: ChildLog | None = None
    started_at: float = 0.0
    restart_count: int = 0
    backoff: float = BACKOFF_START
    next_retry: float = 0.0
    recent_deaths: list[float] = field(default_factory=list)
    status: str = 'stopped'   # stopped|starting|running|failed|crashlooping|disabled
    desired: bool = True


def _py() -> str:
    return str(env.PYTHON)


def _app_cmd(*args: str) -> Callable[[dict], list[str]]:
    return lambda cfg: [_py(), '-u', *args]


def build_specs(cfg: dict[str, str]) -> list[ServiceSpec]:
    """The process table. Order = start order; stop order is the reverse."""
    http_port = int(cfg.get('AXP_HTTP_PORT', '3000'))

    def app_env(extra: dict[str, str]):
        return lambda c: env.app_env(c, extra=extra)

    return [
        ServiceSpec(
            name='mariadb',
            cmd=lambda c: [str(env.MARIADBD),
                           '--defaults-file=%s' % (env.CONFIG / 'my.ini'), '--console'],
            pre_start=lambda c: mariadb_init.initialize(c) if mariadb_init.needs_init() else None,
            ready=lambda c: health.tcp_open(env.DB_PORT),
            post_ready=mariadb_init.ensure_database,
            stop=lambda c, p: mariadb_init.shutdown(c),
            graceful_timeout=60,
        ),
        ServiceSpec(
            name='redis',
            # forward slashes: harmless for the native build, required by any
            # msys2-runtime redis (backslash paths get mangled to cwd-relative)
            cmd=lambda c: [str(env.REDIS_SERVER), (env.CONFIG / 'redis.conf').as_posix()],
            ready=lambda c: health.tcp_open(env.REDIS_PORT),
            stop=lambda c, p: subprocess.run(
                [str(env.REDIS_CLI), '-p', str(env.REDIS_PORT), 'shutdown', 'nosave'],
                capture_output=True, timeout=15).returncode == 0,
        ),
        ServiceSpec(
            name='go2rtc',
            cmd=lambda c: [str(env.GO2RTC), '-config', str(env.CONFIG / 'go2rtc.yaml')],
            env=lambda c: {**env.app_env(c), 'TZ': 'UTC'},
            ready=lambda c: health.http_ok('http://127.0.0.1:%d/api' % env.GO2RTC_API_PORT),
        ),
        ServiceSpec(
            name='caddy',
            cmd=lambda c: [str(env.CADDY), 'run',
                           '--config', str(env.CONFIG / 'Caddyfile'), '--adapter', 'caddyfile'],
            env=lambda c: {**env.app_env(c),
                           'AXP_APP_DIR': str(env.CURRENT),
                           'AXP_HTTP_PORT': str(http_port),
                           'AXP_LAUNCHER_PORT': str(env.CONTROL_PORT)},
            ready=lambda c: health.tcp_open(http_port),
        ),
        ServiceSpec(
            name='backend',
            cmd=_app_cmd('-m', 'server.wsgi'),
            env=app_env({'SNOWFLAKE_INSTANCE': '1',
                         'AXP_BIND_HOST': '127.0.0.1',
                         'AXP_BIND_PORT': str(env.BACKEND_PORT)}),
            cwd=lambda: str(env.CURRENT / 'app'),
            ready=lambda c: (health.healthz(env.BACKEND_PORT) or {}).get('db') is True,
            graceful_timeout=20,
            app_tier=True,
        ),
        # celery refuses embedded beat (-B) on Windows → beat runs as its own service
        ServiceSpec(
            name='worker',
            cmd=_app_cmd('-m', 'celery', '-A', 'server.task.celery', 'worker',
                         '--pool=threads', '-c', '8', '-n', 'worker@axp', '-l', 'info'),
            env=app_env({'SNOWFLAKE_INSTANCE': '2'}),
            cwd=lambda: str(env.CURRENT / 'app'),
            graceful_timeout=30,
            app_tier=True,
        ),
        ServiceSpec(
            name='beat',
            cmd=_app_cmd('-m', 'celery', '-A', 'server.task.celery', 'beat',
                         '-l', 'info', '-s', str(env.DATA / 'celerybeat-schedule')),
            env=app_env({'SNOWFLAKE_INSTANCE': '7'}),
            cwd=lambda: str(env.CURRENT / 'app'),
            graceful_timeout=15,
            app_tier=True,
        ),
        ServiceSpec(
            name='subs',
            cmd=_app_cmd('-m', 'celery', '-A', 'server.task.celery', 'worker', '-Q', 'subs',
                         '--pool=threads', '-c', '50', '-n', 'subs@axp', '-l', 'info'),
            env=app_env({'SNOWFLAKE_INSTANCE': '4'}),
            cwd=lambda: str(env.CURRENT / 'app'),
            graceful_timeout=30,
            app_tier=True,
        ),
        ServiceSpec(
            name='recorder',
            cmd=_app_cmd('-m', 'worker.recorder'),
            env=app_env({'SNOWFLAKE_INSTANCE': '3'}),
            cwd=lambda: str(env.CURRENT / 'app'),
            graceful_timeout=20,
            app_tier=True,
        ),
        ServiceSpec(
            name='encoder',
            cmd=_app_cmd('-m', 'uvicorn', 'worker.encoder.app:app',
                         '--host', '127.0.0.1', '--port', str(env.ENCODER_PORT)),
            env=app_env({'SNOWFLAKE_INSTANCE': '5',
                         'SERVER_API_URL': 'http://127.0.0.1:%d/api/v1' % env.BACKEND_PORT,
                         'ADVERTISE_URL': 'http://127.0.0.1:%d' % env.ENCODER_PORT,
                         'ENCODER_BIND': '127.0.0.1:%d' % env.ENCODER_PORT,
                         'NODE_NAME': cfg.get('ENCODER_NODE_NAME', 'encoder-local'),
                         'HWACCEL': cfg.get('ENCODER_HWACCEL', 'none'),
                         'MAX_SESSIONS': cfg.get('ENCODER_MAX_SESSIONS', '4')}),
            cwd=lambda: str(env.CURRENT / 'app'),
            ready=lambda c: health.http_ok('http://127.0.0.1:%d/healthz' % env.ENCODER_PORT),
            app_tier=True,
        ),
        ServiceSpec(
            name='detector',
            cmd=_app_cmd('-m', 'uvicorn', 'worker.detector.app:app',
                         '--host', '127.0.0.1', '--port', str(env.DETECTOR_PORT)),
            env=app_env({'SNOWFLAKE_INSTANCE': '6',
                         'SERVER_API_URL': 'http://127.0.0.1:%d/api/v1' % env.BACKEND_PORT,
                         'DETECTOR_BIND': '127.0.0.1:%d' % env.DETECTOR_PORT,
                         'GPU_ENABLED': cfg.get('GPU_ENABLED', 'false'),
                         'PYTHONPATH': '%s;%s;%s;%s' % (env.EXTRAS_AI,
                                                        env.CURRENT / 'site-packages-ai',
                                                        env.CURRENT / 'site-packages',
                                                        env.CURRENT / 'app')}),
            cwd=lambda: str(env.CURRENT / 'app'),
            ready=lambda c: health.http_ok('http://127.0.0.1:%d/healthz' % env.DETECTOR_PORT),
            app_tier=True,
            optional=True,
            # inference deps present (legacy in-version dir, or ultralytics in the
            # persistent extras dir — CLIP-only installs must NOT start the detector)
            exists=lambda: ((env.CURRENT / 'site-packages-ai').exists()
                            or (env.EXTRAS_AI / 'ultralytics').exists()),
        ),
    ]


class Supervisor:
    def __init__(self, cfg: dict[str, str]):
        self.cfg = cfg
        self.job = procs.JobObject()
        self.states: dict[str, ServiceState] = {}
        self.lock = threading.RLock()
        self._stop_event = threading.Event()
        for spec in build_specs(cfg):
            self.states[spec.name] = ServiceState(spec=spec, log=ChildLog(spec.name))

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start_infra(self):
        """mariadb / redis / go2rtc / caddy — the tier that stays up through updates."""
        for st in self.states.values():
            if st.spec.app_tier or self._stop_event.is_set():
                continue
            self._start_and_wait(st)

    def _start_and_wait(self, st: ServiceState):
        self._spawn(st)
        if st.popen is None:
            return
        spec = st.spec
        if spec.ready is not None:
            deadline = time.monotonic() + READY_TIMEOUT_S
            while time.monotonic() < deadline and not self._stop_event.is_set():
                if st.popen.poll() is not None:
                    break
                if spec.ready(self.cfg):
                    break
                time.sleep(1.0)
            else:
                logger.error('%s: not ready within %ds', spec.name, READY_TIMEOUT_S)
                st.status = 'failed'
                return
            if st.popen.poll() is not None:
                logger.error('%s: exited during startup (rc=%s)', spec.name, st.popen.returncode)
                st.status = 'failed'
                return
        if spec.post_ready is not None:
            try:
                spec.post_ready(self.cfg)
            except Exception:
                logger.exception('%s: post_ready failed', spec.name)
                st.status = 'failed'
                return
        st.status = 'running'
        logger.info('%s: running (pid=%s)', spec.name, st.popen.pid)

    def _spawn(self, st: ServiceState):
        spec = st.spec
        st.status = 'starting'
        if spec.pre_start is not None:
            try:
                spec.pre_start(self.cfg)
            except Exception:
                logger.exception('%s: pre_start failed', spec.name)
                st.status = 'failed'
                return
        child_env = spec.env(self.cfg) if spec.env else env.app_env(self.cfg)
        try:
            st.popen = subprocess.Popen(
                spec.cmd(self.cfg),
                cwd=spec.cwd() if spec.cwd else None,
                env=child_env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=procs.popen_flags())
        except OSError as e:
            logger.error('%s: spawn failed: %s', spec.name, e)
            st.popen = None
            st.status = 'failed'
            return
        self.job.assign(st.popen)
        st.log.pump(st.popen.stdout)
        st.started_at = time.monotonic()

    def stop_service(self, name: str):
        with self.lock:
            st = self.states[name]
            st.desired = False
            self._stop_child(st)

    def _stop_child(self, st: ServiceState):
        spec, popen = st.spec, st.popen
        st.popen = None
        st.status = 'stopped'
        if popen is None or popen.poll() is not None:
            return
        try:
            done = False
            if spec.stop is not None:
                try:
                    done = bool(spec.stop(self.cfg, popen))
                except Exception:
                    done = False
            if not done:
                procs.send_ctrl_break(popen)
            try:
                popen.wait(timeout=spec.graceful_timeout)
                return
            except subprocess.TimeoutExpired:
                pass
            popen.kill()
            popen.wait(timeout=10)
        except OSError:
            pass

    def stop_all(self, app_only: bool = False):
        for name in reversed(list(self.states)):
            st = self.states[name]
            if app_only and not st.spec.app_tier:
                continue
            st.desired = False
            self._stop_child(st)

    def start_app_tier(self):
        for st in self.states.values():
            if not st.spec.app_tier:
                continue
            if st.spec.optional and st.spec.exists and not st.spec.exists():
                st.status = 'disabled'
                st.desired = False
                continue
            st.desired = True
            st.restart_count = 0
            st.backoff = BACKOFF_START
            st.recent_deaths.clear()
            self._start_and_wait(st)

    def restart_service(self, name: str) -> bool:
        with self.lock:
            st = self.states.get(name)
            if st is None:
                return False
            self._stop_child(st)
            st.desired = True
            st.restart_count = 0
            st.backoff = BACKOFF_START
            st.recent_deaths.clear()
            self._start_and_wait(st)
            return st.status == 'running'

    # ── monitor loop ─────────────────────────────────────────────────────────
    def monitor_forever(self):
        while not self._stop_event.is_set():
            time.sleep(2.0)
            with self.lock:
                for st in self.states.values():
                    self._monitor_one(st)

    def _monitor_one(self, st: ServiceState):
        if not st.desired or st.status == 'disabled':
            return
        if st.status == 'crashlooping':
            # Slow-retry mode: the cause (e.g. a dependency that was down) may have
            # healed — try again every CRASHLOOP_RETRY_S with a fresh death window.
            if st.popen is None and time.monotonic() >= st.next_retry:
                st.recent_deaths.clear()
                self._start_and_wait(st)
                if st.status != 'running':
                    st.status = 'crashlooping'
                    st.next_retry = time.monotonic() + CRASHLOOP_RETRY_S
            return
        popen = st.popen
        if popen is None:
            if st.status == 'failed' and time.monotonic() >= st.next_retry:
                self._register_death(st)
                if st.status != 'crashlooping':
                    self._start_and_wait(st)
            return
        if popen.poll() is None:
            if st.backoff != BACKOFF_START and time.monotonic() - st.started_at > HEALTHY_RESET_S:
                st.backoff = BACKOFF_START
            return
        logger.warning('%s: died rc=%s', st.spec.name, popen.returncode)
        st.popen = None
        self._register_death(st)
        if st.status == 'crashlooping':
            return
        st.status = 'failed'
        st.next_retry = time.monotonic() + st.backoff
        st.backoff = min(st.backoff * 2, BACKOFF_MAX)

    def _register_death(self, st: ServiceState):
        now = time.monotonic()
        st.restart_count += 1
        st.recent_deaths = [t for t in st.recent_deaths if now - t < CRASHLOOP_WINDOW_S]
        st.recent_deaths.append(now)
        if len(st.recent_deaths) > CRASHLOOP_LIMIT:
            logger.error('%s: crashlooping (%d deaths in %ds) — backing off to %ds retries',
                         st.spec.name, len(st.recent_deaths), CRASHLOOP_WINDOW_S,
                         CRASHLOOP_RETRY_S)
            st.status = 'crashlooping'
            st.next_retry = time.monotonic() + CRASHLOOP_RETRY_S

    def shutdown(self):
        self._stop_event.set()
        with self.lock:
            self.stop_all()

    # ── introspection ────────────────────────────────────────────────────────
    def status(self) -> dict:
        with self.lock:
            return {
                'launcher_version': LAUNCHER_VERSION,
                'current_version': env.current_version(),
                'services': {
                    name: {
                        'status': st.status,
                        'pid': st.popen.pid if st.popen and st.popen.poll() is None else None,
                        'uptime_s': int(time.monotonic() - st.started_at)
                                     if st.popen and st.popen.poll() is None else 0,
                        'restarts': st.restart_count,
                    }
                    for name, st in self.states.items()
                },
            }

    def logs(self, name: str, tail: int = 200) -> list[str] | None:
        st = self.states.get(name)
        return st.log.tail(tail) if st else None
