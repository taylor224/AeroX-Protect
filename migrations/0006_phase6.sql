-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 6 (advanced features — Wave 1 increment 1)
--
-- Runs after 0005. All-new tables (no drops). Mirrors server/model/{feature_flag,
-- bookmark}.py. UTC DATETIME(3); Snowflake BIGINT UNSIGNED. Permission keys
-- (feature_flags:manage, bookmarks:read/update) seeded via the P0 catalog (server/
-- model/permission.py → seed()). feature_flags rows are seeded from FEATURE_FLAG_SEEDS.
--
-- P6 is a wave-based backlog (see plan/phase-6.md): every advanced feature ships behind
-- a feature_flags toggle; flag off = no cost to P0–P5. This increment lands the flag
-- foundation + R2 bookmarks/labels.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `feature_flags` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `key`                VARCHAR(80)     NOT NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 0,
  `scope`              VARCHAR(16)     NOT NULL DEFAULT 'global',
  `camera_id`          BIGINT UNSIGNED NULL,
  `value`              JSON            NULL,
  `description`        VARCHAR(300)    NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  UNIQUE KEY `uq_feature_flags_key_camera` (`key`, `camera_id`),
  KEY `idx_feature_flags_key` (`key`),
  KEY `idx_feature_flags_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `share_links` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `token_hash`         CHAR(64)        NOT NULL,
  `kind`               VARCHAR(16)     NOT NULL,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `target_ref`         VARCHAR(64)     NULL,
  `range_start`        DATETIME(3)     NULL,
  `range_end`          DATETIME(3)     NULL,
  `label`              VARCHAR(200)    NULL,
  `password_hash`      CHAR(64)        NULL,
  `watermark`          TINYINT(1)      NOT NULL DEFAULT 0,
  `max_views`          INT             NULL,
  `view_count`         INT             NOT NULL DEFAULT 0,
  `expires_at`         DATETIME(3)     NULL,
  `revoked_at`         DATETIME(3)     NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  UNIQUE KEY `uq_share_links_token` (`token_hash`),
  KEY `idx_share_links_creator` (`created_by_id`),
  KEY `idx_share_links_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- R3 — export watermark (extends P2 export_jobs). Password-protected zip deferred (needs
-- an AES-zip lib = new dependency). On a fresh install export_jobs comes from 0002; these
-- ADD COLUMNs run once here. (Existing DBs: run the same ALTER manually.)
ALTER TABLE `export_jobs`
  ADD COLUMN `watermark`          TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN `watermark_text`     VARCHAR(200) NULL,
  ADD COLUMN `password_protected` TINYINT(1)   NOT NULL DEFAULT 0,
  ADD COLUMN `enc_password`       VARBINARY(512) NULL,
  ADD COLUMN `enc_key_id`         VARCHAR(50)  NULL;

-- N1 — Twilio SMS recipient on notification subscriptions (extends P5). Existing DBs: run
-- this ALTER manually.
ALTER TABLE `notification_subscriptions`
  ADD COLUMN `sms_to` VARCHAR(32) NULL;

-- L5 fisheye + R4 dual recording + R6 edge recording (extends P1 cameras) + L7 HW decode
-- (extends P4 ai_settings). Existing DBs: ALTER manually.
ALTER TABLE `cameras`
  ADD COLUMN `fisheye`        TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN `fisheye_params` JSON       NULL,
  ADD COLUMN `dual_recording` TINYINT(1) NOT NULL DEFAULT 0,
  ADD COLUMN `edge_recording` TINYINT(1) NOT NULL DEFAULT 0;
ALTER TABLE `ai_settings`
  ADD COLUMN `hwaccel` VARCHAR(16) NOT NULL DEFAULT 'none';

-- A4 — audio classification config (extends P4 ai_settings). Existing DBs: ALTER manually.
ALTER TABLE `ai_settings`
  ADD COLUMN `audio_enabled`   TINYINT(1)  NOT NULL DEFAULT 0,
  ADD COLUMN `audio_threshold` SMALLINT    NOT NULL DEFAULT 60;

-- R4 — dual recording tags each segment with its stream role (main | sub). Existing DBs:
-- ALTER manually. The high-frequency segments table comes from 0002.
ALTER TABLE `segments`
  ADD COLUMN `stream_role` VARCHAR(8) NOT NULL DEFAULT 'main';

-- R6 — edge-recording import jobs (gap-fill from camera SD). New table.
CREATE TABLE IF NOT EXISTS `edge_import_jobs` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `range_start`        DATETIME(3)     NOT NULL,
  `range_end`          DATETIME(3)     NOT NULL,
  `status`             VARCHAR(12)     NOT NULL DEFAULT 'queued',
  `progress`           INT             NOT NULL DEFAULT 0,
  `clips_found`        INT             NOT NULL DEFAULT 0,
  `clips_imported`     INT             NOT NULL DEFAULT 0,
  `bytes_done`         BIGINT          NOT NULL DEFAULT 0,
  `manifest`           JSON            NULL,
  `celery_task_id`     VARCHAR(100)    NULL,
  `error_message`      VARCHAR(1000)   NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_edge_import_jobs_camera` (`camera_id`),
  KEY `idx_edge_import_jobs_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A4 — audio classification results (high-frequency, FK-free, no soft delete). New table.
CREATE TABLE IF NOT EXISTS `audio_detections` (
  `id`          BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`   BIGINT UNSIGNED NOT NULL,
  `ts`          DATETIME(3)     NOT NULL,
  `label`       VARCHAR(32)     NOT NULL,
  `score`       SMALLINT        NOT NULL,
  `clip_path`   VARCHAR(500)    NULL,
  `event_id`    BIGINT UNSIGNED NULL,
  `node_id`     BIGINT UNSIGNED NULL,
  `created_at`  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY `idx_aud_cam_ts` (`camera_id`, `ts`),
  KEY `idx_aud_label_ts` (`label`, `ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `counting_lines` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `name`               VARCHAR(80)     NOT NULL,
  `kind`               VARCHAR(16)     NOT NULL DEFAULT 'line',
  `geometry`           JSON            NOT NULL,
  `class_filter`       JSON            NULL,
  `direction_labels`   JSON            NULL,
  `loiter_threshold_s` INT             NULL,
  `occupancy_threshold` INT            NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_counting_lines_camera` (`camera_id`),
  KEY `idx_counting_lines_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `counting_stats` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `line_id`            BIGINT UNSIGNED NOT NULL,
  `bucket_ts`          DATETIME(3)     NOT NULL,
  `in_count`           INT             NOT NULL DEFAULT 0,
  `out_count`          INT             NOT NULL DEFAULT 0,
  `occupancy`          INT             NOT NULL DEFAULT 0,
  `label`              VARCHAR(32)     NULL,
  KEY `idx_counting_stats_cam` (`camera_id`),
  KEY `idx_counting_stats_line` (`line_id`),
  KEY `idx_counting_stats_bucket` (`bucket_ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `maps` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `name`               VARCHAR(120)    NOT NULL,
  `kind`               VARCHAR(16)     NOT NULL DEFAULT 'geo',
  `image_url`          VARCHAR(1000)   NULL,
  `config`             JSON            NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_maps_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `map_markers` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `map_id`             BIGINT UNSIGNED NOT NULL,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `x`                  DOUBLE          NOT NULL,
  `y`                  DOUBLE          NOT NULL,
  `heading`            DOUBLE          NULL,
  `label`              VARCHAR(120)    NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  KEY `idx_map_markers_map` (`map_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `archive_targets` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `name`               VARCHAR(120)    NOT NULL,
  `type`               VARCHAR(8)      NOT NULL,
  `config`             JSON            NULL,
  `enc_config`         VARBINARY(2048) NULL,
  `enc_key_id`         VARCHAR(50)     NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_archive_targets_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `archive_jobs` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `target_id`          BIGINT UNSIGNED NOT NULL,
  `source_type`        VARCHAR(16)     NOT NULL DEFAULT 'recording',
  `source_ref`         VARCHAR(64)     NOT NULL,
  `status`             VARCHAR(12)     NOT NULL DEFAULT 'queued',
  `progress`           INT             NOT NULL DEFAULT 0,
  `bytes_total`        BIGINT          NOT NULL DEFAULT 0,
  `bytes_done`         BIGINT          NOT NULL DEFAULT 0,
  `manifest`           JSON            NULL,
  `celery_task_id`     VARCHAR(100)    NULL,
  `error_message`      VARCHAR(1000)   NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_archive_jobs_target` (`target_id`),
  KEY `idx_archive_jobs_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `privacy_masks` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `name`               VARCHAR(80)     NOT NULL,
  `polygon`            JSON            NOT NULL,
  `mode`               VARCHAR(16)     NOT NULL DEFAULT 'server_render',
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_privacy_masks_camera` (`camera_id`),
  KEY `idx_privacy_masks_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `embeddings` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `source_type`        VARCHAR(16)     NOT NULL,
  `source_ref`         VARCHAR(64)     NOT NULL,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `ts`                 DATETIME(3)     NOT NULL,
  `text`               VARCHAR(300)    NULL,
  `backend`            VARCHAR(16)     NOT NULL,
  `dim`                INT             NOT NULL,
  `vector`             JSON            NOT NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY `uq_embeddings_source` (`source_type`, `source_ref`),
  KEY `idx_embeddings_camera_ts` (`camera_id`, `ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `bookmarks` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `start_ts`           DATETIME(3)     NOT NULL,
  `end_ts`             DATETIME(3)     NULL,
  `label`              VARCHAR(200)    NOT NULL,
  `color`              VARCHAR(16)     NULL,
  `note`               TEXT            NULL,
  `recording_id`       BIGINT UNSIGNED NULL,
  `event_id`           BIGINT UNSIGNED NULL,
  `lock_retention`     TINYINT(1)      NOT NULL DEFAULT 0,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_bookmarks_camera_ts` (`camera_id`, `start_ts`),
  KEY `idx_bookmarks_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
