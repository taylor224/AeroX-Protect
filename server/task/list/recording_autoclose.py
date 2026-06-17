"""Auto-stop fixed-duration manual recordings (PLAN P2 manual-record-for-N-minutes).
A manual recording started with a duration carries `planned_end_ts`; this closes it once
that time passes (the recorder then drops it from the forced set on the next reconcile).
"""
import logging

from server.task.celery import app, celery_use_db

logger = logging.getLogger(__name__)


@app.task(name='server.task.list.recording_autoclose.run')
@celery_use_db()
def run():
    from server.controller.recording import RecordingController
    closed = RecordingController.autoclose_due()
    if closed:
        logger.info('auto-closed %d expired manual recording(s)', closed)
    return {'closed': closed}
