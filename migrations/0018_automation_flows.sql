-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — visual automation flows (n8n-style node graph)
--
-- Runs after 0017. All-new tables. `flows.graph` stores the editor canvas verbatim
-- ({nodes, edges}); execution starts at trigger node(s) and walks branch edges
-- (condition true/false, action ok/err). Every run logs a per-node trail to
-- `flow_runs.node_results` so the editor can replay a run on the graph.
-- Existing DBs: run this file manually before restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

CREATE TABLE IF NOT EXISTS `flows` (
  `id`                 BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `uuid`               VARCHAR(32)     NOT NULL,
  `name`               VARCHAR(120)    NOT NULL,
  `description`        VARCHAR(500)    NULL,
  `enabled`            TINYINT(1)      NOT NULL DEFAULT 1,
  `graph`              JSON            NOT NULL,
  `cooldown_s`         SMALLINT        NOT NULL DEFAULT 0,
  `incoming_token`     VARCHAR(40)     NULL,
  `last_run_ts`        DATETIME(3)     NULL,
  `created_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  `deleted_at`         DATETIME(3)     NULL,
  `created_by_id`      BIGINT UNSIGNED NULL,
  `last_updated_by_id` BIGINT UNSIGNED NULL,
  UNIQUE KEY `uq_flows_uuid` (`uuid`),
  UNIQUE KEY `uq_flows_incoming_token` (`incoming_token`),
  KEY `idx_flows_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `flow_runs` (
  `id`               BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  `flow_id`          BIGINT UNSIGNED NOT NULL,
  `trigger_type`     VARCHAR(16)     NOT NULL,
  `event_id`         BIGINT UNSIGNED NULL,
  `camera_id`        BIGINT UNSIGNED NULL,
  `status`           VARCHAR(16)     NOT NULL DEFAULT 'running',
  `skip_reason`      VARCHAR(32)     NULL,
  `trigger_snapshot` JSON            NULL,
  `node_results`     JSON            NULL,
  `started_ts`       DATETIME(3)     NULL,
  `finished_ts`      DATETIME(3)     NULL,
  `duration_ms`      INT             NULL,
  `created_at`       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `deleted_at`       DATETIME(3)     NULL,
  KEY `idx_flow_runs_flow` (`flow_id`),
  KEY `idx_flow_runs_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
