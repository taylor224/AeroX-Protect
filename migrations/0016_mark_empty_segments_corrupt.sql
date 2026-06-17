-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — data fix: mark zero-byte / zero-duration segments corrupt
--
-- Runs after 0015. Before the indexer guard (segment_indexer.py), ffmpeg's
-- -segment_atclocktime kept rolling empty files while the source was down (e.g.
-- go2rtc 404) and the indexer inserted them as valid rows with a fabricated 10s
-- duration. Those rows poisoned the playback timeline, HLS playlists and export
-- concat lists. The read paths already filter `corrupt = 1`, so flipping the flag
-- fixes playback immediately; retention removes the rows + files by age as usual.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

UPDATE `segments`
   SET `corrupt` = 1
 WHERE `corrupt` = 0
   AND (`size_bytes` = 0 OR `duration_ms` = 0);
