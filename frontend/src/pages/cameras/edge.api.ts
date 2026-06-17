import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface EdgeGap {
  start_ts: number;
  end_ts: number;
  duration_ms: number;
}

export interface EdgeImportJob {
  id: string;
  camera_id: string;
  range_start: number;
  range_end: number;
  status: 'queued' | 'running' | 'done' | 'failed';
  progress: number;
  clips_found: number;
  clips_imported: number;
  bytes_done: number;
  error_message: string | null;
  created_at: number | null;
}

export async function previewGaps(cameraUuid: string, start: number, end: number): Promise<EdgeGap[]> {
  const { data } = await api.get<ApiResponse<{ gaps: EdgeGap[] }>>(
    `/cameras/${cameraUuid}/edge/gaps`,
    { params: { start, end } },
  );
  return data.data?.gaps ?? [];
}

export async function listEdgeJobs(cameraUuid: string): Promise<EdgeImportJob[]> {
  const { data } = await api.get<ApiResponse<{ items: EdgeImportJob[] }>>(`/cameras/${cameraUuid}/edge/jobs`);
  return data.data?.items ?? [];
}

export async function runEdgeImport(cameraUuid: string, rangeStart: number, rangeEnd: number): Promise<EdgeImportJob> {
  const { data } = await api.post<ApiResponse<EdgeImportJob>>(`/cameras/${cameraUuid}/edge/import`, {
    range_start: rangeStart,
    range_end: rangeEnd,
  });
  return data.data as EdgeImportJob;
}
