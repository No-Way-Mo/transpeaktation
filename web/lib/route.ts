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
// Turn arrow rotation (degrees clockwise from straight ahead) per maneuver modifier.
const ANGLES: Record<string, number> = {
  straight: 0, 'slight right': 45, right: 90, 'sharp right': 135, 'slight left': -45, left: -90, 'sharp left': -135,
};

const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
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

/** POST /voice: what the user said, parsed into a trip. Places are already resolved (place = null if not found). */
export type VoiceIntent = {
  transcript: string;
  action: 'plan' | 'plan_and_book' | 'unknown';
  destination: { query: string; place: Place | null } | null;
  origin: { query: string; place: Place | null } | null;
  time: string | null;                       // as spoken, e.g. "6:30" or "7:00 PM"
  time_mode: 'depart' | 'arrive' | null;     // "at 6:30" vs "by 7 pm"
};

export async function sendVoice(audio: Blob, signal?: AbortSignal): Promise<VoiceIntent> {
  const body = new FormData();
  body.append('audio', audio, `speech.${audio.type.includes('mp4') ? 'm4a' : 'webm'}`);
  const res = await fetch(`${API}/voice`, { method: 'POST', body, signal });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `HTTP ${res.status}`);
  return res.json();
}

/** Spoken time -> the next time it happens in SF (epoch ms). No am/pm: whichever of the two comes next. */
export function spokenTime(t: string, now = Date.now()): number | null {
  const m = /^(\d{1,2})(?::(\d{2}))?\s*(?:([ap])\.?\s?m\.?)?$/i.exec(t.trim());
  if (!m) return null;
  if (+m[1] > 12 || +(m[2] ?? 0) > 59) return null;
  const h = +m[1] % 12, min = +(m[2] ?? 0), ap = m[3]?.toLowerCase();
  const pad = (n: number) => String(n).padStart(2, '0');
  const at = (hour: number) => {
    const today = toSfLocal(now).slice(0, 10), clock = `T${pad(hour)}:${pad(min)}`;
    const t = fromSfLocal(today + clock);
    return t > now ? t : fromSfLocal(new Date(Date.parse(`${today}T00:00Z`) + 864e5).toISOString().slice(0, 10) + clock);
  };
  return ap ? at(h + (ap === 'p' ? 12 : 0)) : Math.min(at(h), at(h + 12));
}

/** One line on the route screen saying what voice did. Voice only plans; booking always needs a tap (AGENTS.md). */
export function voiceNote(v: VoiceIntent): string {
  if (v.destination && !v.destination.place) return `Couldn't find "${v.destination.query}". Try another name.`;
  if (!v.destination?.place) return `Heard "${v.transcript}". Try "Take me to Oracle Park".`;
  return `You said "${v.transcript}".` + (v.action === 'plan_and_book' ? ' Pick a route, then confirm to book.' : '');
}

export function fmtDist(m: number, units: Units = 'mi'): string {
  if (units === 'km') return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
  const mi = m / 1609.34;
  return mi < 0.1 ? `${Math.max(50, Math.round((m * 3.281) / 50) * 50)} ft` : `${mi.toFixed(1)} mi`;
}

// Every trip and event time is San Francisco wall-clock time, whatever time zone the browser is in: "arrive by
// 2:00 PM" means 2 PM in SF, and an SF event's day never shifts because the viewer is in New York.
export const SF_TZ = 'America/Los_Angeles';
const sfParts = new Intl.DateTimeFormat('en-US', {
  timeZone: SF_TZ, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
});

/** Epoch ms → SF wall-clock "YYYY-MM-DDTHH:mm" (the datetime-local input format). */
export function toSfLocal(ms: number): string {
  const p = Object.fromEntries(sfParts.formatToParts(ms).map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** SF wall-clock "YYYY-MM-DDTHH:mm" → epoch ms (NaN if malformed). DST-safe: the offset is re-read at the guess. */
export function fromSfLocal(s: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(s);
  if (!m) return NaN;
  const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  let t = wall;
  for (let i = 0; i < 2; i++) t = wall - (Date.parse(`${toSfLocal(t)}Z`) - t);
  return t;
}

/** Whole SF calendar days from `now` to `ms` (0 = same SF day). */
export const sfDays = (ms: number, now: number) =>
  Math.round((Date.parse(toSfLocal(ms).slice(0, 10)) - Date.parse(toSfLocal(now).slice(0, 10))) / 864e5);

export const fmtTime = (sec: number, now = Date.now()) =>
  new Date(now + sec * 1000).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: SF_TZ });

/** "7:15 PM" today, "Tomorrow 7:15 PM", otherwise "Tue 7:15 PM" (SF time). */
export function fmtWhen(ms: number, now = Date.now()): string {
  const t = fmtTime(0, ms), days = sfDays(ms, now);
  return days === 0 ? t : days === 1 ? `Tomorrow ${t}` : `${new Date(ms).toLocaleDateString('en-US', { weekday: 'short', timeZone: SF_TZ })} ${t}`;
}

/** Equirectangular distance in metres; plenty for city-scale "is this near that". */
export function meters(a: LatLng, b: LatLng): number {
  const k = Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot(a[0] - b[0], (a[1] - b[1]) * k) * 111_320;
}

/** Metres from p to segment a–b (flat-earth, fine at city scale). Mapbox lines only have vertices at bends, so
 *  distance to vertices alone would call the middle of a long straight "far" from its own neighbour. */
export function segMeters(p: LatLng, a: LatLng, b: LatLng): number {
  const k = Math.cos((p[0] * Math.PI) / 180);
  const [bx, by, px, py] = [(b[1] - a[1]) * k, b[0] - a[0], (p[1] - a[1]) * k, p[0] - a[0]];
  const t = Math.max(0, Math.min(1, (px * bx + py * by) / (bx * bx + by * by || 1)));
  return Math.hypot(px - t * bx, py - t * by) * 111_320;
}

/** Metres from p to the nearest point of a polyline. */
export function metersToLine(p: LatLng, line: LatLng[]): number {
  if (line.length === 1) return meters(p, line[0]);
  let d = Infinity;
  for (let j = 1; j < line.length; j++) d = Math.min(d, segMeters(p, line[j - 1], line[j]));
  return d;
}

/** Where to pin route i's "12 min" label: the point of its middle stretch farthest from every other route,
 *  so labels on overlapping alternatives don't stack. */
export function labelPoint(routes: Route[], i: number): LatLng {
  const cs = routes[i].coords, others = routes.filter((_, j) => j !== i).map(r => r.coords);
  let best = cs[Math.floor(cs.length / 2)], bestD = -1;
  if (!others.length) return best;
  // ponytail: O(n·m) scan over every 4th point; fine for 2-3 city routes, index the others if it ever shows up.
  for (let k = Math.floor(cs.length * 0.15); k < cs.length * 0.85; k += 4) {
    let d = Infinity;
    for (const o of others) for (let j = 1; j < o.length; j++) d = Math.min(d, segMeters(cs[k], o[j - 1], o[j]));
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

/** Icon for a turn: an arrow rotated to the turn, a U-turn, or the arrival flag. */
export function stepIcon(s: Step): { name: 'arrow' | 'uturn' | 'flag'; rotate: number } {
  if (s.maneuver.type === 'arrive') return { name: 'flag', rotate: 0 };
  if (s.maneuver.modifier === 'uturn') return { name: 'uturn', rotate: 0 };
  return { name: 'arrow', rotate: s.maneuver.type === 'depart' ? 0 : ANGLES[s.maneuver.modifier ?? ''] ?? 0 };
}

export type Slow = 'moderate' | 'heavy' | 'severe';
/** Stretches of the route slower than free-flow, merged per level, for colouring over the route line. */
export function trafficRuns(r: Route): { level: Slow; coords: LatLng[] }[] {
  const out: { level: Slow; coords: LatLng[] }[] = [];
  let cur: (typeof out)[number] | null = null;
  (r.congestion ?? []).forEach((lvl, k) => {
    const next = r.coords[k + 1];
    if (!next || (lvl !== 'moderate' && lvl !== 'heavy' && lvl !== 'severe')) { cur = null; return; }
    if (cur?.level === lvl) cur.coords.push(next);
    else out.push((cur = { level: lvl, coords: [r.coords[k], next] }));
  });
  return out;
}

/** Tag for a route card: the first (fastest) route vs. how much slower each alternative is. */
export function routeTag(i: number, dur: number, fastest: number): string {
  if (i === 0) return 'Fastest';
  const diff = Math.round((dur - fastest) / 60);
  return diff > 0 ? `+${diff} min` : 'Similar';
}
