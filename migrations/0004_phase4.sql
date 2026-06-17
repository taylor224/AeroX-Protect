-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 4 (AI object detection + search + distributed nodes)
--
-- Runs after 0003. All-new tables (no drops). Mirrors server/model/{detection,
-- detection_zone,object_trigger,ai_node,detection_assignment,ai_settings}.py.
-- UTC DATETIME(3); Snowflake BIGINT UNSIGNED. events.type already supports 'object'
-- and source 'server' (P3). Permission keys (detections/zones/triggers/ai/ai_nodes)
-- were seeded in the P0 catalog (0000_init.sql). Global ai_settings + builtin ai_node
-- are seeded by `poetry run seed`.
-- detections is FK-free, soft-delete-free, ultra-high-frequency (retention = batch
-- DELETE / future RANGE-partition DROP on created_at).
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `detections` (
  `id`          BIGINT UNSIGNED NOT NULL,
  `camera_id`   BIGINT UNSIGNED NOT NULL,
  `ts`          DATETIME(3)     NOT NULL,
  `class_id`    SMALLINT        NOT NULL,
  `label`       VARCHAR(32)     NOT NULL,
  `confidence`  SMALLINT        NOT NULL,
  `track_id`    BIGINT UNSIGNED NULL,
  `track_key`   CHAR(32)        NULL,
  `bbox`        JSON            NOT NULL,
  `frame_w`     SMALLINT        NULL,
  `frame_h`     SMALLINT        NULL,
  `zone_id`     BIGINT UNSIGNED NULL,
  `segment_id`  BIGINT UNSIGNED NULL,
  `event_id`    BIGINT UNSIGNED NULL,
  `attrs`       JSON            NULL,
  `node_id`     BIGINT UNSIGNED NULL,
  `created_at`  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_det_cam_ts` (`camera_id`, `ts`),
  KEY `idx_det_label_ts` (`label`, `ts`),
  KEY `idx_det_cam_label_ts` (`camera_id`, `label`, `ts`),
  KEY `idx_det_track` (`camera_id`, `track_id`),
  KEY `idx_det_zone_ts` (`zone_id`, `ts`),
  KEY `idx_det_segment` (`segment_id`),
  KEY `idx_det_event` (`event_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
-- (large-scale) ALTER TABLE detections PARTITION BY RANGE (TO_DAYS(created_at)) (...) — §14 Q5

CREATE TABLE IF NOT EXISTS `detection_zones` (
  `id`                 BIGINT UNSIGNED NOT NULL,
  `camera_id`          BIGINT UNSIGNED NOT NULL,
  `name`               VARCHAR(80)     NOT NULL,
  `kind`               VARCHAR(16)     NOT NULL DEFAULT 'include',
  `polygon`            JSON            NOT NULL,
  `label_filter`       JSON            NULL,
  `color`              VARCHAR(9)      NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `priority`           SMALLINT        NOT NULL DEFAULT 0,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_zone_cam` (`camera_id`),
  KEY `idx_zone_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `object_triggers` (
  `id`                 BIGINT UNSIGNED NOT NULL,
  `camera_id`          BIGINT UNSIGNED NULL,
  `name`               VARCHAR(80)     NOT NULL,
  `labels`             JSON            NOT NULL,
  `zone_id`            BIGINT UNSIGNED NULL,
  `min_confidence`     SMALLINT        NOT NULL DEFAULT 50,
  `min_dwell_ms`       INT             NOT NULL DEFAULT 0,
  `require_zone_entry` TINYINT(1)      NOT NULL DEFAULT 0,
  `min_count`          SMALLINT        NOT NULL DEFAULT 1,
  `cooldown_s`         SMALLINT        NOT NULL DEFAULT 30,
  `debounce_per_track` TINYINT(1)      NOT NULL DEFAULT 1,
  `event_subtype`      VARCHAR(48)     NULL,
  `action_hint`        VARCHAR(16)     NULL,
  `notify`             TINYINT(1)      NOT NULL DEFAULT 1,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `active_schedule_id` BIGINT UNSIGNED NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_trig_cam` (`camera_id`),
  KEY `idx_trig_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `ai_nodes` (
  `id`                 BIGINT UNSIGNED NOT NULL,
  `uuid`               CHAR(32)        NOT NULL,
  `name`               VARCHAR(80)     NOT NULL,
  `kind`               VARCHAR(16)     NOT NULL DEFAULT 'remote',
  `endpoint`           VARCHAR(255)    NULL,
  `status`             VARCHAR(16)     NOT NULL DEFAULT 'offline',
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `gpu`                TINYINT(1)      NOT NULL DEFAULT 0,
  `gpu_name`           VARCHAR(80)     NULL,
  `capacity`           SMALLINT        NOT NULL DEFAULT 0,
  `capabilities`       JSON            NULL,
  `bench`              JSON            NULL,
  `version`            VARCHAR(40)     NULL,
  `assigned_count`     SMALLINT        NOT NULL DEFAULT 0,
  `last_heartbeat_ts`  DATETIME(3)     NULL,
  `token_jti`          CHAR(36)        NULL,
  `last_seen_ip`       VARCHAR(64)     NULL,
  `last_error`         VARCHAR(512)    NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_node_uuid` (`uuid`),
  KEY `idx_node_status` (`status`),
  KEY `idx_node_heartbeat` (`last_heartbeat_ts`),
  KEY `idx_node_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `detection_assignments` (
  `id`             BIGINT UNSIGNED NOT NULL,
  `camera_id`      BIGINT UNSIGNED NOT NULL,
  `node_id`        BIGINT UNSIGNED NOT NULL,
  `state`          VARCHAR(16)     NOT NULL DEFAULT 'pending',
  `model`          VARCHAR(40)     NULL,
  `target_fps`     SMALLINT        NULL,
  `claimed_at`     DATETIME(3)     NULL,
  `last_report_ts` DATETIME(3)     NULL,
  `epoch`          INT             NOT NULL DEFAULT 0,
  `created_at`     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_assign_cam` (`camera_id`),
  KEY `idx_assign_node` (`node_id`),
  KEY `idx_assign_state` (`state`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `ai_settings` (
  `id`                   BIGINT UNSIGNED NOT NULL,
  `camera_id`            BIGINT UNSIGNED NULL,
  `detection_enabled`    TINYINT(1)      NOT NULL DEFAULT 1,
  `gpu_enabled`          TINYINT(1)      NOT NULL DEFAULT 0,
  `model`                VARCHAR(40)     NOT NULL DEFAULT 'yolov8n',
  `target_fps`           SMALLINT        NOT NULL DEFAULT 5,
  `imgsz`                SMALLINT        NOT NULL DEFAULT 640,
  `min_confidence`       SMALLINT        NOT NULL DEFAULT 35,
  `labels`               JSON            NULL,
  `clip_enabled`         TINYINT(1)      NOT NULL DEFAULT 0,
  `live_overlay_enabled` TINYINT(1)      NOT NULL DEFAULT 0,
  `store_crops`          TINYINT(1)      NOT NULL DEFAULT 0,
  `retention_days`       SMALLINT        NOT NULL DEFAULT 30,
  `sample_interval_ms`   INT             NOT NULL DEFAULT 1000,
  `created_at`           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `last_updated_by_id`   BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_aiset_cam` (`camera_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
