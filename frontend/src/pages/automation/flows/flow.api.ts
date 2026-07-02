import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { Flow, FlowRunDetail, FlowRunSummary } from '@/types/flow';

export async function listFlows(): Promise<{ count: number; items: Flow[] }> {
  const { data } = await api.get<ApiResponse<{ count: number; items: Flow[] }>>('/flows', {
    params: { items_per_page: 100 },
  });
  return data.data as { count: number; items: Flow[] };
}
export async function getFlow(uuid: string): Promise<Flow> {
  const { data } = await api.get<ApiResponse<Flow>>(`/flows/${uuid}`);
  return data.data as Flow;
}
export async function createFlow(body: Partial<Flow>): Promise<Flow> {
  const { data } = await api.post<ApiResponse<Flow>>('/flows', body);
  return data.data as Flow;
}
export async function updateFlow(uuid: string, body: Partial<Flow>): Promise<Flow> {
  const { data } = await api.put<ApiResponse<Flow>>(`/flows/${uuid}`, body);
  return data.data as Flow;
}
export async function deleteFlow(uuid: string): Promise<void> {
  await api.delete(`/flows/${uuid}`);
}
export async function enableFlow(uuid: string, enabled: boolean): Promise<Flow> {
  const { data } = await api.post<ApiResponse<Flow>>(`/flows/${uuid}/enable`, { enabled });
  return data.data as Flow;
}
export async function runFlow(uuid: string): Promise<FlowRunDetail> {
  const { data } = await api.post<ApiResponse<FlowRunDetail>>(`/flows/${uuid}/run`, {});
  return data.data as FlowRunDetail;
}
export async function listFlowRuns(uuid: string): Promise<{ count: number; items: FlowRunSummary[] }> {
  const { data } = await api.get<ApiResponse<{ count: number; items: FlowRunSummary[] }>>(
    `/flows/${uuid}/runs`, { params: { items_per_page: 50 } });
  return data.data as { count: number; items: FlowRunSummary[] };
}
export async function getFlowRun(uuid: string, runId: string): Promise<FlowRunDetail> {
  const { data } = await api.get<ApiResponse<FlowRunDetail>>(`/flows/${uuid}/runs/${runId}`);
  return data.data as FlowRunDetail;
}
