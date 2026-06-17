import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface AudioDetection {
  id: string;
  camera_id: string;
  ts: number | null;
  label: string;
  score: number;
  clip_path: string | null;
  event_id: string | null;
}

export async function listAudioDetections(cameraUuid: string, limit = 50): Promise<AudioDetection[]> {
  const { data } = await api.get<ApiResponse<{ items: AudioDetection[] }>>(
    `/cameras/${cameraUuid}/audio-detections`,
    { params: { limit } },
  );
  return data.data?.items ?? [];
}

export async function audioLabels(): Promise<{ labels: string[]; backend: string }> {
  const { data } = await api.get<ApiResponse<{ labels: string[]; backend: string }>>('/audio/labels');
  return data.data ?? { labels: [], backend: 'stub' };
}
