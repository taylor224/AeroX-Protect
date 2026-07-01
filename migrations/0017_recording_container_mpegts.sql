-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — switch recording to MPEG-TS segments
--
-- Runs after 0016. Recorded playback moved to hls.js over a VOD playlist whose media
-- segments are MPEG-TS (the native HLS container). MPEG-TS also fixes fragile fMP4
-- recordings: no moov/faststart, resilient to a truncated tail on crash/restart, clean
-- concat, and it carries H.264/H.265 as-is (no hvc1 tagging needed). New segments are
-- written as .ts going forward; existing .mp4 segments keep playing (they are remuxed to
-- MPEG-TS on demand for the same playlist).
--
-- This flips the default container for existing storage policies. The column default for
-- new rows is set in the model (server/model/storage_policy.py).
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

UPDATE `storage_policies`
   SET `container` = 'mpegts'
 WHERE `container` = 'fmp4';
