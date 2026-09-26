// Place search (Nominatim) + driving routes (OSRM) + display formatting.
// Shared by the desktop and mobile layouts. Plain TS (no enums etc.) so `node --test` can run it directly.

export type Place = { label: string; sub: string; lat: number; lon: number };
export type LatLng = [number, number];
export type Step = {
  distance: number;
  duration: number;
  name: string;
  maneuver: { type: string; modifier?: string; location: [number, number] }; // [lon, lat]
};
export type Route = { dur: number; dist: number; summary: string; coords: LatLng[]; steps: Step[] };
export type Units = 'mi' | 'km';

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

// ponytail: public Nominatim/OSRM demo servers (rate-limited, no SLA). Move to Mapbox (MAPBOX_TOKEN) via api/ for traffic-aware ETAs.
export async function searchPlaces(q: string, signal?: AbortSignal): Promise<Place[]> {
  const url = `https://nominatim.openstreetmap.org/search?format=json&limit=5&bounded=1&viewbox=-122.53,37.84,-122.35,37.70&q=${encodeURIComponent(q)}`;
  const data: { name?: string; display_name: string; lat: string; lon: string }[] = await (await fetch(url, { signal })).json();
  return data.map(d => {
    const parts = d.display_name.split(', ');
    return { label: d.name || parts[0], sub: parts.slice(1, 4).join(', '), lat: +d.lat, lon: +d.lon };
  });
}

export async function fetchRoutes(from: Place, to: Place, signal?: AbortSignal): Promise<Route[]> {
  const url = `https://router.project-osrm.org/route/v1/driving/${from.lon},${from.lat};${to.lon},${to.lat}?alternatives=3&overview=full&geometries=geojson&steps=true`;
  const data = await (await fetch(url, { signal })).json();
  if (data.code !== 'Ok' || !data.routes?.length) throw new Error(data.message || 'No route');
  return data.routes.map((r: any) => ({
    dur: r.duration, dist: r.distance, summary: r.legs[0].summary,
    coords: r.geometry.coordinates.map(([x, y]: number[]) => [y, x]), steps: r.legs[0].steps,
  }));
}

export function fmtDist(m: number, units: Units = 'mi'): string {
  if (units === 'km') return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
  const mi = m / 1609.34;
  return mi < 0.1 ? `${Math.max(50, Math.round((m * 3.281) / 50) * 50)} ft` : `${mi.toFixed(1)} mi`;
}

export const fmtTime = (sec: number, now = Date.now()) =>
  new Date(now + sec * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

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
