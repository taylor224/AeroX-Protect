import { getAccessToken } from '@/auth/authStorage';
import { env } from '@/config/env';
import { api } from '@/lib/axios';
import type { ApiResponse, PageResult } from '@/types/api';
import type {
  AxpEvent,
  EventListResult,
  EventOverlay,
  EventPolicy,
  EventTimelineData,
  ScheduleRule,
  TimelapseJob,
} from '@/types/p3';

// repeat query keys without bracket indexes → ?type=a&type=b (Flask getlist)
const repeat = { paramsSerializer: { indexes: null } } as const;

// ── events ───────────────────────────────────────────────────────────────────
export interface EventFilter {
  cameraId?: string; // numeric camera id (events filter by id, not uuid)
  types?: string[];
  start?: number;
  end?: number;
  hasRecording?: boolean;
  page?: number;
}

export async function listEvents(f: EventFilter): Promise<EventListResult> {
  const params: Record<string, unknown> = { page: f.page ?? 1, items_per_page: 100, order: 'desc' };
  if (f.cameraId) params.camera_id = f.cameraId;
  if (f.types?.length) params.type = f.types;
  if (f.start) params.start = f.start;
  if (f.end) params.end = f.end;
  if (f.hasRecording !== undefined) params.has_recording = f.hasRecording;
  const { data } = await api.get<ApiResponse<EventListResult>>('/events', { params, ...repeat });
  return data.data as EventListResult;
}

export async function getEventTimeline(
  cameraUuid: string,
  start: number,
  end: number,
  types?: string[],
): Promise<EventTimelineData> {
  const params: Record<string, unknown> = { camera_id: cameraUuid, start, end };
  if (types?.length) params.type = types;
  const { data } = await api.get<ApiResponse<EventTimelineData>>('/events/timeline', { params, ...repeat });
  return data.data as EventTimelineData;
}

export async function getEventOverlay(eventId: string): Promise<EventOverlay> {
  const { data } = await api.get<ApiResponse<EventOverlay>>(`/events/${eventId}/overlay`);
  return data.data as EventOverlay;
}

export async function simulateEvent(cameraUuid: string, type: string, score?: number): Promise<AxpEvent> {
  const { data } = await api.post<ApiResponse<AxpEvent>>('/events/simulate', {
    camera_uuid: cameraUuid,
    type,
    score,
  });
  return data.data as AxpEvent;
}

// ── policies ─────────────────────────────────────────────────────────────────
export async function listPolicies(cameraUuid?: string): Promise<EventPolicy[]> {
  const { data } = await api.get<ApiResponse<{ items: EventPolicy[] }>>('/event-policies', {
    params: cameraUuid ? { camera_id: cameraUuid } : {},
  });
  return data.data?.items ?? [];
}

export type PolicyInput = Partial<EventPolicy> & { camera_uuid?: string | null };

export async function createPolicy(body: PolicyInput): Promise<EventPolicy> {
  const { data } = await api.post<ApiResponse<EventPolicy>>('/event-policies', body);
  return data.data as EventPolicy;
}

export async function updatePolicy(id: string, body: PolicyInput): Promise<EventPolicy> {
  const { data } = await api.put<ApiResponse<EventPolicy>>(`/event-policies/${id}`, body);
  return data.data as EventPolicy;
}

export async function deletePolicy(id: string): Promise<void> {
  await api.delete(`/event-policies/${id}`);
}

// ── schedule ─────────────────────────────────────────────────────────────────
export async function getSchedule(cameraUuid: string): Promise<ScheduleRule[]> {
  const { data } = await api.get<ApiResponse<{ rules: ScheduleRule[] }>>(`/cameras/${cameraUuid}/schedule`);
  return data.data?.rules ?? [];
}

export async function replaceSchedule(cameraUuid: string, rules: ScheduleRule[]): Promise<ScheduleRule[]> {
  const { data } = await api.put<ApiResponse<{ rules: ScheduleRule[] }>>(`/cameras/${cameraUuid}/schedule`, {
    rules,
  });
  return data.data?.rules ?? [];
}

// ── timelapse ────────────────────────────────────────────────────────────────
export async function listTimelapse(cameraUuid?: string): Promise<TimelapseJob[]> {
  const { data } = await api.get<ApiResponse<PageResult<TimelapseJob>>>('/timelapse', {
    params: { items_per_page: 20, ...(cameraUuid ? { camera_id: cameraUuid } : {}) },
  });
  return data.data?.items ?? [];
}

export async function createTimelapse(body: {
  camera_uuid: string;
  range_start: number;
  range_end: number;
  speed_factor: number;
}): Promise<TimelapseJob> {
  const { data } = await api.post<ApiResponse<TimelapseJob>>('/timelapse', body);
  return data.data as TimelapseJob;
}

export async function cancelTimelapse(jobId: string): Promise<void> {
  await api.post(`/timelapse/${jobId}/cancel`, {});
}

export function timelapseDownloadUrl(jobId: string): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/timelapse/${jobId}/download?access_token=${encodeURIComponent(token)}`;
}
