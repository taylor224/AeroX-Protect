import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { ArchiveJob, ArchiveTarget } from '@/types/p6';

export interface ArchiveTargetInput {
  name: string;
  type: 's3' | 'smb' | 'local';
  config?: Record<string, unknown>;
  secrets?: Record<string, string>;
  enabled?: boolean;
}

export async function listTargets(): Promise<ArchiveTarget[]> {
  const { data } = await api.get<ApiResponse<{ items: ArchiveTarget[] }>>('/archive-targets');
  return data.data?.items ?? [];
}

export async function createTarget(body: ArchiveTargetInput): Promise<ArchiveTarget> {
  const { data } = await api.post<ApiResponse<ArchiveTarget>>('/archive-targets', body);
  return data.data as ArchiveTarget;
}

export async function updateTarget(id: string, body: Partial<ArchiveTargetInput>): Promise<ArchiveTarget> {
  const { data } = await api.put<ApiResponse<ArchiveTarget>>(`/archive-targets/${id}`, body);
  return data.data as ArchiveTarget;
}

export async function deleteTarget(id: string): Promise<void> {
  await api.delete(`/archive-targets/${id}`);
}

export async function listJobs(): Promise<ArchiveJob[]> {
  const { data } = await api.get<ApiResponse<{ items: ArchiveJob[] }>>('/archive-jobs');
  return data.data?.items ?? [];
}

export async function createJob(targetId: string, sourceRef: string): Promise<{ job_id: string }> {
  const { data } = await api.post<ApiResponse<{ job_id: string }>>('/archive-jobs', {
    target_id: targetId,
    source_ref: sourceRef,
    source_type: 'recording',
  });
  return data.data as { job_id: string };
}
