import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { FeatureFlag, FeatureFlagsResponse } from '@/types/p6';

export async function getFeatureFlags(): Promise<FeatureFlagsResponse> {
  const { data } = await api.get<ApiResponse<FeatureFlagsResponse>>('/feature-flags');
  return data.data ?? { items: [], enabled: {} };
}

export async function setFeatureFlag(key: string, enabled: boolean): Promise<FeatureFlag> {
  const { data } = await api.put<ApiResponse<FeatureFlag>>(`/feature-flags/${key}`, { enabled });
  return data.data as FeatureFlag;
}

/** The full key→enabled map (fail-closed: empty until loaded). */
export function useFeatureFlags(): Record<string, boolean> {
  const { data } = useQuery({
    queryKey: ['feature-flags'],
    queryFn: getFeatureFlags,
    staleTime: 60_000,
  });
  return data?.enabled ?? {};
}

/** Gate UI on a P6 feature flag. Defaults to false until the map loads (fail-closed). */
export function useFeatureFlag(key: string): boolean {
  return useFeatureFlags()[key] ?? false;
}
