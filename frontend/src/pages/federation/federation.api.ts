import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface FederationMember {
  id: string;
  name: string;
  base_url: string;
  has_token: boolean;
  status: 'unknown' | 'online' | 'offline' | 'error';
  last_sync_at: number | null;
  last_error: string | null;
  camera_count: number;
  enabled: boolean;
  created_at: number | null;
}

export interface FederationCamera {
  id: string;
  member_id: string;
  member_name: string | null;
  remote_uuid: string;
  name: string;
  status: string | null;
  online: boolean;
  last_sync_at: number | null;
}

export async function listMembers(): Promise<FederationMember[]> {
  const { data } = await api.get<ApiResponse<{ items: FederationMember[] }>>('/federation/members');
  return data.data?.items ?? [];
}

export async function createMember(body: { name: string; base_url: string; token: string }): Promise<FederationMember> {
  const { data } = await api.post<ApiResponse<FederationMember>>('/federation/members', body);
  return data.data as FederationMember;
}

export async function deleteMember(id: string): Promise<void> {
  await api.delete(`/federation/members/${id}`);
}

export async function syncMember(id: string): Promise<FederationMember> {
  const { data } = await api.post<ApiResponse<FederationMember>>(`/federation/members/${id}/sync`, {});
  return data.data as FederationMember;
}

export async function aggregatedCameras(): Promise<FederationCamera[]> {
  const { data } = await api.get<ApiResponse<{ cameras: FederationCamera[] }>>('/federation/cameras');
  return data.data?.cameras ?? [];
}
