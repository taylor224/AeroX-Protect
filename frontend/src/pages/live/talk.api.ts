import { getAccessToken } from '@/auth/authStorage';
import { env } from '@/config/env';
import { api } from '@/lib/axios';

/** Relay a WebRTC offer to the camera backchannel; returns the answer SDP (+ status). */
export async function talkOffer(
  cameraUuid: string,
  offerSdp: string,
): Promise<{ ok: boolean; status: number; sdp: string | null }> {
  const token = getAccessToken() ?? '';
  const res = await fetch(`${env.apiUrl}/cameras/${cameraUuid}/talk/offer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/sdp', Authorization: `Bearer ${token}` },
    body: offerSdp,
  });
  if (!res.ok) return { ok: false, status: res.status, sdp: null };
  const text = await res.text();
  if (text.trimStart().startsWith('{')) {
    try {
      return { ok: true, status: 200, sdp: (JSON.parse(text) as { sdp?: string }).sdp ?? null };
    } catch {
      return { ok: false, status: 200, sdp: null };
    }
  }
  return { ok: true, status: 200, sdp: text || null };
}

export async function talkStop(cameraUuid: string): Promise<void> {
  try {
    await api.post(`/cameras/${cameraUuid}/talk/stop`);
  } catch {
    /* best-effort lock release */
  }
}
