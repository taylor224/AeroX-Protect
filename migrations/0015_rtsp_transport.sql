-- ─────────────────────────────────────────────────────────────────────────────
-- AeroXProtect (axp) — per-camera RTSP transport (extends P1 cameras)
--
-- Runs after 0014. `rtsp_transport` selects how go2rtc connects to the camera over RTSP:
-- NULL = auto (go2rtc native, interleaved TCP); 'tcp' / 'udp' force it via go2rtc's ffmpeg
-- source (built-in rtsp/tcp|rtsp/udp preset). Existing DBs: run this ALTER manually before
-- restarting the backend.
-- ─────────────────────────────────────────────────────────────────────────────
USE `axp`;

ALTER TABLE `cameras`
  ADD COLUMN `rtsp_transport` VARCHAR(8) NULL AFTER `rtsp_port`;
