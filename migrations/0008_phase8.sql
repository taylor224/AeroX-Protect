-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 8 (multi-NVR federation)
--
-- Runs after 0007. All-new tables. A hub registers member AeroXProtect instances and
-- aggregates their cameras/events by calling each member's P5 external API (/api/v1/ext/*)
-- with a per-member Fernet-encrypted api_token. Flag-gated (`federation`, default OFF).
-- Permission keys (federation:read/manage) seeded via the P0 catalog.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `federation_members` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `name`               VARCHAR(120)    NOT NULL,
  `base_url`           VARCHAR(300)    NOT NULL,
  `token_enc`          VARBINARY(512)  NULL,
  `cred_key_id`        VARCHAR(32)     NULL,
  `status`             VARCHAR(16)     NOT NULL DEFAULT 'unknown',
  `last_sync_at`       DATETIME(3)     NULL,
  `last_error`         VARCHAR(500)    NULL,
  `camera_count`       INT             NOT NULL DEFAULT 0,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_federation_members_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `federation_cameras` (
  `id`            BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `member_id`     BIGINT UNSIGNED NOT NULL,
  `remote_uuid`   VARCHAR(64)     NOT NULL,
  `name`          VARCHAR(200)    NOT NULL,
  `status`        VARCHAR(16)     NULL,
  `online`        TINYINT(1)      NOT NULL DEFAULT 0,
  `last_sync_at`  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  UNIQUE KEY `uq_fed_cam_member_remote` (`member_id`, `remote_uuid`),
  KEY `idx_fed_cam_member` (`member_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
