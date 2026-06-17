import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { DashboardDetail, DashboardLayout, DashboardSummary } from '@/types/axp';

export async function listDashboards(): Promise<DashboardSummary[]> {
  const { data } = await api.get<ApiResponse<{ items: DashboardSummary[] }>>('/dashboards');
  return data.data?.items ?? [];
}

export async function getDashboard(uuid: string): Promise<DashboardDetail> {
  const { data } = await api.get<ApiResponse<DashboardDetail>>(`/dashboards/${uuid}`);
  return data.data as DashboardDetail;
}

export async function createDashboard(name: string, layout: DashboardLayout): Promise<DashboardDetail> {
  const { data } = await api.post<ApiResponse<DashboardDetail>>('/dashboards', { name, layout });
  return data.data as DashboardDetail;
}

export async function saveDashboard(uuid: string, patch: { name?: string; layout?: DashboardLayout }): Promise<DashboardDetail> {
  const { data } = await api.post<ApiResponse<DashboardDetail>>(`/dashboards/${uuid}`, patch);
  return data.data as DashboardDetail;
}

export async function deleteDashboard(uuid: string): Promise<void> {
  await api.delete(`/dashboards/${uuid}`);
}

export async function setAcl(uuid: string, userId: string, access: 'view' | 'edit'): Promise<void> {
  await api.post(`/dashboards/${uuid}/acl`, { user_id: userId, access });
}

export async function removeAcl(uuid: string, userId: string): Promise<void> {
  await api.delete(`/dashboards/${uuid}/acl/${userId}`);
}
