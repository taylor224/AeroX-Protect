import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { DiscoverCandidate, Disk, PoolSummary, StoragePolicy } from '@/types/p2';

export async function listDisks(): Promise<Disk[]> {
  const { data } = await api.get<ApiResponse<{ disks: Disk[] }>>('/storage/disks');
  return data.data?.disks ?? [];
}

export async function getPool(): Promise<PoolSummary> {
  const { data } = await api.get<ApiResponse<PoolSummary>>('/storage/pool');
  return data.data as PoolSummary;
}

export async function discoverDisks(): Promise<DiscoverCandidate[]> {
  const { data } = await api.get<ApiResponse<{ candidates: DiscoverCandidate[] }>>('/storage/discover');
  return data.data?.candidates ?? [];
}

export async function registerDisk(body: {
  name: string;
  mount_path: string;
  role: string;
  reserved_free_bytes: number;
}): Promise<Disk> {
  const { data } = await api.post<ApiResponse<Disk>>('/storage/disks', body);
  return data.data as Disk;
}

export async function updateDisk(id: string, patch: Partial<Disk>): Promise<Disk> {
  const { data } = await api.put<ApiResponse<Disk>>(`/storage/disks/${id}`, patch);
  return data.data as Disk;
}

export async function deleteDisk(id: string, mode: 'unregister' | 'evacuate'): Promise<void> {
  await api.delete(`/storage/disks/${id}`, { data: { mode } });
}

export async function getPolicy(cameraUuid: string): Promise<StoragePolicy> {
  const { data } = await api.get<ApiResponse<StoragePolicy>>(`/storage/policies/${cameraUuid}`);
  return data.data as StoragePolicy;
}

export async function updatePolicy(cameraUuid: string, patch: Partial<StoragePolicy>): Promise<StoragePolicy> {
  const { data } = await api.put<ApiResponse<StoragePolicy>>(`/storage/policies/${cameraUuid}`, patch);
  return data.data as StoragePolicy;
}
