-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — initial schema (P0)
--
-- This file runs via docker-entrypoint-initdb.d on first MySQL init. It mirrors the
-- SQLAlchemy models (server/model/*) which are the single source of truth; keep both
-- in sync (PLAN §4.7). All ids are application Snowflake BIGINT UNSIGNED (seed rows
-- reserve ids 1..999). All timestamps are UTC DATETIME(3) (PLAN §12.1).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS `axp`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `axp`;

-- ── roles ────────────────────────────────────────────────────────────────────
CREATE TABLE `roles` (
  `id` BIGINT UNSIGNED NOT NULL,
  `name` VARCHAR(50) NOT NULL,
  `display_name` VARCHAR(100) NOT NULL,
  `description` VARCHAR(500) NULL,
  `permissions` JSON NOT NULL,
  `is_system` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_roles_name` (`name`),
  KEY `idx_roles_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── users ────────────────────────────────────────────────────────────────────
CREATE TABLE `users` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `login_id` VARCHAR(190) NOT NULL,
  `password` VARCHAR(255) NOT NULL,
  `name` VARCHAR(120) NOT NULL,
  `email` VARCHAR(190) NULL,
  `phone_number` VARCHAR(40) NULL,
  `role_id` BIGINT UNSIGNED NOT NULL,
  `permissions` JSON NOT NULL,
  `language` VARCHAR(10) NOT NULL DEFAULT 'ko',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `failed_login_count` INT NOT NULL DEFAULT 0,
  `locked_until` DATETIME(3) NULL,
  `last_login_at` DATETIME(3) NULL,
  `token_version` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_login_id` (`login_id`),
  UNIQUE KEY `uq_users_uuid` (`uuid`),
  KEY `idx_users_role_id` (`role_id`),
  KEY `idx_users_email` (`email`),
  KEY `idx_users_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── permissions (catalog) ────────────────────────────────────────────────────
CREATE TABLE `permissions` (
  `id` BIGINT UNSIGNED NOT NULL,
  `resource` VARCHAR(50) NOT NULL,
  `action` VARCHAR(50) NOT NULL,
  `description` VARCHAR(300) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_permissions_resource_action` (`resource`, `action`),
  KEY `idx_permissions_resource` (`resource`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── refresh_tokens (rotation + reuse detection) ──────────────────────────────
CREATE TABLE `refresh_tokens` (
  `id` BIGINT UNSIGNED NOT NULL,
  `user_id` BIGINT UNSIGNED NOT NULL,
  `jti` CHAR(36) NOT NULL,
  `family_id` CHAR(36) NOT NULL,
  `issued_at` DATETIME(3) NOT NULL,
  `expires_at` DATETIME(3) NOT NULL,
  `rotated_to_jti` CHAR(36) NULL,
  `revoked_at` DATETIME(3) NULL,
  `user_agent` VARCHAR(255) NULL,
  `ip` VARCHAR(64) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_refresh_jti` (`jti`),
  KEY `idx_refresh_user` (`user_id`),
  KEY `idx_refresh_family` (`family_id`),
  KEY `idx_refresh_expires` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── audit_logs (security + access log) ───────────────────────────────────────
CREATE TABLE `audit_logs` (
  `id` BIGINT UNSIGNED NOT NULL,
  `action` VARCHAR(80) NOT NULL,
  `target` VARCHAR(190) NULL,
  `user_id` BIGINT UNSIGNED NULL,
  `method` VARCHAR(10) NULL,
  `path` VARCHAR(500) NULL,
  `ip` VARCHAR(64) NULL,
  `user_agent` VARCHAR(255) NULL,
  `detail` JSON NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_audit_action` (`action`),
  KEY `idx_audit_user` (`user_id`),
  KEY `idx_audit_target` (`target`),
  KEY `idx_audit_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── cameras (P1 skeleton) ────────────────────────────────────────────────────
CREATE TABLE `cameras` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `name` VARCHAR(120) NOT NULL,
  `vendor` VARCHAR(40) NULL,
  `model` VARCHAR(120) NULL,
  `driver` VARCHAR(40) NULL,
  `host` VARCHAR(190) NULL,
  `port` INT NULL,
  `credentials_encrypted` TEXT NULL,
  `capabilities` JSON NOT NULL,
  `status` VARCHAR(20) NOT NULL DEFAULT 'unknown',
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_cameras_uuid` (`uuid`),
  KEY `idx_cameras_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── streams (P1 skeleton) ────────────────────────────────────────────────────
CREATE TABLE `streams` (
  `id` BIGINT UNSIGNED NOT NULL,
  `camera_id` BIGINT UNSIGNED NOT NULL,
  `role` VARCHAR(10) NULL,
  `codec` VARCHAR(20) NULL,
  `resolution` VARCHAR(20) NULL,
  `fps` INT NULL,
  `go2rtc_name` VARCHAR(120) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_streams_camera_id` (`camera_id`),
  KEY `idx_streams_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── disks (P2 skeleton) ──────────────────────────────────────────────────────
CREATE TABLE `disks` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `mount_path` VARCHAR(255) NOT NULL,
  `capacity_bytes` BIGINT NULL,
  `reserved_free_bytes` BIGINT NOT NULL DEFAULT 0,
  `role` VARCHAR(20) NULL,
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_disks_mount_path` (`mount_path`),
  UNIQUE KEY `uq_disks_uuid` (`uuid`),
  KEY `idx_disks_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── storage_policies (P2 skeleton) ───────────────────────────────────────────
CREATE TABLE `storage_policies` (
  `id` BIGINT UNSIGNED NOT NULL,
  `name` VARCHAR(120) NOT NULL,
  `strategy` VARCHAR(20) NULL,
  `config` JSON NOT NULL,
  `enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  KEY `idx_storage_policies_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── dashboards (P1/P5 skeleton) ──────────────────────────────────────────────
CREATE TABLE `dashboards` (
  `id` BIGINT UNSIGNED NOT NULL,
  `uuid` CHAR(32) NOT NULL,
  `name` VARCHAR(120) NOT NULL,
  `layout` JSON NOT NULL,
  `acl` JSON NOT NULL,
  `is_default` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at` DATETIME(3) NULL,
  `created_by_id` BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dashboards_uuid` (`uuid`),
  KEY `idx_dashboards_deleted_at` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── settings (global KV) ─────────────────────────────────────────────────────
CREATE TABLE `settings` (
  `id` BIGINT UNSIGNED NOT NULL,
  `key` VARCHAR(120) NOT NULL,
  `value` JSON NULL,
  `description` VARCHAR(300) NULL,
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_settings_key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ═══════════════════════════════ SEED DATA ═══════════════════════════════════
-- System roles (reserved ids). admin = full wildcard; user = no base permissions.
INSERT INTO `roles` (`id`,`name`,`display_name`,`permissions`,`is_system`,`created_at`,`updated_at`) VALUES
 (1,'admin','관리자','{"*": ["*"]}',1,UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
 (2,'user','사용자','{}',1,UTC_TIMESTAMP(3),UTC_TIMESTAMP(3));

-- Permission catalog (PLAN §12.2) — kept in sync with server/model/permission.py.
INSERT INTO `permissions` (`id`,`resource`,`action`,`description`,`created_at`,`updated_at`) VALUES
(100,'users','read','사용자 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(101,'users','create','사용자 생성',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(102,'users','update','사용자 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(103,'users','delete','사용자 삭제',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(104,'roles','read','역할 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(105,'roles','update','역할 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(106,'roles','manage','역할 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(107,'audit','read','감사로그 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(108,'settings','read','설정 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(109,'settings','update','설정 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(110,'cameras','read','카메라 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(111,'cameras','create','카메라 추가',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(112,'cameras','update','카메라 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(113,'cameras','delete','카메라 삭제',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(114,'cameras','discover','카메라 검색',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(115,'live','read','라이브 보기',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(116,'ptz','control','PTZ 제어',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(117,'streams','read','스트림 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(118,'streams','update','스트림 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(119,'dashboards','read','대시보드 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(120,'dashboards','create','대시보드 생성',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(121,'dashboards','update','대시보드 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(122,'dashboards','delete','대시보드 삭제',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(123,'dashboards','share','대시보드 공유',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(124,'recordings','read','녹화 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(125,'recordings','control','녹화 제어',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(126,'playback','read','재생',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(127,'clips','export','클립 내보내기',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(128,'storage','read','스토리지 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(129,'storage','manage','스토리지 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(130,'retention','manage','보존정책 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(131,'events','read','이벤트 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(132,'events','update','이벤트 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(133,'events','delete','이벤트 삭제',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(134,'policies','read','정책 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(135,'policies','update','정책 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(136,'schedules','read','스케줄 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(137,'schedules','update','스케줄 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(138,'timelapse','read','타임랩스 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(139,'timelapse','create','타임랩스 생성',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(140,'timelapse','cancel','타임랩스 취소',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(141,'detections','read','검출 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(142,'zones','read','검출구역 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(143,'zones','update','검출구역 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(144,'triggers','read','트리거 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(145,'triggers','update','트리거 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(146,'ai','read','AI 설정 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(147,'ai','update','AI 설정 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(148,'ai_nodes','manage','AI 노드 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(149,'rules','read','규칙 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(150,'rules','create','규칙 생성',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(151,'rules','update','규칙 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(152,'rules','delete','규칙 삭제',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(153,'targets','read','대상 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(154,'targets','manage','대상 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(155,'monitors','read','모니터 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(156,'monitors','manage','모니터 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(157,'notifications','read','알림 조회',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(158,'notifications','update','알림 수정',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(159,'api_tokens','manage','API 토큰 관리',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3));

-- Bootstrap settings. NOTE (PLAN §12.1): gpu_enabled here is a placeholder — global
-- GPU authority moves to P4 ai_settings.gpu_enabled.
INSERT INTO `settings` (`id`,`key`,`value`,`description`,`created_at`,`updated_at`) VALUES
(1,'gpu_enabled','false','전역 GPU 사용 (P4에서 ai_settings로 이관)',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(2,'timezone','"Asia/Seoul"','표시 시간대',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3)),
(3,'retention_default_days','30','기본 보존 기간(일)',UTC_TIMESTAMP(3),UTC_TIMESTAMP(3));

-- First admin: created at runtime by `seed-admin` (Argon2 hash from BOOTSTRAP_ADMIN_*).
