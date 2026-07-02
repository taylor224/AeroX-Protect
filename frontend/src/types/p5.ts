// P5 (monitors / device targets / api tokens) DTOs. Rule + subscription-notification
// DTOs were retired — visual flows (types/flow.ts) are the automation surface.

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
