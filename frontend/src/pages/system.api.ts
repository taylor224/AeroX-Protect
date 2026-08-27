import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

/** Native-install (Windows launcher) self-update API. Docker deployments answer
 *  501 platform_unsupported on every route — callers hide the feature then. */

export interface UpdateCheck {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
  /** Release requires a newer launcher — must run the full installer instead. */
  needs_installer?: boolean;
  notes_url?: string | null;
  installer_url?: string | null;
  checked_at?: string;
}

export type UpdatePhase =
  | 'idle' | 'checking' | 'precheck' | 'downloading' | 'verifying' | 'extracting'
  | 'backup_db' | 'stopping_app' | 'migrating' | 'swapping' | 'starting' | 'health'
  | 'done' | 'rollback' | 'restoring' | 'failed';

export interface UpdateStatus {
  phase: UpdatePhase;
  percent: number;
  message?: string | null;
  error?: string | null;
  from?: string | null;
  to?: string | null;
}

export interface ApplyResult {
  ticket: string;
  expires_in: number;
  poll_url: string;
}

export async function checkUpdate(force = false): Promise<UpdateCheck> {
  const { data } = await api.get<ApiResponse<UpdateCheck>>(
    `/system/update/check${force ? '?force=1' : ''}`,
  );
  return data.data as UpdateCheck;
}

export async function applyUpdate(version?: string | null): Promise<ApplyResult> {
  const { data } = await api.post<ApiResponse<ApplyResult>>('/system/update/apply', { version });
  return data.data as ApplyResult;
}

/**
 * Poll the launcher's update progress THROUGH the reverse proxy (/updater/* →
 * launcher loopback API) with the HMAC ticket from applyUpdate. Deliberately a
 * bare fetch, NOT the axios instance: mid-update the backend is down, and the
 * axios 401-refresh interceptor must not fire on a dead backend.
 */
export async function pollUpdaterStatus(pollUrl: string, ticket: string): Promise<UpdateStatus> {
  const res = await fetch(`${pollUrl}?ticket=${encodeURIComponent(ticket)}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`updater ${res.status}`);
  const body = (await res.json()) as { data?: UpdateStatus } & UpdateStatus;
  return (body.data ?? body) as UpdateStatus;
}

/** Version reported by the (unauthenticated) healthz probe — used to confirm the
 *  new backend is up after an update. Bare fetch for the same reason as above. */
export async function fetchHealthzVersion(): Promise<string | null> {
  try {
    const res = await fetch('/api/v1/healthz', { cache: 'no-store' });
    if (!res.ok) return null;
    const body = (await res.json()) as { data?: { version?: string }; version?: string };
    return body.data?.version ?? body.version ?? null;
  } catch {
    return null;
  }
}
