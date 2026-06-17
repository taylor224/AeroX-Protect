-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — per-camera dual-recording stream choice (extends P6 R4)
--
-- Runs after 0011. `dual_record_stream` lets the camera settings choose WHICH stream the
-- dual recorder captures (role: main/sub/third). NULL = auto (prefer 'sub'). Existing DBs:
-- run this ALTER manually before restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

ALTER TABLE `cameras`
  ADD COLUMN `dual_record_stream` VARCHAR(16) NULL AFTER `dual_recording`;
