import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.disk_scan.scan_disks')
@celery_use_db()
def scan_disks():
    """Every 5 min: refresh free/total bytes for registered disks (watchdog/balance cache)."""
    from server.service.disk_scanner import refresh_all_usage
    count = refresh_all_usage()
    logger.info('disk_scan: refreshed %d disks', count)
    return count
