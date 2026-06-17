import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { CountingLine, CountingStat } from '@/types/p6';

export interface CountingLineInput {
  name: string;
  kind: 'line' | 'region';
  geometry: [number, number][];
  class_filter?: string[] | null;
  loiter_threshold_s?: number | null;
  occupancy_threshold?: number | null;
}

export async function listCountingLines(cameraUuid: string): Promise<CountingLine[]> {
  const { data } = await api.get<ApiResponse<{ items: CountingLine[] }>>(`/cameras/${cameraUuid}/counting`);
  return data.data?.items ?? [];
}

export async function createCountingLine(cameraUuid: string, body: CountingLineInput): Promise<CountingLine> {
  const { data } = await api.post<ApiResponse<CountingLine>>(`/cameras/${cameraUuid}/counting`, body);
  return data.data as CountingLine;
}

export async function deleteCountingLine(id: string): Promise<void> {
  await api.delete(`/counting/${id}`);
}

export async function getCountingAnalytics(
  cameraUuid: string,
  start: number,
  end: number,
): Promise<CountingStat[]> {
  const { data } = await api.get<ApiResponse<{ items: CountingStat[] }>>('/analytics/counting', {
    params: { camera_id: cameraUuid, start, end },
  });
  return data.data?.items ?? [];
}
