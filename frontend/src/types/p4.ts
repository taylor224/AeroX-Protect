// P4 (AI detection) DTOs — mirror server to_dict / search shapes.

export interface DetectionGroup {
  group: 'clip' | 'track' | 'raw';
  camera_id: string;
  track_id?: string | null;
  start_ts: number;
  end_ts: number;
  labels: string[];
  count: number;
  track_count?: number;
  top_confidence: number;
  rep_detection_id: string;
  segment_id: string | null;
  bbox: number[];
}

export interface DetectionSearchResult {
  count: number;
  group: string;
  items: DetectionGroup[];
}

export interface OverlayTrack {
  track_id: string;
  label: string;
  points: { ts: number; bbox: number[]; conf: number }[];
}

export interface DetectionOverlayData {
  w: number;
  h: number;
  tracks: OverlayTrack[];
}

export interface DetectionMarker {
  ts: number;
  label: string;
  count: number;
  top_conf: number;
  track_id: string | null;
  detection_id: string;
}

export interface DetectionTimelineData {
  markers: DetectionMarker[];
  coverage: { start: number; end: number }[];
}

export type ZoneKind = 'include' | 'ignore';

export interface DetectionZone {
  id: string;
  camera_id: string;
  name: string;
  kind: ZoneKind;
  polygon: [number, number][];
  label_filter: string[] | null;
  color: string | null;
  enabled: boolean;
  priority: number;
}

export interface ObjectTrigger {
  id: string;
  camera_id: string | null;
  name: string;
  labels: string[];
  zone_id: string | null;
  min_confidence: number;
  min_dwell_ms: number;
  require_zone_entry: boolean;
  min_count: number;
  cooldown_s: number;
  debounce_per_track: boolean;
  event_subtype: string | null;
  action_hint: string | null;
  notify: boolean;
  enabled: boolean;
}

export interface AiNode {
  id: string;
  uuid: string;
  name: string;
  kind: 'builtin' | 'remote';
  status: 'online' | 'degraded' | 'offline' | 'draining' | 'disabled';
  enabled: boolean;
  gpu: boolean;
  gpu_name: string | null;
  capacity: number;
  assigned_count: number;
  version: string | null;
  last_heartbeat_ts: number | null;
  last_error: string | null;
}

export interface AiAssignment {
  id: string;
  camera_id: string;
  node_id: string;
  node_name: string | null;
  state: string;
  model: string | null;
  target_fps: number | null;
  epoch: number;
  last_report_ts: number | null;
}

export interface AiSettings {
  id: string;
  camera_id: string | null;
  detection_enabled: boolean;
  gpu_enabled: boolean;
  model: string;
  target_fps: number;
  imgsz: number;
  min_confidence: number;
  labels: string[] | null;
  clip_enabled: boolean;
  live_overlay_enabled: boolean;
  store_crops: boolean;
  retention_days: number;
  sample_interval_ms: number;
  hwaccel?: string;
  audio_enabled?: boolean;
  audio_threshold?: number;
}

export const DETECTION_LABELS = ['person', 'car', 'truck', 'bus', 'motorcycle', 'bicycle', 'dog', 'cat'] as const;
// Ultralytics model zoo (auto-downloaded by name at warmup). YOLO11 is the current
// flagship (Oct 2024); v10/v9/v8 kept for choice. n<s<m = faster→more accurate.
export const YOLO_MODELS = [
  'yolo11n', 'yolo11s', 'yolo11m',
  'yolov10n', 'yolov10s',
  'yolov9t', 'yolov9s',
  'yolov8n', 'yolov8s', 'yolov8m',
] as const;
