import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { PrivacyMask } from '@/types/p6';

export async function listMasks(cameraUuid: string): Promise<PrivacyMask[]> {
  const { data } = await api.get<ApiResponse<{ items: PrivacyMask[] }>>(`/cameras/${cameraUuid}/privacy-masks`);
  return data.data?.items ?? [];
}

export async function createMask(
  cameraUuid: string,
  body: { name: string; polygon: [number, number][] },
): Promise<PrivacyMask> {
  const { data } = await api.post<ApiResponse<PrivacyMask>>(`/cameras/${cameraUuid}/privacy-masks`, body);
  return data.data as PrivacyMask;
}

export async function updateMask(id: string, body: Partial<PrivacyMask>): Promise<PrivacyMask> {
  const { data } = await api.put<ApiResponse<PrivacyMask>>(`/privacy-masks/${id}`, body);
  return data.data as PrivacyMask;
}

export async function deleteMask(id: string): Promise<void> {
  await api.delete(`/privacy-masks/${id}`);
}
