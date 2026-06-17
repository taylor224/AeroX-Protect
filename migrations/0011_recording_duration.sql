-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — fixed-duration manual recording (extends P2 recordings)
--
-- Runs after 0010. `planned_end_ts` lets a manual recording auto-stop after a chosen
-- duration (the recording_autoclose beat task closes it). Existing DBs: run this ALTER
-- manually before restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

ALTER TABLE `recordings`
  ADD COLUMN `planned_end_ts` DATETIME(3) NULL AFTER `end_ts`;
