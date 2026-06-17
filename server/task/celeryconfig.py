from celery.schedules import crontab

import config

broker_url = config.REDIS_URI
result_backend = config.REDIS_URI

broker_transport_options = {
    'max_retries': 1,
    'interval_start': 0,
    'interval_step': 0.2,
    'interval_max': 0.5,
    'visibility_timeout': 86400,
}

beat_schedule = {
    'cleanup_expired_tokens': {
        'task': 'server.task.list.maintenance.cleanup_expired_tokens',
        'schedule': crontab(hour='3', minute='0'),  # daily 03:00 UTC
    },
    'camera_health_check': {
        'task': 'server.task.list.camera_health.camera_health_check',
        'schedule': 30.0,   # every 30s — frame-grab health + caches the tile thumbnail in one pass
    },
    # P2
    'run_retention': {
        'task': 'server.task.list.retention.run_retention',
        'schedule': 60.0,   # every minute
    },
    'scan_disks': {
        'task': 'server.task.list.disk_scan.scan_disks',
        'schedule': 300.0,  # every 5 min
    },
    'segment_sweep': {
        'task': 'server.task.list.segment_sweep.sweep',
        'schedule': 120.0,  # every 2 min
    },
    'expire_export_jobs': {
        'task': 'server.task.list.transcode.expire_export_jobs',
        'schedule': crontab(minute='17'),
    },
    'backfill_thumbnails': {
        'task': 'server.task.list.thumbnail.backfill_thumbnails',
        'schedule': 600.0,  # every 10 min
    },
    'edge_auto_import_scan': {
        'task': 'server.task.list.edge_import.edge_auto_import_scan',
        'schedule': 1800.0,  # every 30 min — gap-fill from camera SD for auto-import cameras
    },
    # P3
    'supervise_subscriptions': {
        'task': 'server.task.list.event_subscription.supervise_subscriptions',
        'schedule': 30.0,
    },
    'active_event_sweeper': {
        'task': 'server.task.list.event_maintenance.active_event_sweeper',
        'schedule': 30.0,
    },
    'cleanup_events': {
        'task': 'server.task.list.event_maintenance.cleanup_events',
        'schedule': crontab(hour='4', minute='0'),
    },
    # P4
    'supervise_nodes': {
        'task': 'server.task.list.ai_supervise.supervise_nodes',
        'schedule': 10.0,   # node health sweep + rebalance
    },
    'backfill_segments': {
        'task': 'server.task.list.detection_linker.backfill_segments',
        'schedule': 30.0,
    },
    'purge_detections': {
        'task': 'server.task.list.detection_retention.purge_detections',
        'schedule': crontab(hour='4', minute='30'),
    },
    # P5
    'outbox_consumer': {
        'task': 'server.task.list.outbox_consumer.consume',
        'schedule': 5.0,    # drives rules + notifications from the P3 event outbox
    },
    'schedule_trigger': {
        'task': 'server.task.list.schedule_trigger.tick',
        'schedule': crontab(minute='*'),   # cron-rule evaluation, minute resolution
    },
    'pairing_code_cleanup': {
        'task': 'server.task.list.pairing_code_cleanup.cleanup',
        'schedule': 300.0,
    },
    'target_healthcheck': {
        'task': 'server.task.list.p5_retention.healthcheck_targets',
        'schedule': 300.0,
    },
    'p5_retention': {
        'task': 'server.task.list.p5_retention.run',
        'schedule': crontab(hour='3', minute='30'),
    },
    # P8 — refresh federated members' camera cache + status (flag-gated no-op when off)
    'federation_sync': {
        'task': 'server.task.list.federation_sync.sync',
        'schedule': 120.0,
    },
    # P2 — auto-stop fixed-duration manual recordings
    'recording_autoclose': {
        'task': 'server.task.list.recording_autoclose.run',
        'schedule': 30.0,
    },
}

imports = ('server.task.list',)
