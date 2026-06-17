import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface Door {
  id: string;
  name: string;
  location: string | null;
  controller_type: string;
  lock_state: 'locked' | 'unlocked';
  camera_id: string | null;
  access_group: string;
  require_pin: boolean;
  unlock_seconds: number;
  enabled: boolean;
}

export interface AccessCredential {
  id: string;
  card_number: string;
  holder_name: string;
  access_group: string;
  has_pin: boolean;
  valid_from: number | null;
  valid_until: number | null;
  enabled: boolean;
}

export interface AccessEvent {
  id: string;
  door_id: string;
  card_number: string | null;
  holder_name: string | null;
  decision: 'granted' | 'denied';
  reason: string | null;
  source: string | null;
  ts: number | null;
}

export async function listDoors(): Promise<Door[]> {
  const { data } = await api.get<ApiResponse<{ items: Door[] }>>('/access/doors');
  return data.data?.items ?? [];
}
export async function createDoor(body: Partial<Door>): Promise<Door> {
  const { data } = await api.post<ApiResponse<Door>>('/access/doors', body);
  return data.data as Door;
}
export async function deleteDoor(id: string): Promise<void> {
  await api.delete(`/access/doors/${id}`);
}
export async function unlockDoor(id: string): Promise<unknown> {
  const { data } = await api.post(`/access/doors/${id}/unlock`, {});
  return data;
}
export async function swipe(id: string, card_number: string, pin?: string): Promise<{ granted: boolean; decision: string; reason: string | null }> {
  const { data } = await api.post<ApiResponse<{ granted: boolean; decision: string; reason: string | null }>>(
    `/access/doors/${id}/swipe`, { card_number, pin });
  return data.data as { granted: boolean; decision: string; reason: string | null };
}

export async function listCredentials(): Promise<AccessCredential[]> {
  const { data } = await api.get<ApiResponse<{ items: AccessCredential[] }>>('/access/credentials');
  return data.data?.items ?? [];
}
export async function createCredential(body: { card_number: string; holder_name: string; access_group?: string; pin?: string }): Promise<AccessCredential> {
  const { data } = await api.post<ApiResponse<AccessCredential>>('/access/credentials', body);
  return data.data as AccessCredential;
}
export async function deleteCredential(id: string): Promise<void> {
  await api.delete(`/access/credentials/${id}`);
}

export async function listAccessEvents(): Promise<AccessEvent[]> {
  const { data } = await api.get<ApiResponse<{ items: AccessEvent[] }>>('/access/events');
  return data.data?.items ?? [];
}
