import { env } from '@/config/env';
import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';
import type { ShareLink, ShareLinkCreated, ShareView } from '@/types/p6';

export interface ShareLinkInput {
  kind: 'clip' | 'event';
  camera_uuid?: string;
  event_id?: string;
  range_start?: number;
  range_end?: number;
  label?: string;
  password?: string;
  max_views?: number | null;
  expires_in_s?: number;
  watermark?: boolean;
}

// ── owner-authed ──────────────────────────────────────────────────────────────
export async function createShareLink(body: ShareLinkInput): Promise<ShareLinkCreated> {
  const { data } = await api.post<ApiResponse<ShareLinkCreated>>('/share-links', body);
  return data.data as ShareLinkCreated;
}

export async function listShareLinks(): Promise<ShareLink[]> {
  const { data } = await api.get<ApiResponse<{ items: ShareLink[] }>>('/share-links');
  return data.data?.items ?? [];
}

export async function revokeShareLink(id: string): Promise<void> {
  await api.delete(`/share-links/${id}`);
}

// ── public viewer (no auth — bare fetch so the JWT interceptor never runs) ─────
export async function getShareView(token: string): Promise<ShareView> {
  const res = await fetch(`${env.apiUrl}/s/${encodeURIComponent(token)}`);
  if (res.status === 404) return { status: 'revoked' }; // treat unknown token as gone
  const json = (await res.json()) as ApiResponse<ShareView>;
  return (json.data as ShareView) ?? { status: 'revoked' };
}

export async function unlockShareView(token: string, password: string): Promise<ShareView> {
  const res = await fetch(`${env.apiUrl}/s/${encodeURIComponent(token)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  const json = (await res.json()) as ApiResponse<ShareView>;
  return (json.data as ShareView) ?? { status: 'revoked' };
}

export function shareSegmentUrl(token: string, segmentId: string): string {
  return `${env.apiUrl}/s/${encodeURIComponent(token)}/segments/${segmentId}/data`;
}

/** Full shareable URL the owner copies. `base` is the configured public base URL
 *  (Settings → general); falls back to the current browser origin when unset. */
export function shareUrl(path: string, base?: string): string {
  const origin = (base && base.trim()) || window.location.origin;
  return `${origin.replace(/\/$/, '')}${path}`;
}
