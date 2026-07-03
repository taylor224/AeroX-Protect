import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { EncodeAssignment, EncodingNode } from '@/types/p4';

// ── encoder worker nodes (live/playback transcode offload) ───────────────────
export async function listEncodingNodes(): Promise<EncodingNode[]> {
  const { data } = await api.get<ApiResponse<{ items: EncodingNode[] }>>('/encoding-nodes');
  return data.data?.items ?? [];
}
export async function createEncodingNode(name: string): Promise<{ node: EncodingNode; join_token: string }> {
  const { data } = await api.post<ApiResponse<{ node: EncodingNode; join_token: string }>>('/encoding-nodes', { name });
  return data.data as { node: EncodingNode; join_token: string };
}
export async function drainEncodingNode(id: string): Promise<void> {
  await api.post(`/encoding-nodes/${id}/drain`, {});
}
export async function deleteEncodingNode(id: string): Promise<void> {
  await api.delete(`/encoding-nodes/${id}`);
}
export async function listEncodeAssignments(): Promise<{ items: EncodeAssignment[] }> {
  const { data } = await api.get<ApiResponse<{ items: EncodeAssignment[] }>>('/encoding-nodes/assignments');
  return data.data as { items: EncodeAssignment[] };
}
export async function rebalanceEncoding(): Promise<{ assigned: number; pending_count: number }> {
  const { data } = await api.post<ApiResponse<{ assigned: number; pending_count: number }>>(
    '/encoding-nodes/assignments/rebalance', {});
  return data.data as { assigned: number; pending_count: number };
}
