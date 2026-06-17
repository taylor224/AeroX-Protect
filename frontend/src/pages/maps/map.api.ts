import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { MapMarker, SiteMap } from '@/types/p6';

export async function listMaps(): Promise<SiteMap[]> {
  const { data } = await api.get<ApiResponse<{ items: SiteMap[] }>>('/maps');
  return data.data?.items ?? [];
}

export async function getMap(id: string): Promise<SiteMap> {
  const { data } = await api.get<ApiResponse<SiteMap>>(`/maps/${id}`);
  return data.data as SiteMap;
}

export async function createMap(body: Partial<SiteMap>): Promise<SiteMap> {
  const { data } = await api.post<ApiResponse<SiteMap>>('/maps', body);
  return data.data as SiteMap;
}

export async function deleteMap(id: string): Promise<void> {
  await api.delete(`/maps/${id}`);
}

export async function replaceMarkers(id: string, markers: MapMarker[]): Promise<SiteMap> {
  const { data } = await api.put<ApiResponse<SiteMap>>(`/maps/${id}/markers`, { markers });
  return data.data as SiteMap;
}

export type MapProvider = 'osm' | 'google';

export interface MapConfig {
  provider: MapProvider;
  has_key: boolean;
  google_api_key?: string | null;
  updated_at?: number;
}

export async function getMapConfig(): Promise<MapConfig> {
  const { data } = await api.get<ApiResponse<MapConfig>>('/maps/config');
  return data.data as MapConfig;
}

export async function updateMapConfig(body: { provider?: MapProvider; google_api_key?: string }): Promise<MapConfig> {
  const { data } = await api.put<ApiResponse<MapConfig>>('/maps/config', body);
  return data.data as MapConfig;
}
