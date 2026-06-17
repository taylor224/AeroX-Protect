export interface Segment {
  id: string;
  camera_id: string;
  start_ts: number;
  end_ts: number;
  duration_ms: number;
  size_bytes: number;
  container: string;
  video_codec: string | null;
  reason: string;
  storage_tier: string;
}

export interface TimeRange {
  start: number;
  end: number;
}

export interface TimelineData {
  ranges: TimeRange[];
  gaps: TimeRange[];
  events: unknown[];
  objects: unknown[];
}

export interface RecorderHealth {
  state: 'stopped' | 'starting' | 'recording' | 'reconnecting' | 'error';
  pid: number | null;
  last_segment_at: number | null;
  restart_count: number;
  last_error: string | null;
}

export interface RecordingStatus {
  camera_uuid: string;
  record_mode: 'off' | 'continuous';
  health: RecorderHealth;
  active_manual: { id: string; start_ts: number } | null;
}

export interface Disk {
  id: string;
  name: string;
  mount_path: string;
  role: 'system' | 'cache' | 'record';
  enabled: boolean;
  reserved_free_bytes: number;
  total_bytes: number;
  free_bytes: number;
  used_bytes: number;
  usage_percent: number;
  weight: number;
  status: string;
  health?: 'ok' | 'warning' | 'critical';
}

export interface DiscoverCandidate {
  mount_path: string;
  device: string | null;
  total_bytes: number;
  free_bytes: number;
  fstype: string | null;
}

export interface PoolSummary {
  roles: Record<string, { count: number; total_bytes: number; free_bytes: number; reserved_bytes: number }>;
  record_total_bytes: number;
  warnings: string[];
  disks: Disk[];
}

export interface StoragePolicy {
  id: string;
  camera_id: string | null;
  segment_seconds: number;
  container: string;
  record_mode: 'off' | 'continuous';
  balance_strategy: string;
  retention_days: number | null;
  retention_max_bytes: number | null;
  over_capacity_policy: 'delete_oldest' | 'stop_recording' | 'warn_only';
  cache_buffer_seconds: number;
  event_retention_days?: number | null;
  warnings?: string[];
}

export interface ExportJob {
  id: string;
  camera_id: string;
  start_ts: number;
  end_ts: number;
  mode: 'copy' | 'transcode';
  status: 'queued' | 'processing' | 'done' | 'failed' | 'expired';
  progress: number;
  output_size_bytes: number | null;
  error_message: string | null;
  download_token?: string;
  created_at: number | null;
}
