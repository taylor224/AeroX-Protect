"""Launcher entrypoint (run by WinSW as a Windows service):

    runtime\\python\\python.exe -u -m axp_launcher

Boot: console + Job Object → control API → infra tier (mariadb/redis/go2rtc/caddy)
→ one-shot db-upgrade/seed/seed-admin with the current payload → app tier →
monitor loop. WinSW stops us via `python -m axp_launcher.ctl stop` (control API
/v1/shutdown), which unwinds everything in reverse; the Job Object guarantees
nothing survives even a hard launcher kill.
"""
import logging
import logging.handlers
import sys

from . import LAUNCHER_VERSION, env, procs
from .control import ControlServer
from .supervisor import Supervisor
from .update import Updater


def _setup_logging():
    env.LOGS.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        env.LOGS / 'launcher.log', maxBytes=16 * 1024 * 1024, backupCount=5,
        encoding='utf-8')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [launcher] %(levelname)s %(name)s: %(message)s',
        handlers=[handler, logging.StreamHandler(sys.stderr)])


def _dbinit(cfg, sup):
    """One-shot schema/seed pass with the current payload; failures are logged but
    do not block boot (the backend will fail its own healthcheck and surface it)."""
    from .update import Updater as _U   # reuse _run_app_cmd
    updater_like = _U(cfg, sup)
    for args in (['-m', 'server.command', 'db-upgrade'],
                 ['-m', 'server.command', 'seed'],
                 ['-m', 'server.command', 'seed-admin']):
        try:
            updater_like._run_app_cmd(env.CURRENT, args)
        except Exception:
            logging.getLogger(__name__).exception('dbinit step %s failed', args)


def main():
    _setup_logging()
    log = logging.getLogger(__name__)
    log.info('axp launcher v%s starting (home=%s, app=v%s)',
             LAUNCHER_VERSION, env.AXP_HOME, env.current_version())

    cfg = env.load_env()
    if not cfg.get('SECRET_KEY'):
        log.error('config\\axp.env missing or has no SECRET_KEY — aborting')
        sys.exit(2)

    procs.alloc_console()
    sup = Supervisor(cfg)
    updater = Updater(cfg, sup)
    control = ControlServer(cfg, sup, updater)
    control.start()

    try:
        sup.start_infra()
        _dbinit(cfg, sup)
        sup.start_app_tier()
        log.info('all services started')
        # monitor until /v1/shutdown
        import threading
        mon = threading.Thread(target=sup.monitor_forever, name='monitor', daemon=True)
        mon.start()
        control.shutdown_event.wait()
        log.info('shutdown requested')
    finally:
        sup.shutdown()
        control.stop()
        log.info('launcher exited cleanly')


if __name__ == '__main__':
    main()
