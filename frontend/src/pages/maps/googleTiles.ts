/** Google Map Tiles API (https://developers.google.com/maps/documentation/tile/2d-tiles).
 * Official, key-based raster tiles that drop into a plain Leaflet TileLayer — no SDK, no
 * extra npm dependency. A session token is created once, then reused in the tile URLs. */

const CREATE_SESSION = 'https://tile.googleapis.com/v1/createSession';
const TILE_BASE = 'https://tile.googleapis.com/v1/2dtiles';

export async function createGoogleSession(apiKey: string): Promise<string> {
  const res = await fetch(`${CREATE_SESSION}?key=${encodeURIComponent(apiKey)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mapType: 'roadmap', language: 'ko-KR', region: 'KR' }),
  });
  if (!res.ok) throw new Error(`google session ${res.status}`);
  const data = (await res.json()) as { session?: string };
  if (!data.session) throw new Error('google session: no token');
  return data.session;
}

/** Leaflet TileLayer URL template for a created session. */
export function googleTileUrl(session: string, apiKey: string): string {
  return `${TILE_BASE}/{z}/{x}/{y}?session=${encodeURIComponent(session)}&key=${encodeURIComponent(apiKey)}`;
}
