import { getAccessToken } from '@/auth/authStorage';
import { env } from '@/config/env';
import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type {
  AiAssignment,
  AiNode,
  AiSettings,
  DetectionOverlayData,
  DetectionSearchResult,
  DetectionTimelineData,
  DetectionZone,
  ObjectTrigger,
} from '@/types/p4';

const repeat = { paramsSerializer: { indexes: null } } as const;

// ── detection search ─────────────────────────────────────────────────────────
export interface DetectionFilter {
  cameraId?: string;
  labels?: string[];
  start?: number;
  end?: number;
  minConfidence?: number;
  group?: 'clip' | 'track' | 'raw';
  page?: number;
}

export async function searchDetections(f: DetectionFilter): Promise<DetectionSearchResult> {
  const params: Record<string, unknown> = { group: f.group ?? 'clip', page: f.page ?? 1, items_per_page: 60 };
  if (f.cameraId) params.camera_id = f.cameraId;
  if (f.labels?.length) params.label = f.labels;
  if (f.start) params.start = f.start;
  if (f.end) params.end = f.end;
  if (f.minConfidence !== undefined) params.min_confidence = f.minConfidence;
  const { data } = await api.get<ApiResponse<DetectionSearchResult>>('/detections/search', { params, ...repeat });
  return data.data as DetectionSearchResult;
}

export async function getDetectionOverlay(
  cameraUuid: string,
  start: number,
  end: number,
  labels?: string[],
): Promise<DetectionOverlayData> {
  const params: Record<string, unknown> = { camera_id: cameraUuid, start, end };
  if (labels?.length) params.label = labels;
  const { data } = await api.get<ApiResponse<DetectionOverlayData>>('/detections/overlay', { params, ...repeat });
  return data.data as DetectionOverlayData;
}

export async function getDetectionTimeline(
  cameraUuid: string,
  start: number,
  end: number,
  labels?: string[],
): Promise<DetectionTimelineData> {
  const params: Record<string, unknown> = { camera_id: cameraUuid, start, end };
  if (labels?.length) params.label = labels;
  const { data } = await api.get<ApiResponse<DetectionTimelineData>>('/detections/timeline', { params, ...repeat });
  return data.data as DetectionTimelineData;
}

export function detectionSnapshotUrl(detectionId: string): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/detections/${detectionId}/snapshot?access_token=${encodeURIComponent(token)}`;
}

// ── zones ────────────────────────────────────────────────────────────────────
export async function listZones(cameraUuid: string): Promise<DetectionZone[]> {
  const { data } = await api.get<ApiResponse<{ items: DetectionZone[] }>>(`/cameras/${cameraUuid}/detection-zones`);
  return data.data?.items ?? [];
}
export async function createZone(cameraUuid: string, body: Partial<DetectionZone>): Promise<DetectionZone> {
  const { data } = await api.post<ApiResponse<DetectionZone>>(`/cameras/${cameraUuid}/detection-zones`, body);
  return data.data as DetectionZone;
}
export async function updateZone(zoneId: string, body: Partial<DetectionZone>): Promise<DetectionZone> {
  const { data } = await api.put<ApiResponse<DetectionZone>>(`/detection-zones/${zoneId}`, body);
  return data.data as DetectionZone;
}
export async function deleteZone(zoneId: string): Promise<void> {
  await api.delete(`/detection-zones/${zoneId}`);
}

// ── triggers ─────────────────────────────────────────────────────────────────
export async function listTriggers(cameraUuid?: string): Promise<ObjectTrigger[]> {
  const { data } = await api.get<ApiResponse<{ items: ObjectTrigger[] }>>('/object-triggers', {
    params: cameraUuid ? { camera_id: cameraUuid } : {},
  });
  return data.data?.items ?? [];
}
export type TriggerInput = Partial<ObjectTrigger> & { camera_uuid?: string | null };
export async function createTrigger(body: TriggerInput): Promise<ObjectTrigger> {
  const { data } = await api.post<ApiResponse<ObjectTrigger>>('/object-triggers', body);
  return data.data as ObjectTrigger;
}
export async function updateTrigger(id: string, body: TriggerInput): Promise<ObjectTrigger> {
  const { data } = await api.put<ApiResponse<ObjectTrigger>>(`/object-triggers/${id}`, body);
  return data.data as ObjectTrigger;
}
export async function deleteTrigger(id: string): Promise<void> {
  await api.delete(`/object-triggers/${id}`);
}
export async function testTrigger(body: Record<string, unknown>): Promise<{ matched: boolean; name?: string }> {
  const { data } = await api.post<ApiResponse<{ matched: boolean; name?: string }>>('/object-triggers/test', body);
  return data.data as { matched: boolean; name?: string };
}

// ── settings ─────────────────────────────────────────────────────────────────
export interface AiSettingsResponse {
  global: AiSettings;
  camera_id?: string;
  camera_override?: AiSettings | null;
  effective?: Record<string, unknown>;
}
export async function getAiSettings(cameraUuid?: string): Promise<AiSettingsResponse> {
  const { data } = await api.get<ApiResponse<AiSettingsResponse>>('/ai/settings', {
    params: cameraUuid ? { camera_id: cameraUuid } : {},
  });
  return data.data as AiSettingsResponse;
}
export async function updateAiSettings(body: Partial<AiSettings>): Promise<AiSettings> {
  const { data } = await api.put<ApiResponse<AiSettings>>('/ai/settings', body);
  return data.data as AiSettings;
}

// ── nodes / assignments ──────────────────────────────────────────────────────
export async function listNodes(): Promise<AiNode[]> {
  const { data } = await api.get<ApiResponse<{ items: AiNode[] }>>('/ai-nodes');
  return data.data?.items ?? [];
}
export async function createNode(name: string): Promise<{ node: AiNode; join_token: string }> {
  const { data } = await api.post<ApiResponse<{ node: AiNode; join_token: string }>>('/ai-nodes', { name });
  return data.data as { node: AiNode; join_token: string };
}
export async function drainNode(id: string): Promise<void> {
  await api.post(`/ai-nodes/${id}/drain`, {});
}
export async function deleteNode(id: string): Promise<void> {
  await api.delete(`/ai-nodes/${id}`);
}
export async function listAssignments(): Promise<{ items: AiAssignment[]; etag: string }> {
  const { data } = await api.get<ApiResponse<{ items: AiAssignment[]; etag: string }>>('/ai/assignments');
  return data.data as { items: AiAssignment[]; etag: string };
}
export async function rebalance(): Promise<{ assigned: number; pending_count: number }> {
  const { data } = await api.post<ApiResponse<{ assigned: number; pending_count: number }>>(
    '/ai/assignments/rebalance', {});
  return data.data as { assigned: number; pending_count: number };
}
