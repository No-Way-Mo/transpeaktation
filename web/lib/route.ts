// Place search + driving routes (via api/: Mapbox with traffic, OSRM/Nominatim fallback) + display formatting.
// Shared by the desktop and mobile layouts. Plain TS (no enums etc.) so `node --test` can run it directly.

export type Place = { label: string; sub: string; lat: number; lon: number };
export type LatLng = [number, number];
export type Step = {
  distance: number;
  duration: number;
  name: string;
  maneuver: { type: string; modifier?: string; location: [number, number] }; // [lon, lat]
};
export type Route = {
  dur: number; dist: number; summary: string; coords: LatLng[]; steps: Step[];
  dur_typical?: number | null;          // usual time without today's traffic (Mapbox only)
  congestion?: string[] | null;         // per coords pair: low | moderate | heavy | severe | unknown (Mapbox only)
  road_segment_ids?: string[] | null;   // OSM edges "u-v-key", same IDs as Mongo road_segments / Tiger metrics
};
export type Units = 'mi' | 'km';
/** When to travel: now (live traffic), leave at `at`, or arrive by `at` (epoch ms). */
export type When = { mode: 'now' | 'depart' | 'arrive'; at: number };

// ponytail: "Current location" is fixed to Union Square; swap in navigator.geolocation when we need real GPS.
export const ORIGIN: Place = { label: 'Current location', sub: 'Union Square', lat: 37.788, lon: -122.4075 };
export const RECENT: Place[] = [
  { label: 'Oracle Park', sub: '24 Willie Mays Plaza', lat: 37.7786, lon: -122.3893 },
  { label: 'Chase Center', sub: '1 Warriors Way', lat: 37.768, lon: -122.3877 },
  { label: 'Ferry Building', sub: '1 Ferry Building', lat: 37.7955, lon: -122.3937 },
];
const ARROWS: Record<string, string> = {
  left: '←', right: '→', straight: '↑', 'slight left': '↖', 'slight right': '↗',
  'sharp left': '↰', 'sharp right': '↱', uturn: '↩',
};

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API}${path}`, { signal });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `HTTP ${res.status}`);
  return res.json();
}

export async function searchPlaces(q: string, signal?: AbortSignal): Promise<Place[]> {
  return (await api<{ places: Place[] }>(`/places?q=${encodeURIComponent(q)}`, signal)).places;
}

export async function fetchRoutes(from: Place, to: Place, when: When = { mode: 'now', at: 0 }, signal?: AbortSignal): Promise<Route[]> {
  // Clamp to now: the api/ rejects past times, and a picker left open for a while drifts into the past.
  const t = when.mode === 'now' ? '' : `&${when.mode === 'depart' ? 'depart_at' : 'arrive_by'}=${encodeURIComponent(new Date(Math.max(when.at, Date.now())).toISOString())}`;
  return (await api<{ routes: Route[] }>(`/routes?from=${from.lon},${from.lat}&to=${to.lon},${to.lat}${t}`, signal)).routes;
}

export function fmtDist(m: number, units: Units = 'mi'): string {
  if (units === 'km') return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
  const mi = m / 1609.34;
  return mi < 0.1 ? `${Math.max(50, Math.round((m * 3.281) / 50) * 50)} ft` : `${mi.toFixed(1)} mi`;
}

export const fmtTime = (sec: number, now = Date.now()) =>
  new Date(now + sec * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** "7:15 PM" today, "Tomorrow 7:15 PM", otherwise "Tue 7:15 PM". */
export function fmtWhen(ms: number, now = Date.now()): string {
  const d = new Date(ms), t = fmtTime(0, ms);
  const days = Math.round((new Date(d).setHours(0, 0, 0, 0) - new Date(now).setHours(0, 0, 0, 0)) / 864e5);
  return days === 0 ? t : days === 1 ? `Tomorrow ${t}` : `${d.toLocaleDateString([], { weekday: 'short' })} ${t}`;
}

/** Equirectangular distance in metres; plenty for city-scale "is this near that". */
export function meters(a: LatLng, b: LatLng): number {
  const k = Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot(a[0] - b[0], (a[1] - b[1]) * k) * 111_320;
}

/** Where to pin route i's "12 min" label: the point of its middle stretch farthest from every other route,
 *  so labels on overlapping alternatives don't stack. */
export function labelPoint(routes: Route[], i: number): LatLng {
  const cs = routes[i].coords, others = routes.flatMap((r, j) => (j === i ? [] : r.coords));
  let best = cs[Math.floor(cs.length / 2)], bestD = -1;
  if (!others.length) return best;
  // ponytail: O(n·m) scan over every 4th point; fine for 2-3 city routes, index the others if it ever shows up.
  for (let k = Math.floor(cs.length * 0.15); k < cs.length * 0.85; k += 4) {
    let d = Infinity;
    for (const o of others) d = Math.min(d, meters(cs[k], o));
    if (d > bestD) { bestD = d; best = cs[k]; }
  }
  return best;
}

export const mins = (sec: number) => Math.max(1, Math.round(sec / 60));

export function stepText(s: Step, destination: string): string {
  const m = s.maneuver, name = s.name || 'the road';
  if (m.type === 'arrive') return `Arrive at ${destination}`;
  if (m.type === 'depart') return `Head ${m.modifier || ''} on ${name}`.replace('  ', ' ');
  if (m.type === 'roundabout' || m.type === 'rotary') return `Take the roundabout onto ${name}`;
  if (m.type === 'continue' || m.type === 'new name') return `Continue on ${name}`;
  const verb = m.type === 'merge' ? 'Merge' : m.type === 'fork' ? 'Keep' : 'Turn';
  return `${verb} ${m.modifier || ''} onto ${name}`.replace('  ', ' ');
}

export function stepArrow(s: Step): string {
  if (s.maneuver.type === 'arrive') return '■';
  if (s.maneuver.type === 'depart') return '↑';
  return ARROWS[s.maneuver.modifier ?? ''] || '↑';
}

/** Tag for a route card: the first (fastest) route vs. how much slower each alternative is. */
export function routeTag(i: number, dur: number, fastest: number): string {
  if (i === 0) return 'Fastest';
  const diff = Math.round((dur - fastest) / 60);
  return diff > 0 ? `+${diff} min` : 'Similar';
}
