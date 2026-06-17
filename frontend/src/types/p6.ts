// Phase 6 — advanced features (Wave 1: feature flags + bookmarks).

export interface FeatureFlag {
  key: string;
  enabled: boolean;
  scope: string;
  camera_id: string | null;
  value: unknown;
  description: string | null;
}

export interface FeatureFlagsResponse {
  items: FeatureFlag[];
  enabled: Record<string, boolean>;
}

export interface Bookmark {
  id: string;
  camera_id: string;
  start_ts: number;
  end_ts: number | null;
  label: string;
  color: string | null;
  note: string | null;
  recording_id: string | null;
  event_id: string | null;
  lock_retention: boolean;
  created_by_id: string | null;
  created_at: number;
}

export interface BookmarkInput {
  camera_uuid: string;
  start_ts: number;
  end_ts?: number | null;
  label: string;
  color?: string | null;
  note?: string | null;
  recording_id?: string | null;
  event_id?: string | null;
  lock_retention?: boolean;
}

// ── M1 batch camera add ───────────────────────────────────────────────────────
export interface BatchAddResultItem {
  index: number;
  host: string;
  status: 'created' | 'failed';
  uuid?: string;
  name?: string;
  error?: string;
}

export interface BatchAddResult {
  created: number;
  failed: number;
  results: BatchAddResultItem[];
}

// ── R1 share links ────────────────────────────────────────────────────────────
export interface ShareLink {
  id: string;
  kind: 'clip' | 'event';
  camera_id: string;
  target_ref: string | null;
  range_start: number | null;
  range_end: number | null;
  label: string | null;
  has_password: boolean;
  watermark: boolean;
  max_views: number | null;
  view_count: number;
  expires_at: number | null;
  revoked_at: number | null;
  status: string;
  created_at: number;
}

export interface ShareLinkCreated extends ShareLink {
  token: string; // shown once
  path: string;
}

export interface ShareSegment {
  id: string;
  start_ts: number;
  end_ts: number;
  duration_ms: number;
}

// ── A2/A3 counting + loitering ────────────────────────────────────────────────
export interface CountingLine {
  id: string;
  camera_id: string;
  name: string;
  kind: 'line' | 'region';
  geometry: [number, number][];
  class_filter: string[] | null;
  direction_labels: { in?: string; out?: string } | null;
  loiter_threshold_s: number | null;
  occupancy_threshold: number | null;
  enabled: boolean;
}

export interface CountingStat {
  line_id: string;
  bucket_ts: number;
  in_count: number;
  out_count: number;
  occupancy: number;
  label: string | null;
}

// ── L6 maps ───────────────────────────────────────────────────────────────────
export interface MapMarker {
  id?: string;
  camera_id: string;
  x: number; // geo: lng | floorplan: 0–1
  y: number; // geo: lat | floorplan: 0–1
  heading?: number | null;
  label?: string | null;
}

export interface SiteMap {
  id: string;
  name: string;
  kind: 'geo' | 'floorplan';
  image_url: string | null;
  config: { center_lat?: number; center_lng?: number; zoom?: number; w?: number; h?: number } | null;
  enabled: boolean;
  markers?: MapMarker[];
}

// ── M2 archiving ──────────────────────────────────────────────────────────────
export interface ArchiveTarget {
  id: string;
  name: string;
  type: 's3' | 'smb' | 'local';
  config: Record<string, unknown> | null;
  has_secrets: boolean;
  enabled: boolean;
}

export interface ArchiveJob {
  id: string;
  target_id: string;
  source_type: string;
  source_ref: string;
  status: string;
  progress: number;
  bytes_total: number;
  bytes_done: number;
  manifest: { count?: number } | null;
  error_message: string | null;
  created_at: number;
}

// ── L2 privacy masks ──────────────────────────────────────────────────────────
export interface PrivacyMask {
  id: string;
  camera_id: string;
  name: string;
  polygon: [number, number][];
  mode: string;
  enabled: boolean;
}

export interface ShareView {
  status: 'ok' | 'password_required' | 'expired' | 'revoked' | 'exhausted';
  kind?: 'clip' | 'event';
  label?: string | null;
  camera_name?: string | null;
  range_start?: number | null;
  range_end?: number | null;
  watermark?: boolean;
  is_event?: boolean;
  has_password?: boolean;
  segments?: ShareSegment[];
}
