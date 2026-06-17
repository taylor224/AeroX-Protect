// P5 (automation / monitors / notifications / external API) DTOs.

export type TriggerType = 'event' | 'object' | 'schedule' | 'manual' | 'system_event' | 'incoming_webhook';
export type ActionType =
  | 'speaker' | 'io' | 'webhook' | 'push' | 'email' | 'sms' | 'camera_enable' | 'camera_disable';

export interface RuleAction {
  type: ActionType;
  target_id?: number | string | null;
  params?: Record<string, unknown>;
  delay_ms?: number;
  continue_on_error?: boolean;
}

export interface Rule {
  id: string;
  uuid: string;
  name: string;
  description: string | null;
  enabled: boolean;
  priority: number;
  stop_on_match: boolean;
  trigger_type: TriggerType;
  trigger: Record<string, unknown>;
  condition: Record<string, unknown>;
  actions: RuleAction[];
  cooldown_s: number;
  debounce_s: number;
  dedup_scope: string;
  max_per_hour: number | null;
  incoming_token?: string | null;
  last_triggered_ts: number | null;
  created_at: number | null;
}

export interface RuleExecution {
  id: string;
  rule_id: string;
  trigger_type: string;
  event_id: string | null;
  camera_id: string | null;
  matched: boolean;
  skip_reason: string | null;
  action_results: { type: string; status: string; error?: string }[] | null;
  status: string;
  created_at: number | null;
  duration_ms: number | null;
}

export interface ActionTarget {
  id: string;
  uuid: string;
  type: 'speaker' | 'io' | 'email';
  name: string;
  vendor: string | null;
  protocol: string;
  host: string | null;
  port: number | null;
  config: Record<string, unknown>;
  camera_id: string | null;
  enabled: boolean;
  status: string;
  has_credentials: boolean;
}

export interface WebhookEndpoint {
  id: string;
  uuid: string;
  name: string;
  url: string;
  has_secret: boolean;
  timeout_ms: number;
  max_retries: number;
  verify_tls: boolean;
  purpose: string;
  enabled: boolean;
  last_status: number | null;
  consecutive_failures: number;
}

export interface Monitor {
  id: string;
  uuid: string;
  name: string;
  dashboard_id: string;
  dashboard_uuid?: string | null;
  status: 'unpaired' | 'pending' | 'paired' | 'revoked';
  paired_at: number | null;
  last_seen_at: number | null;
  device_label: string | null;
  settings: Record<string, unknown> | null;
  enabled: boolean;
}

export interface NotificationSubscription {
  id: string;
  channel: 'push' | 'email' | 'webhook' | 'inapp';
  event_types: string[] | null;
  camera_ids: string[] | null;
  object_classes: string[] | null;
  min_priority: string;
  muted: boolean;
  muted_until: number | null;
  batch_window_s: number;
  quiet_hours: { ranges?: { start: string; end: string }[]; allow_critical?: boolean } | null;
  enabled: boolean;
}

export interface AppNotification {
  id: string;
  event_id: string | null;
  camera_id: string | null;
  type: string;
  priority: string;
  title: string;
  body: string | null;
  deeplink: string | null;
  read_at: number | null;
  created_at: number | null;
}

export interface ApiToken {
  id: string;
  uuid: string;
  name: string;
  token_prefix: string;
  scopes: Record<string, string[]>;
  camera_ids: string[] | null;
  expires_at: number | null;
  last_used_at: number | null;
  revoked_at: number | null;
  created_at: number | null;
}

export const EVENT_TYPES = ['motion', 'line_crossing', 'intrusion', 'tamper', 'object',
  'face', 'doorbell_call', 'audio_class', 'loitering'] as const;
export const OBJECT_CLASSES = ['person', 'car', 'truck', 'bus', 'dog', 'cat'] as const;
// action types offered in the rule wizard (speaker/io need device targets configured
// elsewhere and are kept only for back-compat — not surfaced in the builder)
export const ACTION_TYPES: ActionType[] = ['webhook', 'push', 'email', 'sms',
  'camera_enable', 'camera_disable'];

// system_event trigger options (device/camera lifecycle — distinct from detection events)
export const SYSTEM_EVENTS = ['camera_online', 'camera_offline', 'camera_config_changed',
  'camera_motion', 'doorbell_ring', 'io_input_on', 'io_input_off', 'device_online', 'device_offline'] as const;
