"""axp-recorder entrypoint: `python -m worker.recorder`."""
import logging
import os
import signal
from datetime import datetime, timezone

import config
from server.model import BaseDB, db

logger = logging.getLogger(__name__)


def _install_shutdown_signals():
    """Route SIGTERM (docker stop) and SIGBREAK (Windows launcher CTRL_BREAK) into
    KeyboardInterrupt so the supervisor's finally-block runs graceful_stop on every
    ffmpeg child — otherwise the final segment of each camera is lost."""
    def _raise(_signum, _frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _raise)
    except (OSError, ValueError):
        pass
    if os.name == 'nt':
        try:
            signal.signal(signal.SIGBREAK, _raise)
        except (OSError, ValueError):
            pass


def _tz_tripwire():
    """Segment filenames come from ffmpeg `-strftime` (process-local time) and
    segment_indexer parses them as naive UTC — a non-UTC process TZ skews every
    indexed start_ts by the offset. The launcher/compose must set TZ=UTC."""
    skew = abs((datetime.now() - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds())
    if skew > 60:
        logger.critical(
            'process timezone is not UTC (offset %.0fs) — segment timestamps WILL be wrong; '
            'set TZ=UTC in the recorder environment', skew)


def main():
    logging.basicConfig(
        level=logging.DEBUG if config.PROJECT_ENV == 'development' else logging.INFO,
        format='%(asctime)s [recorder] %(levelname)s %(name)s: %(message)s')
    _install_shutdown_signals()
    _tz_tripwire()
    db.db_init(config.DATABASE_URI, BaseDB)

    from worker.recorder.supervisor import RecorderSupervisor
    try:
        RecorderSupervisor().run()
    except KeyboardInterrupt:
        logger.info('recorder shutdown complete')


if __name__ == '__main__':
    main()
