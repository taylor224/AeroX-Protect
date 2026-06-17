import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

export interface PortalConfig {
  enabled: boolean;
  stun_urls: string[];
  turn_host: string | null;
  turn_port: number;
  turn_protocol: 'udp' | 'tcp';
  turn_tls: boolean;
  realm: string | null;
  ttl_seconds: number;
  has_secret: boolean;
  updated_at: number | null;
}

const FALLBACK: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }];

let cache: { servers: RTCIceServer[]; expiresAt: number } | null = null;

/** ICE servers for WebRTC peers (P9). Cached until shortly before the TURN-credential TTL
 *  expires; falls back to public STUN so live never breaks. */
export async function getIceServers(): Promise<RTCIceServer[]> {
  const now = Date.now();
  if (cache && cache.expiresAt > now) return cache.servers;
  try {
    const { data } = await api.get<ApiResponse<{ ice_servers: RTCIceServer[]; ttl: number }>>(
      '/portal/ice-servers');
    const servers = data.data?.ice_servers?.length ? data.data.ice_servers : FALLBACK;
    const ttl = data.data?.ttl ?? 0;
    const lifetimeMs = ttl > 0 ? Math.max(60, ttl - 60) * 1000 : 300_000;
    cache = { servers, expiresAt: now + lifetimeMs };
    return servers;
  } catch {
    return FALLBACK;
  }
}

export async function getPortalConfig(): Promise<PortalConfig> {
  const { data } = await api.get<ApiResponse<PortalConfig>>('/portal/config');
  return data.data as PortalConfig;
}

export async function updatePortalConfig(body: Partial<PortalConfig> & { auth_secret?: string }): Promise<PortalConfig> {
  const { data } = await api.put<ApiResponse<PortalConfig>>('/portal/config', body);
  return data.data as PortalConfig;
}
