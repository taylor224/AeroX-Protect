export type CameraStatus = 'online' | 'offline' | 'unauthorized' | 'error' | 'unknown';

export interface Stream {
  role: 'main' | 'sub' | 'third';
  codec: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  bitrate_kbps: number | null;
  audio_codec: string | null;
  rtsp_path: string | null;
  go2rtc_name: string;
  is_default_live: boolean;
  is_default_full: boolean;
  enabled: boolean;
}

export interface Camera {
  id: string;
  uuid: string;
  name: string;
  vendor: string;
  model: string | null;
  firmware: string | null;
  serial: string | null;
  driver: string;
  host: string;
  onvif_port: number | null;
  http_port: number | null;
  rtsp_port: number | null;
  rtsp_transport?: string; // 'auto' | 'tcp' | 'udp'
  use_https: boolean;
  channel: number;
  has_credentials: boolean;
  ptz_supported: boolean;
  audio_supported: boolean;
  two_way_audio: boolean;
  live_transcode?: boolean;
  fisheye?: boolean;
  fisheye_params?: { cx?: number; cy?: number; radius?: number; lens_fov?: number; mode?: string } | null;
  dual_recording?: boolean;
  dual_record_stream?: string | null;
  edge_recording?: boolean;
  edge_auto_import?: boolean;
  ai_features?: Record<string, boolean>;
  status: CameraStatus;
  last_seen_at: number | null;
  last_error: string | null;
  is_enabled: boolean;
  created_at: number | null;
  updated_at: number | null;
  streams?: Stream[];
}

export interface ProbeResult {
  host: string;
  vendor: string;
  driver: string;
  model: string | null;
  firmware: string | null;
  serial: string | null;
  ptz_supported: boolean;
  audio_supported: boolean;
  snapshot_url: string | null;
  streams: Partial<Stream>[];
  capabilities: unknown;
  reachable: { onvif?: boolean; vendor_api?: boolean; rtsp?: boolean | null };
  status?: string;
  error?: string;
}

export interface DiscoveredDevice {
  host: string;
  xaddrs: string[];
  name: string | null;
  manufacturer: string | null;
  model: string | null;
  hardware: string | null;
  source?: string; // 'onvif' | 'sadp'
  http_port?: string | number | null;
}

export type RatioMode = 'fit' | 'stretch' | 'crop';

export interface LayoutCell {
  i: string;
  camera_uuid?: string | null;
  stream_role?: 'main' | 'sub';
  x: number;
  y: number;
  w: number;
  h: number;
  ratio_mode?: RatioMode;
}

export interface DashboardLayout {
  version: number;
  grid: { cols: number; rows: number; gap: number };
  ratio_mode?: RatioMode;
  show_names?: boolean; // always show camera name labels (saved with the dashboard)
  cells: LayoutCell[];
  name?: string;                  // page name (multi-page dashboards)
  // multi-page: a dashboard can hold several grid pages that auto-rotate (sequence).
  // legacy single-page dashboards omit `pages` and store grid/cells at the top level.
  pages?: DashboardLayout[];
  sequence?: { enabled: boolean; dwell_s: number };
}

export interface DashboardSummary {
  uuid: string;
  name: string;
  description: string | null;
  owner_id: string;
  is_shared: boolean;
  default_ratio_mode: RatioMode;
  access?: 'view' | 'edit' | null;
  created_at: number | null;
  updated_at: number | null;
}

export interface DashboardDetail extends DashboardSummary {
  layout: DashboardLayout;
  acl?: { user_id: string; access: 'view' | 'edit' }[];
}

export interface PtzPreset {
  token: string;
  name: string;
}
