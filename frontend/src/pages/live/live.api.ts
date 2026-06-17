import { getAccessToken } from '@/auth/authStorage';
import { env } from '@/config/env';
import { api } from '@/lib/axios';
import type { ApiResponse } from '@/types/api';

/** Low-latency fMP4 stream URL (token in query — <video> can't set headers). */
export function liveMp4Url(go2rtcName: string): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/live/mp4/${encodeURIComponent(go2rtcName)}?access_token=${encodeURIComponent(token)}`;
}

/** Short-lived ticket for the MSE WebSocket (issued after a JWT + camera-scope check). */
export async function getWsTicket(go2rtcName: string): Promise<{ ticket: string; expires_in: number }> {
  const { data } = await api.post<ApiResponse<{ ticket: string; expires_in: number }>>(
    `/live/ws-ticket/${encodeURIComponent(go2rtcName)}`,
  );
  return data.data as { ticket: string; expires_in: number };
}

/** Same-origin MSE WebSocket URL (nginx validates the ticket, then proxies to go2rtc).
 *  TURN-free and low-latency — works from remote networks over a plain WebSocket. */
export function liveWsUrl(go2rtcName: string, ticket: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${scheme}//${window.location.host}/live-ws/?src=${encodeURIComponent(go2rtcName)}` +
    `&ticket=${encodeURIComponent(ticket)}`;
}

export function snapshotUrl(cameraUuid: string): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/cameras/${cameraUuid}/snapshot?access_token=${encodeURIComponent(token)}`;
}

/** Cached thumbnail (refreshed ~30s by the health task) — cheap for list tiles. */
export function thumbnailUrl(cameraUuid: string): string {
  const token = getAccessToken() ?? '';
  return `${env.apiUrl}/cameras/${cameraUuid}/thumbnail?access_token=${encodeURIComponent(token)}`;
}

/** WebRTC SDP exchange via the backend proxy. Returns the answer SDP, or null. */
export async function webrtcExchange(go2rtcName: string, offerSdp: string): Promise<string | null> {
  const token = getAccessToken() ?? '';
  try {
    const res = await fetch(`${env.apiUrl}/live/webrtc/${encodeURIComponent(go2rtcName)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp', Authorization: `Bearer ${token}` },
      body: offerSdp,
    });
    if (!res.ok) return null;
    const text = await res.text();
    // go2rtc may answer raw SDP or {type,sdp}
    if (text.trimStart().startsWith('{')) {
      try {
        return (JSON.parse(text) as { sdp?: string }).sdp ?? null;
      } catch {
        return null;
      }
    }
    return text || null;
  } catch {
    return null;
  }
}
