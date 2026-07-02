import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { ActionTarget, ApiToken, Monitor } from '@/types/p5';

// ── action targets (device picker for flow speaker/io nodes) ─────────────────
export async function listTargets(): Promise<ActionTarget[]> {
  const { data } = await api.get<ApiResponse<{ items: ActionTarget[] }>>('/action-targets');
  return data.data?.items ?? [];
}

// ── monitors ─────────────────────────────────────────────────────────────────
export async function listMonitors(): Promise<Monitor[]> {
  const { data } = await api.get<ApiResponse<{ items: Monitor[] }>>('/monitors');
  return data.data?.items ?? [];
}
export async function createMonitor(name: string, dashboardUuid: string): Promise<Monitor> {
  const { data } = await api.post<ApiResponse<Monitor>>('/monitors', { name, dashboard_uuid: dashboardUuid });
  return data.data as Monitor;
}
export async function deleteMonitor(uuid: string): Promise<void> {
  await api.delete(`/monitors/${uuid}`);
}
export async function revokeMonitor(uuid: string): Promise<void> {
  await api.post(`/monitors/${uuid}/revoke`, {});
}
export async function issuePairCode(uuid: string): Promise<{ code: string; expires_in: number }> {
  const { data } = await api.post<ApiResponse<{ code: string; expires_in: number }>>(`/monitors/${uuid}/pair-code`, {});
  return data.data as { code: string; expires_in: number };
}

// ── api tokens (secrets) ─────────────────────────────────────────────────────
export async function listApiTokens(): Promise<ApiToken[]> {
  const { data } = await api.get<ApiResponse<{ items: ApiToken[] }>>('/api-tokens');
  return data.data?.items ?? [];
}
export async function createApiToken(name: string, scopes: Record<string, string[]>): Promise<ApiToken & { token: string }> {
  const { data } = await api.post<ApiResponse<ApiToken & { token: string }>>('/api-tokens', { name, scopes });
  return data.data as ApiToken & { token: string };
}
export async function revokeApiToken(uuid: string): Promise<void> {
  await api.post(`/api-tokens/${uuid}/revoke`, {});
}
