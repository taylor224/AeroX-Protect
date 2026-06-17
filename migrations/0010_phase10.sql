-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 10 (access control — doors, credentials, access events)
--
-- Runs after 0009. All-new tables. Doors drive a lock relay (mock/vendor_http/onvif);
-- credentials (card + optional sha256+pepper PIN) gate by access_group + validity window;
-- every swipe decision is logged to access_events and promoted to a P3 `access` event
-- (camera-scoped when the door has a linked camera). Flag-gated (`access_control`, default
-- OFF). Permission keys (access:read/control/manage) seeded via the P0 catalog.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `doors` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `name`               VARCHAR(120)    NOT NULL,
  `location`           VARCHAR(200)    NULL,
  `controller_type`    VARCHAR(16)     NOT NULL DEFAULT 'mock',
  `controller_config`  JSON            NULL,
  `lock_state`         VARCHAR(12)     NOT NULL DEFAULT 'locked',
  `camera_id`          BIGINT UNSIGNED NULL,
  `access_group`       VARCHAR(64)     NOT NULL DEFAULT 'default',
  `require_pin`        TINYINT(1)      NOT NULL DEFAULT 0,
  `unlock_seconds`     INT             NOT NULL DEFAULT 5,
  `unlocked_at`        DATETIME(3)     NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_doors_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `access_credentials` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `card_number`        VARCHAR(64)     NOT NULL,
  `holder_name`        VARCHAR(120)    NOT NULL,
  `identity_id`        BIGINT UNSIGNED NULL,
  `access_group`       VARCHAR(64)     NOT NULL DEFAULT 'default',
  `pin_hash`           CHAR(64)        NULL,
  `valid_from`         DATETIME(3)     NULL,
  `valid_until`        DATETIME(3)     NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_access_cred_card` (`card_number`),
  KEY `idx_access_cred_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `access_events` (
  `id`             BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `door_id`        BIGINT UNSIGNED NOT NULL,
  `credential_id`  BIGINT UNSIGNED NULL,
  `card_number`    VARCHAR(64)     NULL,
  `holder_name`    VARCHAR(120)    NULL,
  `decision`       VARCHAR(8)      NOT NULL,
  `reason`         VARCHAR(40)     NULL,
  `source`         VARCHAR(16)     NULL,
  `ts`             DATETIME(3)     NOT NULL,
  `event_id`       BIGINT UNSIGNED NULL,
  KEY `idx_access_door_ts` (`door_id`, `ts`),
  KEY `idx_access_card_ts` (`card_number`, `ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
