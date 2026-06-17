import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface SemanticResult {
  source_type: string;
  source_ref: string;
  camera_id: string;
  ts: number;
  text: string | null;
  score: number;
}

export interface SemanticSearchResponse {
  backend: string;
  count: number;
  items: SemanticResult[];
}

export async function semanticSearch(q: string, cameraId?: string, limit = 24): Promise<SemanticSearchResponse> {
  const params: Record<string, unknown> = { q, limit };
  if (cameraId) params.camera_id = cameraId;
  const { data } = await api.get<ApiResponse<SemanticSearchResponse>>('/search/semantic', { params });
  return data.data ?? { backend: 'hash', count: 0, items: [] };
}

export async function semanticReindex(cameraId?: string): Promise<{ indexed: number; backend: string }> {
  const { data } = await api.post<ApiResponse<{ indexed: number; backend: string }>>(
    '/search/semantic/reindex',
    cameraId ? { camera_id: cameraId } : {},
  );
  return data.data as { indexed: number; backend: string };
}
