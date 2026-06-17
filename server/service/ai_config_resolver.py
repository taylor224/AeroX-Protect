"""Effective per-camera AI config (global ← camera override) + CameraJobSpec generation
(PLAN P4 §5.3). The detector node (builtin or remote) is driven entirely by the JobSpec —
no camera config lives in the worker. GPU toggle is global-only authority."""
import config
from server.model.ai_settings import DEFAULT_LABELS, AiSettings
from server.model.camera import Camera
from server.model.detection_assignment import DetectionAssignment
from server.model.detection_zone import KIND_INCLUDE, DetectionZone
from server.model.object_trigger import ObjectTrigger
from server.model.stream import Stream

_MERGE = ('detection_enabled', 'model', 'target_fps', 'imgsz', 'min_confidence', 'labels',
          'clip_enabled', 'live_overlay_enabled', 'store_crops', 'sample_interval_ms')


def effective_settings(camera_id: int) -> dict:
    """Global defaults overlaid by the camera's coherent override row (if any).
    gpu_enabled is always taken from the global row (camera can't override GPU)."""
    g = AiSettings.ensure_global()
    src = AiSettings.get_for_camera(camera_id) or g
    eff = {f: getattr(src, f) for f in _MERGE}
    eff['gpu_enabled'] = bool(g.gpu_enabled)
    return eff


def enabled_camera_ids() -> list[int]:
    """Enabled cameras whose effective detection_enabled is true."""
    out = []
    for cam in Camera.get_all_enabled():
        if effective_settings(cam.id)['detection_enabled']:
            out.append(cam.id)
    return out


def _main_stream(camera_id: int):
    streams = Stream.get_by_camera(camera_id)
    for s in streams:
        if s.role == 'main':
            return s
    return streams[0] if streams else None


def camera_job_spec(camera_id: int) -> dict | None:
    """Server→node work order for one camera (PLAN §5.2 CameraJobSpec). None if the camera
    has no main stream or detection is disabled."""
    cam = Camera.get_by_id(camera_id)
    if not cam:
        return None
    eff = effective_settings(camera_id)
    if not eff['detection_enabled']:
        return None
    main = _main_stream(camera_id)
    if not main:
        return None

    assignment = DetectionAssignment.get_for_camera(camera_id)
    epoch = assignment.epoch if assignment else 0

    labels = list(eff['labels'] or DEFAULT_LABELS)
    for t in ObjectTrigger.get_candidates(camera_id):     # union trigger-needed classes
        for lab in (t.labels or []):
            if lab not in labels:
                labels.append(lab)

    zones = {'include': [], 'ignore': []}
    for z in DetectionZone.get_for_camera(camera_id):
        bucket = 'include' if z.kind == KIND_INCLUDE else 'ignore'
        zones[bucket].append(z.polygon)

    return {
        'camera_id': camera_id,
        'go2rtc_name': main.go2rtc_name,
        'epoch': epoch,
        'model': (assignment.model if assignment and assignment.model else eff['model']),
        'imgsz': eff['imgsz'],
        'target_fps': (assignment.target_fps if assignment and assignment.target_fps else eff['target_fps']),
        'min_confidence': eff['min_confidence'],
        'labels': labels,
        'zones': zones,
        'clip_enabled': bool(eff['clip_enabled']),
        'live_overlay': bool(eff['live_overlay_enabled']),
        'sample_interval_ms': eff['sample_interval_ms'],
        'rtsp_url': '%s/%s' % (config.GO2RTC_RTSP, main.go2rtc_name),
    }
