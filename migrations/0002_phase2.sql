-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 2 (recording + storage engine)
--
-- Runs after 0001. The P0 disks/storage_policies skeletons are empty, so we drop +
-- recreate them at full P2 schema. Mirrors server/model/{disk,storage_policy,segment,
-- recording,export_job,recorder_health}.py. UTC DATETIME(3); Snowflake BIGINT UNSIGNED.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

DROP TABLE IF EXISTS `disks`;
DROP TABLE IF EXISTS `storage_policies`;

CREATE TABLE `disks` (
  `id` BIGINT UNSIGNED NOT NULL,
  `name` VARCHAR(100) NOT NULL,
  `mount_path` VARCHAR(500) NOT NULL,
  `device` VARCHAR(200) NULL,
  `fs_uuid` VARCHAR(100) NULL,
  `role` VARCHAR(16) NOT NULL DEFAULT 'record',
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `reserved_free_bytes` BIGINT NOT NULL DEFAULT 0,
  `total_bytes` BIGINT NOT NULL DEFAULT 0,
  `free_bytes` BIGINT NOT NULL DEFAULT 0,
  `weight` INT NOT NULL DEFAULT 100,
  `status` VARCHAR(16) NOT NULL DEFAULT 'online',
  `last_seen_at` DATETIME(3) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_disks_mount` (`mount_path`),
  UNIQUE KEY `uq_disks_fs_uuid` (`fs_uuid`),
  KEY `idx_disks_role_enabled` (`role`, `enabled`, `deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `storage_policies` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NULL,
  `segment_seconds` INT NOT NULL DEFAULT 10,
  `container` VARCHAR(8) NOT NULL DEFAULT 'fmp4',
  `record_mode` VARCHAR(12) NOT NULL DEFAULT 'off',
  `balance_strategy` VARCHAR(16) NOT NULL DEFAULT 'least_used',
  `pinned_disk_id` BIGINT UNSIGNED NULL,
  `retention_days` INT NULL,
  `retention_max_bytes` BIGINT NULL,
  `over_capacity_policy` VARCHAR(16) NOT NULL DEFAULT 'delete_oldest',
  `cache_buffer_seconds` INT NOT NULL DEFAULT 60,
  `event_retention_days` INT NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_policy_camera` (`camera_id`, `deleted_at`),
  KEY `idx_policy_mode` (`record_mode`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `segments` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `disk_id` BIGINT UNSIGNED NOT NULL,
  `rel_path` VARCHAR(500) NOT NULL,
  `start_ts` DATETIME(3) NOT NULL,
  `end_ts` DATETIME(3) NOT NULL,
  `duration_ms` INT NOT NULL,
  `size_bytes` BIGINT NOT NULL,
  `container` VARCHAR(8) NOT NULL DEFAULT 'fmp4',
  `video_codec` VARCHAR(20) NULL,
  `has_audio` TINYINT(1) NOT NULL DEFAULT 0,
  `width` SMALLINT NULL,
  `height` SMALLINT NULL,
  `first_keyframe_ms` INT NOT NULL DEFAULT 0,
  `reason` VARCHAR(12) NOT NULL DEFAULT 'continuous',
  `storage_tier` VARCHAR(8) NOT NULL DEFAULT 'cache',
  `corrupt` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_seg_cam_start` (`camera_id`, `start_ts`, `end_ts`),
  KEY `idx_seg_disk_start` (`disk_id`, `start_ts`),
  KEY `idx_seg_tier_start` (`storage_tier`, `start_ts`),
  KEY `idx_seg_reason` (`camera_id`, `reason`, `start_ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- large scale: ALTER ... PARTITION BY RANGE (TO_DAYS(start_ts)) (monthly)

CREATE TABLE `recordings` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `reason` VARCHAR(12) NOT NULL,
  `retention_class` VARCHAR(12) NOT NULL DEFAULT 'default',
  `start_ts` DATETIME(3) NOT NULL,
  `end_ts` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `note` VARCHAR(500) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  PRIMARY KEY (`id`),
  KEY `idx_rec_cam_start` (`camera_id`, `start_ts`),
  KEY `idx_rec_protect` (`camera_id`, `retention_class`, `start_ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `export_jobs` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `requested_by_id` BIGINT UNSIGNED NOT NULL,
  `start_ts` DATETIME(3) NOT NULL,
  `end_ts` DATETIME(3) NOT NULL,
  `mode` VARCHAR(12) NOT NULL DEFAULT 'copy',
  `container` VARCHAR(8) NOT NULL DEFAULT 'mp4',
  `transcode_preset` VARCHAR(50) NULL,
  `status` VARCHAR(12) NOT NULL DEFAULT 'queued',
  `progress` INT NOT NULL DEFAULT 0,
  `celery_task_id` VARCHAR(100) NULL,
  `output_disk_id` BIGINT UNSIGNED NULL,
  `output_rel_path` VARCHAR(500) NULL,
  `output_size_bytes` BIGINT NULL,
  `download_token` VARCHAR(100) NOT NULL,
  `error_message` VARCHAR(1000) NULL,
  `expires_at` DATETIME(3) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_export_token` (`download_token`),
  KEY `idx_export_status` (`status`, `created_at`),
  KEY `idx_export_requester` (`requested_by_id`, `created_at`),
  KEY `idx_export_expires` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `recorder_health` (
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `state` VARCHAR(16) NOT NULL DEFAULT 'stopped',
  `pid` INT NULL,
  `last_segment_at` DATETIME(3) NULL,
  `restart_count` INT NOT NULL DEFAULT 0,
  `last_error` VARCHAR(1000) NULL,
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`camera_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
