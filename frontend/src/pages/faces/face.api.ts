import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface FaceIdentity {
  id: string;
  name: string;
  note: string | null;
  consent: boolean;
  consent_at: number | null;
  enabled: boolean;
  backend: string | null;
  embedding_count: number;
  created_at: number | null;
}

export interface FaceObservation {
  id: string;
  camera_id: string;
  ts: number | null;
  quality: number | null;
  identity_id: string | null;
  identity_name: string | null;
  score: number | null;
  event_id: string | null;
}

export async function listIdentities(): Promise<FaceIdentity[]> {
  const { data } = await api.get<ApiResponse<{ items: FaceIdentity[] }>>('/face/identities');
  return data.data?.items ?? [];
}

export async function createIdentity(body: { name: string; consent: boolean; note?: string }): Promise<FaceIdentity> {
  const { data } = await api.post<ApiResponse<FaceIdentity>>('/face/identities', body);
  return data.data as FaceIdentity;
}

export async function updateIdentity(id: string, body: Partial<FaceIdentity>): Promise<FaceIdentity> {
  const { data } = await api.put<ApiResponse<FaceIdentity>>(`/face/identities/${id}`, body);
  return data.data as FaceIdentity;
}

export async function deleteIdentity(id: string): Promise<void> {
  await api.delete(`/face/identities/${id}`);
}

export async function enrollFromObservation(identityId: string, observationId: string): Promise<FaceIdentity> {
  const { data } = await api.post<ApiResponse<FaceIdentity>>(
    `/face/identities/${identityId}/enroll`, { observation_id: observationId });
  return data.data as FaceIdentity;
}

export async function listCameraFaces(cameraUuid: string, limit = 50): Promise<FaceObservation[]> {
  const { data } = await api.get<ApiResponse<{ items: FaceObservation[] }>>(
    `/cameras/${cameraUuid}/faces`, { params: { limit } });
  return data.data?.items ?? [];
}

/** Recent face observations across ALL cameras the user may view (default-deny scoped). */
export async function listAllFaces(limit = 100): Promise<FaceObservation[]> {
  const { data } = await api.get<ApiResponse<{ items: FaceObservation[] }>>(
    '/faces/search', { params: { limit } });
  return data.data?.items ?? [];
}
