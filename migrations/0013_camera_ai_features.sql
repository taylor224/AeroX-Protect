-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — per-camera AI feature enables (extends P1 cameras)
--
-- Runs after 0012. `ai_features` is a JSON map of per-camera AI toggles
-- ({audio,smoke,face,lpr}); these used to be global feature flags and are now configured
-- in the camera's settings. The ingest/alert paths check `cameras.ai_features` instead of
-- a global flag. Existing DBs: run this ALTER manually before restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

ALTER TABLE `cameras`
  ADD COLUMN `ai_features` JSON NULL AFTER `edge_recording`;
