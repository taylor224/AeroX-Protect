-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — Phase 9 (remote portal — TURN/STUN relay)
--
-- Runs after 0008. One new singleton table holding the ICE-server config handed to
-- WebRTC clients for outside-LAN live/playback. The coturn `static-auth-secret` is
-- Fernet-encrypted; clients receive short-lived HMAC credentials derived from it.
-- Flag-gated (`remote_portal`, default OFF). Permission key `portal:manage` seeded via
-- the P0 catalog.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `turn_config` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `singleton`          TINYINT(1)      NOT NULL DEFAULT 1,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 0,
  `stun_urls`          JSON            NULL,
  `turn_host`          VARCHAR(255)    NULL,
  `turn_port`          INT             NOT NULL DEFAULT 3478,
  `turn_protocol`      VARCHAR(8)      NOT NULL DEFAULT 'udp',
  `turn_tls`           TINYINT(1)      NOT NULL DEFAULT 0,
  `realm`              VARCHAR(120)    NULL,
  `ttl_seconds`        INT             NOT NULL DEFAULT 3600,
  `auth_secret_enc`    VARBINARY(512)  NULL,
  `cred_key_id`        VARCHAR(32)     NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY `uq_turn_config_singleton` (`singleton`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
