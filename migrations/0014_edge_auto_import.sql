-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — per-camera edge auto-import (extends P6 R6 edge recording)
--
-- Runs after 0013. `edge_auto_import` opts a camera into a periodic background scan
-- (beat task edge_auto_import_scan, every 30 min) that gap-fills the NVR timeline from the
-- camera's on-board SD clips automatically. Requires `edge_recording` to also be on.
-- Existing DBs: run this ALTER manually before restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

ALTER TABLE `cameras`
  ADD COLUMN `edge_auto_import` TINYINT(1) NOT NULL DEFAULT 0 AFTER `edge_recording`;
