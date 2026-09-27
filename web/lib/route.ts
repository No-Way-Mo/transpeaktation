// Place search + the trip plan (via api/: routes, stored events/closures/traffic, model) + display formatting.
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
  by?: 'ml';                            // ml/'s own route (not one of the provider's): transPEAKtation card only
};
export type Units = 'mi' | 'km';
/** When to travel: now (live traffic), leave at `at`, or arrive by `at` (epoch ms). */
export type When = { mode: 'now' | 'depart' | 'arrive'; at: number };

/** The app is SF-only, so every clock time shown or entered is Pacific time, whatever zone the device is in. */
export const TZ = 'America/Los_Angeles';
const PT = new Intl.DateTimeFormat('en-US', { timeZone: TZ, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric' });
/** SF wall clock at `ms`: [year, month 1-12, day, hour, minute]. */
export function ptClock(ms: number): number[] {
  const f = Object.fromEntries(PT.formatToParts(ms).map(p => [p.type, +p.value]));
  return [f.year, f.month, f.day, f.hour, f.minute];
}
/** Epoch ms of an SF wall-clock time. Days past the month end roll over (Date.UTC does); DST-correct. */
export function ptTime(y: number, mo: number, d: number, h: number, mi: number): number {
  const wall = Date.UTC(y, mo - 1, d, h, mi);
  const offset = (ms: number) => { const [Y, M, D, H, Mi] = ptClock(ms); return Date.UTC(Y, M - 1, D, H, Mi) - Math.floor(ms / 60000) * 60000; };
  return wall - offset(wall - offset(wall)); // 2nd pass: the offset at the answer, not at the guess
}
/** datetime-local value ("2026-09-26T18:30") <-> epoch ms, both in SF time. */
export const ptInput = (ms: number) => {
  const [y, mo, d, h, mi] = ptClock(ms), p = (n: number) => String(n).padStart(2, '0');
  return `${y}-${p(mo)}-${p(d)}T${p(h)}:${p(mi)}`;
};
export const fromPtInput = (v: string): number | null => {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(v);
  return m ? ptTime(+m[1], +m[2], +m[3], +m[4], +m[5]) : null;
};

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

/** One route's event-aware estimate from api/ /plan (seconds). */
export type Prediction = {
  dur: number; delay: number; events: string[];
  breakdown: { events_sec: number; incidents_sec: number; traffic_sec: number };
  incidents: { label: string; is_closure: boolean; source: string; at: string; until: string | null }[];
  traffic: { delay_sec: number; slow_segments: number; coverage: number; as_of: string | null; sources: string[] };
  model: string; blocked: boolean;
  /** api/'s own event/closure estimate for this route; shown on the normal cards, never on transPEAKtation's. */
  estimate?: { dur: number; delay: number; why: string[] };
  /** Normal card only, ≤110 chars (2 lines): the congestion on this route when you'd drive it, and how much slower it is than transPEAKtation's. */
  note?: string | null;
};
/** Route reward (api/app/rewards.py): completing the trip on the recommended route (`route` = plan.best) earns
 *  `sol` (devnet), claimed after arrival. Only offered on a logged trip. */
export type RewardOffer = { route: number; lamports: number; sol: number };
/** A claimed reward: paid, too_soon (arrived implausibly fast after departing) or failed. */
export type Reward = {
  status: 'paid' | 'too_soon' | 'failed'; lamports: number; sol: number; wallet: string;
  signature: string | null; explorer: string | null;
};
/** transPEAKtation's pick across the candidate routes, with the explanation and a better departure time if any. */
export type TransPeak = {
  best: number; preds: Prediction[]; tag: string; note: string;
  advice: { depart_at: string; saves_sec: number; text: string } | null;
  reward?: RewardOffer | null;
};
/** An event as the search suggestions show it (api/ /events): SF-local clock times [h, m]. */
export type EventInfo = {
  id: string; venue: string; keys: string[]; title: string; time: string; start: [number, number] | null;
  lat: number; lon: number; crowd: { from: [number, number]; to: [number, number]; delay: number };
  drop?: { label: string; lat: number; lon: number; why: string; badge: string }; source: 'mongo' | 'demo';
};
export type Plan = {
  routes: Route[]; source: string; plan: TransPeak; events: EventInfo[];
  // Where each input came from, for the moment `at` (traffic: tiger:live | tiger:observed | tiger:typical | unavailable)
  // decision: ml:<model> when ml/ picked, else heuristic (with why ml/ wasn't used)
  // note: who wrote the card (gemini:<model> | ml | template (why)); stored: trips | off (rider's switch) | replay
  // trip_record: exactly what was logged to Mongo trips, or null
  data: { at: string; replay: boolean; events: string; incidents: string; traffic: string; predictions: string; decision: string;
    note: string; stored: 'trips' | 'off' | 'replay'; trip_record: Record<string, unknown> | null };
};

/** Demo mode (NEXT_PUBLIC_REPLAY=1): past times are allowed and replay the data stored for then. */
export const REPLAY = process.env.NEXT_PUBLIC_REPLAY === '1';

/** /plan's query. Past times are clamped to now (the api rejects them, and a picker left open drifts into the
 *  past), except in replay mode, where a past time asks the api to simulate that moment. */
export function planPath(from: Place, to: Place, when: When, now = Date.now(), replay = REPLAY): string {
  const past = when.mode !== 'now' && when.at < now && replay;
  const t = when.mode === 'now' ? '' : `&${when.mode === 'depart' ? 'depart_at' : 'arrive_by'}=${encodeURIComponent(new Date(past ? when.at : Math.max(when.at, now)).toISOString())}`;
  return `/plan?from=${from.lon},${from.lat}&to=${to.lon},${to.lat}${t}${past ? '&replay=true' : ''}`;
}

/** GET /plan: candidate routes + what ingest/ stored for their road segments at that time + the model's pick.
 *  `extra` = the rider's privacy switches as query params (lib/privacy.ts privacyQuery). */
export async function fetchPlan(from: Place, to: Place, when: When = { mode: 'now', at: 0 }, signal?: AbortSignal, extra = ''): Promise<Plan> {
  return api<Plan>(planPath(from, to, when) + extra, signal);
}

/** Inside the iOS app (ios/WebView.swift): native GPS watches for arrival. Post the destination {lat, lon} to start,
 *  null to stop; the app fires a `tp-arrived` window event when the rider gets there. Undefined in a browser. */
export const iosArrival = () => (globalThis as { webkit?: { messageHandlers?: { arrival?: { postMessage(m: unknown): void } } } })
  .webkit?.messageHandlers?.arrival;

/** POST /trips/{id}/arrived: the rider reached the destination, so the logged trip stops counting as demand. */
export async function markArrived(tripId: string): Promise<void> {
  const res = await fetch(`${API}/trips/${tripId}/arrived`, { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

/** POST /trips/{id}/reward: after arriving on the recommended route (`route`), pay its reward to `wallet` now. */
export async function claimReward(tripId: string, wallet: string, route: number): Promise<Reward> {
  const res = await fetch(`${API}/trips/${tripId}/reward`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ wallet, route }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `HTTP ${res.status}`);
  return res.json();
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

/** Spoken time (SF clock) -> the next time it happens (epoch ms). No am/pm: whichever of the two comes next. */
export function spokenTime(t: string, now = Date.now()): number | null {
  const m = /^(\d{1,2})(?::(\d{2}))?\s*(?:([ap])\.?\s?m\.?)?$/i.exec(t.trim());
  if (!m) return null;
  if (+m[1] > 12 || +(m[2] ?? 0) > 59) return null;
  const h = +m[1] % 12, min = +(m[2] ?? 0), ap = m[3]?.toLowerCase();
  const [y, mo, d] = ptClock(now);
  const at = (hour: number) => {
    const t = ptTime(y, mo, d, hour, min);
    return t > now ? t : ptTime(y, mo, d + 1, hour, min);
  };
  return ap ? at(h + (ap === 'p' ? 12 : 0)) : Math.min(at(h), at(h + 12));
}

/** One line on the route screen saying what voice did. Voice only plans; booking always needs a tap (AGENTS.md). */
export function voiceNote(v: VoiceIntent): string {
  if (v.destination && !v.destination.place) return `Couldn't find "${v.destination.query}". Try another name.`;
  if (!v.transcript.trim()) return "Didn't catch that. Try again, a little closer to the mic.";
  if (!v.destination?.place) return `Heard "${v.transcript}". Try "Take me to Oracle Park".`;
  return `You said "${v.transcript}".` + (v.action === 'plan_and_book' ? ' Pick a route, then confirm to book.' : '');
}

/** Why a voice request failed, in words the rider can act on. Errors come from sendVoice (api/'s `detail`) or fetch. */
export function voiceError(e: unknown): string {
  if (e instanceof TypeError) return "Can't reach the server. Check your connection and try again."; // fetch network failure
  const msg = e instanceof Error ? e.message : '';
  if (msg.startsWith('voice unavailable')) return "Voice isn't set up on this server yet. Type your destination instead.";
  if (msg === 'audio too long') return 'That was too long. Keep it to a few seconds.';
  if (msg.startsWith('speech-to-text unavailable')) return 'Speech service is busy. Try again in a moment.';
  return "Couldn't understand that. Try again.";
}

export function fmtDist(m: number, units: Units = 'mi'): string {
  if (units === 'km') return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
  const mi = m / 1609.34;
  return mi < 0.1 ? `${Math.max(50, Math.round((m * 3.281) / 50) * 50)} ft` : `${mi.toFixed(1)} mi`;
}

/** Whole SF calendar days from `now` to `ms` (0 = same SF day). */
export function sfDays(ms: number, now: number): number {
  const day = (x: number) => { const [y, mo, d] = ptClock(x); return Date.UTC(y, mo - 1, d); };
  return Math.round((day(ms) - day(now)) / 864e5);
}

export const fmtTime = (sec: number, now = Date.now()) =>
  new Date(now + sec * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: TZ });

/** "7:15 PM" today, "Tomorrow 7:15 PM", otherwise "Tue 7:15 PM" (SF time). */
export function fmtWhen(ms: number, now = Date.now()): string {
  const t = fmtTime(0, ms), days = sfDays(ms, now);
  return days === 0 ? t : days === 1 ? `Tomorrow ${t}` : `${new Date(ms).toLocaleDateString([], { weekday: 'short', timeZone: TZ })} ${t}`;
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
/** A normal route's card when api/'s estimate says it will take a minute or more longer than the provider's ETA:
 *  the tag and a line saying why. null = nothing to warn about. */
export function longerThanItLooks(pred: Prediction | undefined): string | null {
  const est = pred?.estimate;
  if (pred?.blocked) return 'Closure ahead';
  // no named event or closure behind the delay: it is ml/'s traffic forecast, not an event
  return est && est.delay >= 60 ? `+${mins(est.delay)} min ${est.why.length ? 'events' : 'predicted'}` : null;
}

export function routeTag(i: number, dur: number, fastest: number): string {
  if (i === 0) return 'Fastest';
  const diff = Math.round((dur - fastest) / 60);
  return diff > 0 ? `+${diff} min` : 'Similar';
}
