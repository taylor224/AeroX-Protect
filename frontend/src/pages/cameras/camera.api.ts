import { api } from '@/lib/axios';
import type { ApiResponse, PageResult } from '@/types/api';
import type { Camera, DiscoveredDevice, ProbeResult, Stream } from '@/types/axp';
import type { BatchAddResult } from '@/types/p6';

export interface ProbeRequest {
  host: string;
  onvif_port?: number;
  http_port?: number;
  rtsp_port?: number;
  username: string;
  password: string;
  use_https?: boolean;
  rtsp_transport?: string;
  channel?: number;
}

export async function listCameras(page = 1): Promise<PageResult<Camera>> {
  const { data } = await api.get<ApiResponse<PageResult<Camera>>>('/cameras', {
    params: { page, items_per_page: 50, sort: 'created_at', order: 'desc' },
  });
  return data.data as PageResult<Camera>;
}

export async function getCamera(uuid: string): Promise<Camera> {
  const { data } = await api.get<ApiResponse<Camera>>(`/cameras/${uuid}`);
  return data.data as Camera;
}

export async function discoverOnvif(): Promise<DiscoveredDevice[]> {
  const { data } = await api.get<ApiResponse<{ devices: DiscoveredDevice[] }>>('/discovery/onvif');
  return data.data?.devices ?? [];
}

export async function probeCamera(req: ProbeRequest): Promise<ProbeResult> {
  const { data } = await api.post<ApiResponse<ProbeResult>>('/discovery/probe', req);
  return data.data as ProbeResult;
}

export interface CreateCameraRequest extends ProbeRequest {
  name: string;
  vendor: string;
  driver: string;
  model?: string | null;
  firmware?: string | null;
  serial?: string | null;
  ptz_supported?: boolean;
  audio_supported?: boolean;
  is_enabled?: boolean;
  live_transcode?: boolean;
  fisheye?: boolean;
  fisheye_params?: Record<string, number> | null;
  dual_recording?: boolean;
  dual_record_stream?: string | null;
  edge_recording?: boolean;
  edge_auto_import?: boolean;
  ai_features?: Record<string, boolean>;
  capabilities?: unknown;
  streams?: Partial<Stream>[];
}

export async function createCamera(req: CreateCameraRequest): Promise<Camera> {
  const { data } = await api.post<ApiResponse<Camera>>('/cameras', req);
  return data.data as Camera;
}

export async function batchAddCameras(
  common: Record<string, unknown>,
  items: Record<string, unknown>[],
): Promise<BatchAddResult> {
  const { data } = await api.post<ApiResponse<BatchAddResult>>('/cameras/batch', { common, items });
  return data.data as BatchAddResult;
}

export async function updateCamera(uuid: string, patch: Partial<CreateCameraRequest>): Promise<Camera> {
  const { data } = await api.post<ApiResponse<Camera>>(`/cameras/${uuid}`, patch);
  return data.data as Camera;
}

export async function deleteCamera(uuid: string): Promise<void> {
  await api.delete(`/cameras/${uuid}`);
}

/** Re-probe a camera with its stored credentials: auto-detects vendor/driver and refreshes
 *  its high/low-quality (main/sub) streams via ONVIF. Returns the updated camera. */
export async function reprobeCamera(uuid: string): Promise<Camera> {
  const { data } = await api.post<ApiResponse<Camera>>(`/cameras/${uuid}/reprobe`);
  return data.data as Camera;
}

export async function ptzCommand(uuid: string, body: Record<string, unknown>): Promise<void> {
  await api.post(`/cameras/${uuid}/ptz`, body);
}

export async function listPresets(uuid: string) {
  const { data } = await api.get<ApiResponse<{ presets: { token: string; name: string }[] }>>(
    `/cameras/${uuid}/ptz/presets`,
  );
  return data.data?.presets ?? [];
}
