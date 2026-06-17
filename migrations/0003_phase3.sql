-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 3 (events + smart/scheduled recording)
--
-- Runs after 0002. All-new tables (no drops). Mirrors server/model/{event,
-- event_policy,schedule,timelapse_job,event_outbox,camera_subscription}.py.
-- UTC DATETIME(3); Snowflake BIGINT UNSIGNED. recordings.reason already supports
-- event/schedule (P2). New permission keys (events/policies/schedules/timelapse)
-- were seeded in the P0 catalog (0000_init.sql).
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `events` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `type` VARCHAR(32) NOT NULL,
  `subtype` VARCHAR(48) NULL,
  `state` TINYINT NOT NULL DEFAULT 2,
  `start_ts` DATETIME(3) NOT NULL,
  `end_ts` DATETIME(3) NULL,
  `duration_ms` INT NULL,
  `score` SMALLINT NULL,
  `source` VARCHAR(16) NOT NULL,
  `channel` SMALLINT NULL,
  `region` JSON NULL,
  `snapshot_path` VARCHAR(512) NULL,
  `recording_id` BIGINT UNSIGNED NULL,
  `policy_action` VARCHAR(16) NULL,
  `dedup_key` VARCHAR(80) NOT NULL,
  `vendor_event_id` VARCHAR(128) NULL,
  `raw` JSON NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_cam_ts` (`camera_id`, `start_ts`),
  KEY `idx_type_ts` (`type`, `start_ts`),
  KEY `idx_dedup_state` (`dedup_key`, `state`),
  KEY `idx_recording` (`recording_id`),
  KEY `idx_active` (`state`, `start_ts`),
  KEY `idx_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `event_policies` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NULL,
  `event_type` VARCHAR(32) NOT NULL,
  `subtype` VARCHAR(48) NULL,
  `action` VARCHAR(16) NOT NULL,
  `pre_buffer_s` SMALLINT NOT NULL DEFAULT 5,
  `post_buffer_s` SMALLINT NOT NULL DEFAULT 10,
  `cooldown_s` SMALLINT NOT NULL DEFAULT 10,
  `min_score` SMALLINT NULL,
  `retention_class` VARCHAR(24) NULL,
  `notify` TINYINT(1) NOT NULL DEFAULT 1,
  `active_schedule_id` BIGINT UNSIGNED NULL,
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_cam_type` (`camera_id`, `event_type`),
  KEY `idx_policy_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `schedules` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `name` VARCHAR(80) NULL,
  `day_of_week` TINYINT NOT NULL,
  `start_min` SMALLINT NOT NULL,
  `end_min` SMALLINT NOT NULL,
  `mode` VARCHAR(16) NOT NULL,
  `priority` SMALLINT NOT NULL DEFAULT 0,
  `timezone` VARCHAR(40) NOT NULL DEFAULT 'Asia/Seoul',
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `group_uuid` VARCHAR(40) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_cam_dow` (`camera_id`, `day_of_week`),
  KEY `idx_group` (`group_uuid`),
  KEY `idx_sched_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `timelapse_jobs` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `range_start_ts` DATETIME(3) NOT NULL,
  `range_end_ts` DATETIME(3) NOT NULL,
  `source` VARCHAR(16) NOT NULL DEFAULT 'range',
  `event_ids` JSON NULL,
  `speed_factor` INT NOT NULL DEFAULT 60,
  `params` JSON NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'queued',
  `progress` SMALLINT NOT NULL DEFAULT 0,
  `celery_task_id` VARCHAR(64) NULL,
  `output_disk_id` BIGINT UNSIGNED NULL,
  `output_path` VARCHAR(512) NULL,
  `output_size` BIGINT NULL,
  `error` VARCHAR(512) NULL,
  `expires_at` DATETIME(3) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tl_cam` (`camera_id`),
  KEY `idx_tl_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `event_outbox` (
  `id` BIGINT UNSIGNED NOT NULL,
  `event_id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `event_type` VARCHAR(32) NOT NULL,
  `payload` JSON NOT NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'pending',
  `attempts` SMALLINT NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `consumed_at` DATETIME(3) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_outbox_event` (`event_id`),
  KEY `idx_outbox_cam` (`camera_id`),
  KEY `idx_outbox_status` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `camera_subscriptions` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `protocol` VARCHAR(16) NOT NULL,
  `state` VARCHAR(16) NOT NULL,
  `last_event_ts` DATETIME(3) NULL,
  `renew_at_ts` DATETIME(3) NULL,
  `fail_count` SMALLINT NOT NULL DEFAULT 0,
  `last_error` VARCHAR(512) NULL,
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sub_camera` (`camera_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
