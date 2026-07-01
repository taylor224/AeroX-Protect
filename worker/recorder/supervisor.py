"""Recorder supervisor (PLAN P2 §6.4) — long-running process in axp-recorder.

Per-camera ffmpeg copy-codec segment recorder with a convergence loop: desired state
(storage_policies.record_mode=continuous OR an in-progress recording) drives start/stop.
Redis reconcile wakes it early; periodic polling guarantees convergence if a signal is
lost. Health (state/pid/last_segment/restart_count) is upserted to recorder_health.
"""
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field

from sqlalchemy import or_

import config
from server.model import db, utcnow
from server.model.camera import Camera
from server.model.recorder_health import (
    STATE_ERROR,
    STATE_RECONNECTING,
    STATE_RECORDING,
    STATE_STARTING,
    STATE_STOPPED,
    RecorderHealth,
)
from server.model.recording import Recording
from server.model.storage_policy import StoragePolicy
from server.service import ffmpeg, segment_indexer, storage_manager

logger = logging.getLogger(__name__)

# Fast first retry keeps the recording gap after a transient camera/go2rtc blip small
# (a slow first retry is the main cause of multi-second holes), then grows to a modest cap.
BACKOFF_START = 1.0
BACKOFF_MAX = 15.0
STALL_FACTOR = 3


@dataclass
class Proc:
    popen: subprocess.Popen
    disk_id: int
    container: str
    segment_seconds: int
    last_segment_at: float                 # monotonic of last new segment
    restart_count: int = 0
    backoff: float = BACKOFF_START
    next_retry: float = 0.0                # monotonic gate after a failure
    state: str = STATE_STARTING
    dead_handled: bool = False             # death already recorded (avoid double-count)
    last_disk = None
    last_db_segment_at: object = field(default=None)


class RecorderSupervisor:
    def __init__(self):
        self.procs: dict[int, Proc] = {}
        self.sub_procs: dict[int, Proc] = {}   # P6 R4 — opt-in dual-recording sub stream
        self.warm_procs: dict[int, Proc] = {}  # keep-warm consumers for live transcodes
        self._redis = None
        self._pubsub = None

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def run(self):
        logger.info('recorder supervisor starting')
        self._subscribe()
        try:
            while True:
                try:
                    self.tick()
                except Exception:
                    logger.exception('supervisor tick error')
                    db.session.rollback()
                self._wait()
        finally:
            self.shutdown()

    def _subscribe(self):
        try:
            from server.service.token import get_redis
            self._redis = get_redis()
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            self._pubsub.subscribe(config.RECONCILE_CHANNEL)
        except Exception as e:
            logger.warning('reconcile subscribe failed (polling only): %s', e)

    def _wait(self):
        timeout = config.RECORDER_RECONCILE_SECONDS
        if self._pubsub is not None:
            try:
                self._pubsub.get_message(timeout=timeout)   # wake early on reconcile
                return
            except Exception:
                pass
        time.sleep(timeout)

    def shutdown(self):
        for cid in list(self.warm_procs):
            self._stop_warm(cid)
        for cid in list(self.sub_procs):
            self._stop_sub(cid)
        for cid in list(self.procs):
            self._stop(cid)

    # ── convergence ───────────────────────────────────────────────────────────
    def tick(self):
        desired = self._desired_cameras()
        desired_ids = {c.id for c in desired}

        for cid in list(self.procs):
            if cid not in desired_ids:
                self._stop(cid)

        for cam in desired:
            proc = self.procs.get(cam.id)
            if proc is None:
                self._start(cam)
            elif proc.popen.poll() is not None:
                self._on_dead(cam, proc, 'process_exited')
            else:
                self._maintain(cam, proc)

        # P6 R4 — opt-in dual recording runs in a fully isolated loop so a fault here
        # can never disturb the critical main recorder above.
        try:
            self._tick_subs(desired)
        except Exception:
            logger.exception('sub-recorder tick error')
            db.session.rollback()

        # Keep on-demand live transcodes warm (independent of the recording schedule). Isolated
        # like the sub loop — a fault here can never disturb recording.
        try:
            self._tick_warm()
        except Exception:
            logger.exception('keepwarm tick error')
            db.session.rollback()
        db.session.remove()

    def _desired_cameras(self) -> list[Camera]:
        # Recording is schedule-driven for EVERY enabled camera (no per-camera on/off stop).
        # The P3 weekly schedule is the single authority — it defaults to 'continuous' when
        # unscheduled, so cameras record unconditionally unless a schedule window says 'off'.
        now = utcnow()
        continuous_ids = {c.id for c in Camera.get_all_enabled()}
        # In-progress (end_ts NULL) OR still-open event/manual windows (end_ts in the future,
        # e.g. an event's post-buffer) force recording ON regardless of the weekly schedule —
        # otherwise an event that fires during an 'off' window captures nothing.
        forced_ids = set()
        for rec in db.session.query(Recording).filter(
                Recording.deleted_at.is_(None),
                or_(Recording.end_ts.is_(None), Recording.end_ts > now)).all():
            forced_ids.add(rec.camera_id)
        cams = []
        for cid in continuous_ids | forced_ids:
            cam = db.session.query(Camera).filter(Camera.id == cid, Camera.deleted_at.is_(None)).first()
            if not cam or not cam.is_enabled:
                continue
            if cid not in forced_ids:
                # continuous policy is gated by the P3 weekly schedule (schedule_resolver SSOT)
                try:
                    from server.service import schedule_resolver
                    if schedule_resolver.mode(cid, now) == 'off':
                        continue
                except Exception:
                    pass
            cams.append(cam)
        return cams

    # ── start/stop ────────────────────────────────────────────────────────────
    def _start(self, cam: Camera):
        now = time.monotonic()
        prior = self.procs.get(cam.id)
        if prior and now < prior.next_retry:
            return  # backoff gate

        policy = StoragePolicy.get_for_camera(cam.id)
        stream = self._record_stream(cam)
        if stream is None:
            self._set_health(cam.id, STATE_ERROR, error='no_stream')
            return
        disk = storage_manager.pick_write_disk(cam.id, policy)
        if disk is None:
            self._set_health(cam.id, STATE_ERROR, error='no_writable_disk')
            return

        output_dir = os.path.join(disk.mount_path, str(cam.id))
        os.makedirs(output_dir, exist_ok=True)
        container = (policy.container if policy else 'mpegts')
        seg_seconds = (policy.segment_seconds if policy else 10)
        out_pattern = os.path.join(output_dir, 'seg-%Y%m%d-%H%M%S.' + ffmpeg.segment_ext(container))
        cmd = ffmpeg.build_segment_cmd(ffmpeg.restream_url(stream.go2rtc_name), out_pattern,
                                       seg_seconds, container, video_codec=getattr(stream, 'codec', None))

        try:
            log_path = os.path.join(output_dir, 'ffmpeg.log')
            with open(log_path, 'ab') as log_fh:     # child dups the fd; parent copy closes here
                popen = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log_fh)
        except OSError as e:
            self._set_health(cam.id, STATE_ERROR, error='spawn_failed: %s' % e)
            return

        restart_count = prior.restart_count if prior else 0
        backoff = prior.backoff if prior else BACKOFF_START
        proc = Proc(popen=popen, disk_id=disk.id, container=container, segment_seconds=seg_seconds,
                    last_segment_at=now, restart_count=restart_count, backoff=backoff,
                    state=STATE_STARTING)
        proc.last_disk = disk
        self.procs[cam.id] = proc
        self._set_health(cam.id, STATE_STARTING, pid=popen.pid, restart_count=restart_count)
        logger.info('recorder started camera=%s pid=%s disk=%s', cam.id, popen.pid, disk.name)

    def _stop(self, camera_id: int):
        proc = self.procs.pop(camera_id, None)
        if proc and proc.popen.poll() is None:
            try:
                proc.popen.send_signal(signal.SIGINT)   # flush current segment
                proc.popen.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.popen.kill()
                except OSError:
                    pass
        if proc and proc.last_disk is not None:
            # ffmpeg has exited — index the flushed final segment (normally skipped as
            # "newest = in-progress"); without this the last ~segment before a stop is lost
            try:
                segment_indexer.index_camera_dir(camera_id, proc.last_disk, proc.container,
                                                 include_newest=True)
            except Exception:
                logger.exception('final index error camera=%s', camera_id)
                db.session.rollback()
        self._set_health(camera_id, STATE_STOPPED, pid=None)
        logger.info('recorder stopped camera=%s', camera_id)

    def _on_dead(self, cam: Camera, proc: Proc, reason: str):
        """Record the death once (backoff), then re-spawn when the gate elapses."""
        if not proc.dead_handled:
            proc.restart_count += 1
            proc.backoff = min(proc.backoff * 2, BACKOFF_MAX)
            proc.next_retry = time.monotonic() + proc.backoff
            proc.dead_handled = True
            state = STATE_ERROR if proc.restart_count > 10 else STATE_RECONNECTING
            self._set_health(cam.id, state, pid=None, restart_count=proc.restart_count, error=reason)
            logger.warning('recorder dead camera=%s reason=%s restart=%d backoff=%.1f',
                           cam.id, reason, proc.restart_count, proc.backoff)
            # Index the partial final segment the dead ffmpeg left behind (same as _stop). The
            # respawn may land on a different disk (least_used), which would otherwise orphan
            # this file — it would never be indexed and only reclaimed later by retention.
            if proc.last_disk is not None:
                try:
                    segment_indexer.index_camera_dir(cam.id, proc.last_disk, proc.container,
                                                     include_newest=True)
                except Exception:
                    logger.exception('final index error (dead) camera=%s', cam.id)
                    db.session.rollback()
        if time.monotonic() >= proc.next_retry:
            self._start(cam)   # re-spawn (self-gated; carries restart_count/backoff)

    def _maintain(self, cam: Camera, proc: Proc):
        disk = proc.last_disk
        if disk is not None:
            try:
                count = segment_indexer.index_camera_dir(cam.id, disk, proc.container)
                if count:
                    proc.last_segment_at = time.monotonic()
                    proc.last_db_segment_at = utcnow()
                    proc.backoff = BACKOFF_START
            except Exception:
                logger.exception('index error camera=%s', cam.id)
                db.session.rollback()

        # stall detection
        stall_limit = STALL_FACTOR * proc.segment_seconds
        if time.monotonic() - proc.last_segment_at > stall_limit + 8:
            logger.warning('recorder stalled camera=%s — restarting', cam.id)
            try:
                proc.popen.kill()
            except OSError:
                pass
            self._on_dead(cam, proc, 'stalled')
            return

        proc.state = STATE_RECORDING
        self._set_health(cam.id, STATE_RECORDING, pid=proc.popen.pid,
                         last_segment_at=proc.last_db_segment_at, restart_count=proc.restart_count)

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _record_stream(cam: Camera):
        streams = cam.streams
        if not streams:
            return None
        return (next((s for s in streams if s.is_default_full), None)
                or next((s for s in streams if s.role == 'main'), None)
                or streams[0])

    @staticmethod
    def _set_health(camera_id, state, pid=None, last_segment_at=None, restart_count=None, error=None):
        fields = {'state': state}
        if pid is not None or state == STATE_STOPPED:
            fields['pid'] = pid
        if last_segment_at is not None:
            fields['last_segment_at'] = last_segment_at
        if restart_count is not None:
            fields['restart_count'] = restart_count
        if error is not None:
            fields['last_error'] = error[:1000]
        try:
            RecorderHealth.upsert(camera_id, **fields)
        except Exception:
            db.session.rollback()

    # ── P6 R4 dual recording (isolated sub-stream) ──────────────────────────────
    # Opt-in (camera.dual_recording). Records the secondary stream to {disk}/{id}/sub/
    # with stream_role='sub'. Deliberately mirrors the main loop but writes NO recorder
    # health (would clobber the primary) and swallows all faults, so enabling it cannot
    # regress the main recording path.
    def _sub_stream(self, cam: Camera):
        """Secondary stream to dual-record. Honours the per-camera `dual_record_stream` role
        choice when set; otherwise prefers role='sub', then the default-live stream (if
        distinct from main), then any non-main stream. None if only the main stream exists."""
        streams = cam.streams
        if not streams or len(streams) < 2:
            return None
        main = self._record_stream(cam)
        main_id = main.id if main else None
        chosen = getattr(cam, 'dual_record_stream', None)
        if chosen:
            picked = next((s for s in streams if s.role == chosen), None)
            if picked is not None:
                return picked
        return (next((s for s in streams if s.role == 'sub'), None)
                or next((s for s in streams if s.is_default_live and s.id != main_id), None)
                or next((s for s in streams if s.id != main_id), None))

    def _tick_subs(self, desired: list[Camera]):
        dual_ids = {c.id for c in desired if getattr(c, 'dual_recording', False)}
        for cid in list(self.sub_procs):
            if cid not in dual_ids:
                self._stop_sub(cid)
        by_id = {c.id: c for c in desired}
        for cid in dual_ids:
            cam = by_id[cid]
            proc = self.sub_procs.get(cid)
            if proc is None:
                self._start_sub(cam)
            elif proc.popen.poll() is not None:
                self._on_dead_sub(cam, proc)
            else:
                self._maintain_sub(cam, proc)

    def _start_sub(self, cam: Camera):
        now = time.monotonic()
        prior = self.sub_procs.get(cam.id)
        if prior and now < prior.next_retry:
            return  # backoff gate
        stream = self._sub_stream(cam)
        if stream is None:
            return  # no second stream — skip silently (main recording unaffected)
        policy = StoragePolicy.get_for_camera(cam.id)
        disk = storage_manager.pick_write_disk(cam.id, policy)
        if disk is None:
            return

        output_dir = os.path.join(disk.mount_path, str(cam.id), 'sub')
        os.makedirs(output_dir, exist_ok=True)
        container = (policy.container if policy else 'mpegts')
        seg_seconds = (policy.segment_seconds if policy else 10)
        out_pattern = os.path.join(output_dir, 'seg-%Y%m%d-%H%M%S.' + ffmpeg.segment_ext(container))
        cmd = ffmpeg.build_segment_cmd(ffmpeg.restream_url(stream.go2rtc_name), out_pattern,
                                       seg_seconds, container, video_codec=getattr(stream, 'codec', None))

        try:
            with open(os.path.join(output_dir, 'ffmpeg.log'), 'ab') as log_fh:
                popen = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log_fh)
        except OSError as e:
            logger.warning('sub recorder spawn failed camera=%s: %s', cam.id, e)
            return

        restart_count = prior.restart_count if prior else 0
        backoff = prior.backoff if prior else BACKOFF_START
        proc = Proc(popen=popen, disk_id=disk.id, container=container, segment_seconds=seg_seconds,
                    last_segment_at=now, restart_count=restart_count, backoff=backoff,
                    state=STATE_STARTING)
        proc.last_disk = disk
        self.sub_procs[cam.id] = proc
        logger.info('sub recorder started camera=%s pid=%s disk=%s', cam.id, popen.pid, disk.name)

    def _stop_sub(self, camera_id: int):
        proc = self.sub_procs.pop(camera_id, None)
        if proc and proc.popen.poll() is None:
            try:
                proc.popen.send_signal(signal.SIGINT)   # flush current segment
                proc.popen.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.popen.kill()
                except OSError:
                    pass
        if proc and proc.last_disk is not None:
            try:
                segment_indexer.index_camera_dir(camera_id, proc.last_disk, proc.container,
                                                 subdir='sub', stream_role='sub',
                                                 include_newest=True)
            except Exception:
                db.session.rollback()
        logger.info('sub recorder stopped camera=%s', camera_id)

    def _on_dead_sub(self, cam: Camera, proc: Proc):
        if not proc.dead_handled:
            proc.restart_count += 1
            proc.backoff = min(proc.backoff * 2, BACKOFF_MAX)
            proc.next_retry = time.monotonic() + proc.backoff
            proc.dead_handled = True
            logger.warning('sub recorder dead camera=%s restart=%d backoff=%.1f',
                           cam.id, proc.restart_count, proc.backoff)
            if proc.last_disk is not None:
                try:
                    segment_indexer.index_camera_dir(cam.id, proc.last_disk, proc.container,
                                                     subdir='sub', stream_role='sub',
                                                     include_newest=True)
                except Exception:
                    db.session.rollback()
        if time.monotonic() >= proc.next_retry:
            self._start_sub(cam)   # re-spawn (self-gated; carries restart_count/backoff)

    def _maintain_sub(self, cam: Camera, proc: Proc):
        disk = proc.last_disk
        if disk is not None:
            try:
                count = segment_indexer.index_camera_dir(
                    cam.id, disk, proc.container, subdir='sub', stream_role='sub')
                if count:
                    proc.last_segment_at = time.monotonic()
                    proc.backoff = BACKOFF_START
            except Exception:
                logger.exception('sub index error camera=%s', cam.id)
                db.session.rollback()

        stall_limit = STALL_FACTOR * proc.segment_seconds
        if time.monotonic() - proc.last_segment_at > stall_limit + 8:
            logger.warning('sub recorder stalled camera=%s — restarting', cam.id)
            try:
                proc.popen.kill()
            except OSError:
                pass
            self._on_dead_sub(cam, proc)

    # ── keep-warm live transcode consumers ──────────────────────────────────────
    # go2rtc runs an on-demand ffmpeg transcode (H.265→H.264) for live_transcode cameras and
    # stops it when the last viewer leaves, so the next viewer cold-starts it and waits for a
    # keyframe (visible breakup). We hold one throwaway consumer open per such camera to keep
    # the transcode running, so viewers join warm. Runs for ALL enabled live_transcode cameras
    # regardless of the recording schedule (live is viewable even when recording is off), and
    # is fully isolated — a fault here never disturbs recording.
    @staticmethod
    def _warm_stream(cam: Camera):
        """The live stream go2rtc transcodes (default-live that is H.265 or force-transcoded).
        None otherwise — a copy stream cold-starts cheaply and needs no keep-warm."""
        from server.service.go2rtc_sync import live_transcode_enabled
        stream = next((s for s in cam.streams
                       if getattr(s, 'is_default_live', False) and s.enabled), None)
        if stream is None:
            return None
        return stream if live_transcode_enabled(cam, stream) else None

    def _tick_warm(self):
        warm: dict[int, Camera] = {}
        for cam in Camera.get_all_enabled():
            if self._warm_stream(cam) is not None:
                warm[cam.id] = cam
        for cid in list(self.warm_procs):
            if cid not in warm:
                self._stop_warm(cid)
        for cid, cam in warm.items():
            proc = self.warm_procs.get(cid)
            if proc is None:
                self._start_warm(cam)
            elif proc.popen.poll() is not None:
                self._on_dead_warm(cam, proc)

    def _start_warm(self, cam: Camera):
        now = time.monotonic()
        prior = self.warm_procs.get(cam.id)
        if prior and now < prior.next_retry:
            return  # backoff gate
        stream = self._warm_stream(cam)
        if stream is None:
            return
        cmd = ffmpeg.build_keepwarm_cmd(ffmpeg.restream_url(stream.go2rtc_name))
        try:
            popen = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            logger.warning('keepwarm spawn failed camera=%s: %s', cam.id, e)
            return
        restart_count = prior.restart_count if prior else 0
        backoff = prior.backoff if prior else BACKOFF_START
        proc = Proc(popen=popen, disk_id=0, container='', segment_seconds=10,
                    last_segment_at=now, restart_count=restart_count, backoff=backoff,
                    state=STATE_STARTING)
        self.warm_procs[cam.id] = proc
        logger.info('keepwarm started camera=%s pid=%s stream=%s', cam.id, popen.pid, stream.go2rtc_name)

    def _stop_warm(self, camera_id: int):
        proc = self.warm_procs.pop(camera_id, None)
        if proc and proc.popen.poll() is None:
            try:
                proc.popen.send_signal(signal.SIGINT)
                proc.popen.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.popen.kill()
                except OSError:
                    pass
        logger.info('keepwarm stopped camera=%s', camera_id)

    def _on_dead_warm(self, cam: Camera, proc: Proc):
        if not proc.dead_handled:
            proc.restart_count += 1
            proc.backoff = min(proc.backoff * 2, BACKOFF_MAX)
            proc.next_retry = time.monotonic() + proc.backoff
            proc.dead_handled = True
            logger.debug('keepwarm dead camera=%s restart=%d backoff=%.1f',
                         cam.id, proc.restart_count, proc.backoff)
        if time.monotonic() >= proc.next_retry:
            self._start_warm(cam)   # re-spawn (self-gated; carries restart_count/backoff)
