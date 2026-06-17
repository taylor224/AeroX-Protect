"""axp-recorder entrypoint: `python -m worker.recorder`."""
import logging

import config
from server.model import BaseDB, db


def main():
    logging.basicConfig(
        level=logging.DEBUG if config.PROJECT_ENV == 'development' else logging.INFO,
        format='%(asctime)s [recorder] %(levelname)s %(name)s: %(message)s')
    db.db_init(config.DATABASE_URI, BaseDB)

    from worker.recorder.supervisor import RecorderSupervisor
    RecorderSupervisor().run()


if __name__ == '__main__':
    main()
