// P3 (events / schedule / policy / timelapse) DTOs — mirror server to_dict shapes.

export interface AxpEvent {
  id: string;
  camera_id: string; // numeric camera id (string)
  type: string;
  subtype: string | null;
  state: number; // 0 active, 1 ended, 2 pulse
  start_ts: number;
  end_ts: number | null;
  duration_ms: number | null;
  score: number | null;
  source: string;
  channel: number | null;
  region: unknown;
  recording_id: string | null;
  policy_action: string | null;
  created_at: number | null;
}

export interface EventListResult {
  count: number;
  items: AxpEvent[];
}

export interface EventMarker {
  ts: number;
  type: string;
  count: number;
  top_score: number | null;
  event_id: string;
  /** Set when this event has a playable clip; null for notify-only events (e.g. video_loss). */
  recording_id: string | null;
}

export interface EventTimelineData {
  markers: EventMarker[];
  coverage: { start: number; end: number }[];
}

export interface OverlayShape {
  kind: string;
  pts: [number, number][];
}

export interface EventOverlay {
  shapes: OverlayShape[];
  w: number;
  h: number;
  ts_offset_ms: number;
}

export type PolicyAction = 'record' | 'discard' | 'timelapse' | 'notify_only';

export interface EventPolicy {
  id: string;
  camera_id: string | null; // null = global default
  event_type: string;
  subtype: string | null;
  action: PolicyAction;
  pre_buffer_s: number;
  post_buffer_s: number;
  cooldown_s: number;
  min_score: number | null;
  retention_class: string | null;
  notify: boolean;
  enabled: boolean;
}

export type ScheduleMode = 'continuous' | 'event' | 'motion_only' | 'off';

export interface ScheduleRule {
  id?: string;
  name?: string | null;
  day_of_week: number; // 0=Mon..6=Sun (KST)
  start_min: number; // 0..1439
  end_min: number; // 1..1440
  mode: ScheduleMode;
  priority: number;
  timezone?: string;
  group_uuid?: string | null;
}

export type TimelapseStatus = 'queued' | 'running' | 'done' | 'failed' | 'canceled';

export interface TimelapseJob {
  id: string;
  camera_id: string;
  range_start_ts: number;
  range_end_ts: number;
  source: string;
  speed_factor: number;
  status: TimelapseStatus;
  progress: number;
  output_size: number | null;
  error: string | null;
  created_at: number | null;
}

export const EVENT_TYPES = [
  'motion',
  'line_crossing',
  'intrusion',
  'region_enter',
  'region_exit',
  'tamper',
  'audio',
  'io',
  'video_loss',
  'object',
] as const;

export const SCHEDULE_MODES: ScheduleMode[] = ['continuous', 'event', 'motion_only', 'off'];
export const POLICY_ACTIONS: PolicyAction[] = ['record', 'discard', 'timelapse', 'notify_only'];
