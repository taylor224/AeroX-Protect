-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 1 (camera onboarding + live view)
--
-- Runs after 0000_init.sql. The P0 skeleton tables (cameras/streams/dashboards)
-- are empty at this point, so we drop + recreate them at full P1 schema rather
-- than ALTER column-by-column. Mirrors server/model/{camera,stream,dashboard,
-- dashboard_acl,ptz_preset}.py. All ids = Snowflake BIGINT UNSIGNED; timestamps
-- = UTC DATETIME(3) (PLAN §12.1).
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

DROP TABLE IF EXISTS `streams`;
DROP TABLE IF EXISTS `dashboards`;
DROP TABLE IF EXISTS `cameras`;

CREATE TABLE `cameras` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `name` VARCHAR(200) NOT NULL,
  `vendor` VARCHAR(32) NOT NULL DEFAULT 'unknown',
  `model` VARCHAR(128) NULL,
  `firmware` VARCHAR(128) NULL,
  `serial` VARCHAR(128) NULL,
  `driver` VARCHAR(32) NOT NULL DEFAULT 'onvif',
  `protocol_fallback` VARCHAR(32) NULL,
  `host` VARCHAR(255) NOT NULL,
  `onvif_port` INT NULL,
  `http_port` INT NULL,
  `rtsp_port` INT NULL,
  `use_https` TINYINT(1) NOT NULL DEFAULT 0,
  `username_enc` VARBINARY(512) NULL,
  `password_enc` VARBINARY(512) NULL,
  `cred_key_id` VARCHAR(32) NULL,
  `capabilities` JSON NULL,
  `ptz_supported` TINYINT(1) NOT NULL DEFAULT 0,
  `audio_supported` TINYINT(1) NOT NULL DEFAULT 0,
  `two_way_audio` TINYINT(1) NOT NULL DEFAULT 0,
  `channel` INT NOT NULL DEFAULT 1,
  `timezone` VARCHAR(64) NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'unknown',
  `last_seen_at` DATETIME(3) NULL,
  `last_error` VARCHAR(512) NULL,
  `is_enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cameras_uuid` (`uuid`),
  KEY `ix_cameras_host` (`host`, `channel`),
  KEY `ix_cameras_vendor` (`vendor`),
  KEY `ix_cameras_status` (`status`),
  KEY `ix_cameras_serial` (`serial`),
  KEY `ix_cameras_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `streams` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `role` VARCHAR(16) NOT NULL,
  `codec` VARCHAR(16) NULL,
  `width` INT NULL,
  `height` INT NULL,
  `fps` INT NULL,
  `bitrate_kbps` INT NULL,
  `audio_codec` VARCHAR(16) NULL,
  `rtsp_path` VARCHAR(255) NULL,
  `rtsp_url_template` VARCHAR(512) NULL,
  `go2rtc_name` VARCHAR(128) NOT NULL,
  `is_default_live` TINYINT(1) NOT NULL DEFAULT 0,
  `is_default_full` TINYINT(1) NOT NULL DEFAULT 0,
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_streams_go2rtc` (`go2rtc_name`),
  KEY `ix_streams_camera_role` (`camera_id`, `role`),
  KEY `ix_streams_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `dashboards` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `name` VARCHAR(200) NOT NULL,
  `description` VARCHAR(512) NULL,
  `layout` JSON NOT NULL,
  `owner_id` BIGINT UNSIGNED NOT NULL,
  `is_shared` TINYINT(1) NOT NULL DEFAULT 0,
  `default_ratio_mode` VARCHAR(8) NOT NULL DEFAULT 'fit',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dashboards_uuid` (`uuid`),
  KEY `ix_dashboards_owner` (`owner_id`),
  KEY `ix_dashboards_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `dashboard_acl` (
  `id` BIGINT UNSIGNED NOT NULL,
  `dashboard_id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `access` VARCHAR(8) NOT NULL DEFAULT 'view',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dacl` (`dashboard_id`, `user_id`),
  KEY `ix_dacl_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `ptz_presets` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `ptz_token` VARCHAR(64) NULL,
  `name` VARCHAR(128) NOT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  PRIMARY KEY (`id`),
  KEY `ix_ptz_camera` (`camera_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
