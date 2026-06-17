import { getAccessToken } from '@/auth/authStorage';
import { env } from '@/config/env';
import { api } from '@/lib/axios';
import type { ApiResponse, PageResult } from '@/types/api';
import type { ExportJob, RecordingStatus, Segment, TimelineData } from '@/types/p2';

export async function getTimeline(cameraUuid: string, from: number, to: number): Promise<TimelineData> {
  const { data } = await api.get<ApiResponse<TimelineData>>(`/playback/cameras/${cameraUuid}/timeline`, {
    params: { from, to },
  });
  return data.data as TimelineData;
}

export async function getSegments(cameraUuid: string, from: number, to: number): Promise<Segment[]> {
  const { data } = await api.get<ApiResponse<{ segments: Segment[] }>>(`/playback/cameras/${cameraUuid}/segments`, {
    params: { from, to },
  });
  return data.data?.segments ?? [];
}

export function segmentDataUrl(segmentId: string): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/playback/segments/${segmentId}/data?access_token=${encodeURIComponent(token)}`;
}

export function frameUrl(cameraUuid: string, ts: number): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/playback/cameras/${cameraUuid}/frame?ts=${ts}&access_token=${encodeURIComponent(token)}`;
}

// ── recording control ──────────────────────────────────────────────────────
export async function getRecordingStatus(cameraUuid: string): Promise<RecordingStatus> {
  const { data } = await api.get<ApiResponse<RecordingStatus>>(`/recording/cameras/${cameraUuid}/status`);
  return data.data as RecordingStatus;
}

export async function setRecordMode(cameraUuid: string, mode: 'off' | 'continuous'): Promise<void> {
  await api.put(`/recording/cameras/${cameraUuid}/mode`, { mode });
}

export async function manualStart(cameraUuid: string, durationS?: number): Promise<{ recording_id: string }> {
  const { data } = await api.post<ApiResponse<{ recording_id: string }>>(
    `/recording/cameras/${cameraUuid}/manual/start`,
    durationS ? { duration_s: durationS } : {});
  return data.data as { recording_id: string };
}

export async function manualStop(cameraUuid: string, recordingId: string): Promise<void> {
  await api.post(`/recording/cameras/${cameraUuid}/manual/stop`, { recording_id: recordingId });
}

/** P2 delete-protection toggle for a specific recording (e.g. an event's clip). */
export async function protectRecording(recordingId: string, protectedOn: boolean): Promise<void> {
  await api.post(`/recording/recordings/${recordingId}/protect`, { protected: protectedOn });
}

// ── export ─────────────────────────────────────────────────────────────────
export async function createExport(body: {
  camera_uuid: string;
  start_ts: number;
  end_ts: number;
  mode: 'copy' | 'transcode';
  transcode_preset?: string;
  watermark?: boolean;
  watermark_text?: string;
  password?: string;
}): Promise<{ job_id: string }> {
  const { data } = await api.post<ApiResponse<{ job_id: string }>>('/export/jobs', body);
  return data.data as { job_id: string };
}

export async function listExports(): Promise<ExportJob[]> {
  const { data } = await api.get<ApiResponse<PageResult<ExportJob>>>('/export/jobs', {
    params: { items_per_page: 20 },
  });
  return data.data?.items ?? [];
}

export function downloadUrl(token: string): string {
  const access = getAccessToken() ?? '';
  return `${env.apiUrl}/export/download/${token}?access_token=${encodeURIComponent(access)}`;
}
