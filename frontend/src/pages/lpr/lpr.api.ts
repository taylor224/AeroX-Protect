import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface PlateRead {
  id: string;
  camera_id: string;
  ts: number | null;
  plate_text: string;
  plate_key: string;
  confidence: number;
  vehicle_label: string | null;
  list_kind: 'allow' | 'deny' | null;
  list_id: string | null;
  event_id: string | null;
}

export interface PlateListEntry {
  id: string;
  plate_text: string;
  plate_key: string;
  kind: 'allow' | 'deny';
  label: string | null;
  note: string | null;
  action: string | null;
  enabled: boolean;
  created_at: number | null;
}

export async function listCameraPlates(cameraUuid: string, limit = 50): Promise<PlateRead[]> {
  const { data } = await api.get<ApiResponse<{ items: PlateRead[] }>>(
    `/cameras/${cameraUuid}/plates`, { params: { limit } });
  return data.data?.items ?? [];
}

export async function searchPlates(q: string): Promise<PlateRead[]> {
  const { data } = await api.get<ApiResponse<{ items: PlateRead[] }>>('/plates/search', { params: { q } });
  return data.data?.items ?? [];
}

export async function listWatchlist(): Promise<PlateListEntry[]> {
  const { data } = await api.get<ApiResponse<{ items: PlateListEntry[] }>>('/plate-lists');
  return data.data?.items ?? [];
}

export async function createWatchlistEntry(body: {
  plate_text: string; kind: 'allow' | 'deny'; label?: string; note?: string;
}): Promise<PlateListEntry> {
  const { data } = await api.post<ApiResponse<PlateListEntry>>('/plate-lists', body);
  return data.data as PlateListEntry;
}

export async function deleteWatchlistEntry(id: string): Promise<void> {
  await api.delete(`/plate-lists/${id}`);
}
