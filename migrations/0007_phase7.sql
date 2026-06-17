-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 7 (LPR & face recognition — split from the P6 backlog)
--
-- Runs after 0006. All-new tables (no drops). Mirrors server/model/{plate_read,plate_list}
-- (P7a LPR) and server/model/{face_identity,face_read} (P7b face). Snowflake BIGINT PK,
-- UTC DATETIME(3), schema `axp`. Both features ship behind feature_flags (`lpr`/`face`,
-- default OFF — they need dedicated OCR/face models on a node). Permission keys
-- (lpr:read/manage, face:read/manage) seeded via the P0 catalog.
--
-- P7 events reuse the P3 enum (events.type VARCHAR): `lpr`/`face` (reserved in P3, filled here).
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

-- A7 LPR — plate reads (high-frequency, FK-free, no soft delete; mirrors detections).
CREATE TABLE IF NOT EXISTS `plate_reads` (
  `id`            BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`     BIGINT UNSIGNED NOT NULL,
  `ts`            DATETIME(3)     NOT NULL,
  `plate_text`    VARCHAR(24)     NOT NULL,
  `plate_key`     VARCHAR(24)     NOT NULL,
  `confidence`    SMALLINT        NOT NULL,
  `region`        JSON            NULL,
  `vehicle_label` VARCHAR(16)     NULL,
  `track_id`      BIGINT UNSIGNED NULL,
  `list_id`       BIGINT UNSIGNED NULL,
  `list_kind`     VARCHAR(8)      NULL,
  `event_id`      BIGINT UNSIGNED NULL,
  `node_id`       BIGINT UNSIGNED NULL,
  `created_at`    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY `idx_plate_cam_ts` (`camera_id`, `ts`),
  KEY `idx_plate_key_ts` (`plate_key`, `ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A7 LPR — watchlist (allow/deny). Soft-deleted + audited (policy data).
CREATE TABLE IF NOT EXISTS `plate_lists` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `plate_text`         VARCHAR(24)     NOT NULL,
  `plate_key`          VARCHAR(24)     NOT NULL,
  `kind`               VARCHAR(8)      NOT NULL DEFAULT 'deny',
  `label`              VARCHAR(120)    NULL,
  `note`               VARCHAR(500)    NULL,
  `action`             VARCHAR(32)     NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  UNIQUE KEY `uq_plate_lists_key_kind` (`plate_key`, `kind`),
  KEY `idx_plate_lists_key` (`plate_key`),
  KEY `idx_plate_lists_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A8 face — known-identity registry (persons). Privacy-sensitive: consent + soft delete
-- (right to erasure wipes `embeddings`). Reference vectors stored as JSON.
CREATE TABLE IF NOT EXISTS `face_identities` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `name`               VARCHAR(120)    NOT NULL,
  `note`               VARCHAR(500)    NULL,
  `external_ref`       VARCHAR(64)     NULL,
  `consent`            TINYINT(1)      NOT NULL DEFAULT 0,
  `consent_at`         DATETIME(3)     NULL,
  `retention_days`     INT             NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `backend`            VARCHAR(16)     NULL,
  `dim`                INT             NULL,
  `embeddings`         JSON            NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  KEY `idx_face_identities_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- A8 face — observed faces (high-frequency, FK-free). Embedding kept for re-matching;
-- not returned by the API.
CREATE TABLE IF NOT EXISTS `face_observations` (
  `id`            BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `camera_id`     BIGINT UNSIGNED NOT NULL,
  `ts`            DATETIME(3)     NOT NULL,
  `backend`       VARCHAR(16)     NOT NULL,
  `dim`           INT             NOT NULL,
  `embedding`     JSON            NOT NULL,
  `quality`       SMALLINT        NULL,
  `region`        JSON            NULL,
  `identity_id`   BIGINT UNSIGNED NULL,
  `identity_name` VARCHAR(120)    NULL,
  `score`         SMALLINT        NULL,
  `event_id`      BIGINT UNSIGNED NULL,
  `node_id`       BIGINT UNSIGNED NULL,
  `created_at`    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY `idx_face_cam_ts` (`camera_id`, `ts`),
  KEY `idx_face_identity_ts` (`identity_id`, `ts`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
