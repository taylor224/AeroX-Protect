-- 0020: Encoder worker nodes — offload live H.265→H.264 transcode + playback segment
-- transcode to separate encoder servers (mirrors the P4 ai_nodes / detection_assignments
-- pattern). New permission (encoding_nodes:manage), feature flag (encoding_nodes) and
-- setting (live_transcode_idle_s) are seeded by `poetry run seed` (PERMISSION_CATALOG /
-- FEATURE_FLAG_SEEDS / SETTING_SEEDS), not here.

CREATE TABLE IF NOT EXISTS `encoding_nodes` (
  `id`                 BIGINT UNSIGNED NOT NULL,
  `uuid`               CHAR(32)        NOT NULL,
  `name`               VARCHAR(80)     NOT NULL,
  `kind`               VARCHAR(16)     NOT NULL DEFAULT 'remote',
  `endpoint`           VARCHAR(255)    NULL,
  `status`             VARCHAR(16)     NOT NULL DEFAULT 'offline',
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `hwaccel`            VARCHAR(16)     NULL,
  `max_sessions`       SMALLINT        NOT NULL DEFAULT 0,
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
  UNIQUE KEY `uq_encnode_uuid` (`uuid`),
  KEY `idx_encnode_status` (`status`),
  KEY `idx_encnode_heartbeat` (`last_heartbeat_ts`),
  KEY `idx_encnode_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `encode_assignments` (
  `id`             BIGINT UNSIGNED NOT NULL,
  `camera_id`      BIGINT UNSIGNED NOT NULL,
  `node_id`        BIGINT UNSIGNED NOT NULL,
  `state`          VARCHAR(16)     NOT NULL DEFAULT 'pending',
  `claimed_at`     DATETIME(3)     NULL,
  `last_report_ts` DATETIME(3)     NULL,
  `epoch`          INT             NOT NULL DEFAULT 0,
  `created_at`     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_encassign_cam` (`camera_id`),
  KEY `idx_encassign_node` (`node_id`),
  KEY `idx_encassign_state` (`state`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
