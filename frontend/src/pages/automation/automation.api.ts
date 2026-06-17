import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type {
  ActionTarget,
  ApiToken,
  AppNotification,
  Monitor,
  NotificationSubscription,
  Rule,
  RuleExecution,
} from '@/types/p5';

// ── rules ────────────────────────────────────────────────────────────────────
export async function listRules(): Promise<{ count: number; items: Rule[] }> {
  const { data } = await api.get<ApiResponse<{ count: number; items: Rule[] }>>('/rules', {
    params: { items_per_page: 100 },
  });
  return data.data as { count: number; items: Rule[] };
}
export async function createRule(body: Partial<Rule>): Promise<Rule> {
  const { data } = await api.post<ApiResponse<Rule>>('/rules', body);
  return data.data as Rule;
}
export async function updateRule(uuid: string, body: Partial<Rule>): Promise<Rule> {
  const { data } = await api.put<ApiResponse<Rule>>(`/rules/${uuid}`, body);
  return data.data as Rule;
}
export async function deleteRule(uuid: string): Promise<void> {
  await api.delete(`/rules/${uuid}`);
}
export async function enableRule(uuid: string, enabled: boolean): Promise<void> {
  await api.post(`/rules/${uuid}/enable`, { enabled });
}
export async function triggerRule(uuid: string): Promise<{ status: string }> {
  const { data } = await api.post<ApiResponse<{ status: string }>>(`/rules/${uuid}/trigger`, {});
  return data.data as { status: string };
}
export async function listExecutions(ruleUuid?: string): Promise<{ count: number; items: RuleExecution[] }> {
  const path = ruleUuid ? `/rules/${ruleUuid}/executions` : '/rule-executions';
  const { data } = await api.get<ApiResponse<{ count: number; items: RuleExecution[] }>>(path, {
    params: { items_per_page: 50 },
  });
  return data.data as { count: number; items: RuleExecution[] };
}

// ── action targets (device picker for system-event triggers) ─────────────────
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

// ── notifications ────────────────────────────────────────────────────────────
export async function listNotifications(): Promise<{ count: number; unread: number; items: AppNotification[] }> {
  const { data } = await api.get<ApiResponse<{ count: number; unread: number; items: AppNotification[] }>>('/notifications');
  return data.data as { count: number; unread: number; items: AppNotification[] };
}
export async function markAllRead(): Promise<void> {
  await api.post('/notifications/read-all', {});
}
export async function listSubscriptions(): Promise<NotificationSubscription[]> {
  const { data } = await api.get<ApiResponse<{ items: NotificationSubscription[] }>>('/notification-subscriptions');
  return data.data?.items ?? [];
}
export async function createSubscription(body: Record<string, unknown>): Promise<NotificationSubscription> {
  const { data } = await api.post<ApiResponse<NotificationSubscription>>('/notification-subscriptions', body);
  return data.data as NotificationSubscription;
}
export async function updateSubscription(id: string, body: Record<string, unknown>): Promise<NotificationSubscription> {
  const { data } = await api.put<ApiResponse<NotificationSubscription>>(`/notification-subscriptions/${id}`, body);
  return data.data as NotificationSubscription;
}
export async function deleteSubscription(id: string): Promise<void> {
  await api.delete(`/notification-subscriptions/${id}`);
}

// ── api tokens ───────────────────────────────────────────────────────────────
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
