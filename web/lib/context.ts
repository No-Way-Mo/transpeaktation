// Ingested event + road context (api/ /events and /road-conditions, which read what ingest/ wrote to Mongo), the
// time windows used to ask for it, and which items touch a given route. Deterministic geometry only, no model.
// Plain TS (no enums etc.) so `node --test` can run it directly.
import { api, metersToLine, sfDays, TZ, type LatLng, type Route, type When } from './route.ts';

// ---- data contract: mirrors contracts/map_context.schema.json -------------------------------------------------
export type MapEvent = {
  id: string; name: string; category: string | null; venue: string | null;
  lat: number; lon: number; start_time: string; end_time: string | null;
  source: string; status: string | null;
  road_closure_ids: string[];      // road_incidents ids closed for this event
};
export type RoadCondition = {
  id: string; kind: 'closure' | 'incident'; category: string | null; is_closure: boolean;
  description: string | null; street: string | null; status: string | null;
  lat: number; lon: number;        // representative point of `geometry`
  geometry: { type: string; coordinates: unknown };
  start_time: string | null; end_time: string | null; updated_at: string | null;
  source: string;
  road_segment_ids: string[];      // OSM edges "u-v-key", same IDs as Route.road_segment_ids
};

// ---- time windows: every "is this relevant then?" knob lives here ---------------------------------------------
// All instants are epoch ms (absolute), so no browser time zone enters the comparison; SF wall-clock time only
// matters when reading the picker and printing times (route.ts, TZ).
/** A trip's span in epoch ms: leave → arrive. */
export type Span = { from: number; to: number };
export const EVENT_LEAD_MIN = 60;  // an event matters from this long before it starts (arriving crowds)...
export const EVENT_TAIL_MIN = 60;  // ...until this long after it ends (leaving crowds)
// Point-event rule: an event with no end time is active for this long after its start, never indefinitely.
// Same rule server-side: api/app/store.py DEFAULT_EVENT_DURATION.
export const DEFAULT_EVENT_MIN = 180;
// Incident with no end time (e.g. a CHP crash): active this long after it started. Matches store.OPEN_ENDED_INCIDENT.
export const OPEN_INCIDENT_MIN = 360;
const ROUND_MS = 5 * 60_000;       // windows snap outward to 5 min so "now" doesn't refetch on every render

const snap = (s: Span): Span => ({ from: Math.floor(s.from / ROUND_MS) * ROUND_MS, to: Math.ceil(s.to / ROUND_MS) * ROUND_MS });

/** When you're on the road for a `durSec` trip: leave now, leave at `at` (not before now), or arrive by `at`. */
export function tripSpan(when: When, durSec: number, now = Date.now()): Span {
  const leave = when.mode === 'arrive' ? when.at - durSec * 1000 : when.mode === 'depart' ? Math.max(when.at, now) : now;
  return { from: leave, to: leave + durSec * 1000 };
}
/** The trip relevance window: the trip padded by crowd lead/tail. An event is relevant in time iff its active
 *  interval overlaps it. */
export const eventWindow = (trip: Span): Span => snap({ from: trip.from - EVENT_TAIL_MIN * 60_000, to: trip.to + EVENT_LEAD_MIN * 60_000 });
/** Road conditions matter only while you're on the road. */
export const conditionWindow = (trip: Span): Span => snap(trip);

const overlaps = (a: Span, b: Span) => a.from <= b.to && a.to >= b.from;
/** An event's active interval; no end time → the point-event rule. null if the start time is unreadable. */
export function eventActive(e: MapEvent): Span | null {
  const from = Date.parse(e.start_time), end = e.end_time ? Date.parse(e.end_time) : NaN;
  if (!Number.isFinite(from)) return null;
  return { from, to: Number.isFinite(end) ? end : from + DEFAULT_EVENT_MIN * 60_000 };
}
/** event.start <= windowEnd && event.end >= windowStart, with the window = eventWindow(trip). */
export function eventInTime(e: MapEvent, trip: Span): boolean {
  const a = eventActive(e);
  return !!a && overlaps(a, eventWindow(trip));
}
/** Condition active at some point during the trip. Unknown start = already active; no end = OPEN_INCIDENT_MIN after
 *  its start; neither = active (the API doesn't send undated rows today; this keeps a future one visible). */
export function conditionInTime(c: RoadCondition, trip: Span): boolean {
  const start = c.start_time ? Date.parse(c.start_time) : NaN, end = c.end_time ? Date.parse(c.end_time) : NaN;
  const from = Number.isFinite(start) ? start : -Infinity;
  const to = Number.isFinite(end) ? end : Number.isFinite(start) ? start + OPEN_INCIDENT_MIN * 60_000 : Infinity;
  return overlaps({ from, to }, trip);
}

// ---- fetching -------------------------------------------------------------------------------------------------
export const validCoord = (lat: unknown, lon: unknown): boolean =>
  typeof lat === 'number' && typeof lon === 'number' && Number.isFinite(lat) && Number.isFinite(lon)
  && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0);

const range = (w: Span) => `start=${encodeURIComponent(new Date(w.from).toISOString())}&end=${encodeURIComponent(new Date(w.to).toISOString())}`;

export async function fetchEvents(w: Span, signal?: AbortSignal): Promise<MapEvent[]> {
  const { events } = await api<{ events: MapEvent[] }>(`/events?${range(w)}`, signal);
  return (events ?? []).filter(e => e && e.name && validCoord(e.lat, e.lon));
}

export async function fetchRoadConditions(w: Span, signal?: AbortSignal): Promise<RoadCondition[]> {
  const { road_conditions } = await api<{ road_conditions: RoadCondition[] }>(`/road-conditions?${range(w)}`, signal);
  return (road_conditions ?? []).filter(c => c && validCoord(c.lat, c.lon));
}

// ---- route relevance ------------------------------------------------------------------------------------------
export const EVENT_NEAR_M = 300;     // event point (venue / centre of its closures) within this of the route line, or its impact radius if larger
export const CONDITION_NEAR_M = 40;  // no shared segment IDs: the condition must lie on the route line...
export const ALONG_SHARE = 0.5;      // ...for at least half its points, so a street or freeway that only crosses it doesn't count
// "Route 80", "I-280", "US 101": freeways are grade-separated, so a closure point on the deck above a street the route
// uses isn't on the route. Without segment IDs, those count only when a route step is on that highway.
const HIGHWAY = /^(?:route|interstate|highway|hwy|i|us|sr|ca)[\s-]*(\d+)\b/i;

export type RouteContext = { events: MapEvent[]; conditions: RoadCondition[] };
/** `null` = that feed failed to load; the route still works, we just can't say anything about it. */
export type ContextData = { events: MapEvent[] | null; conditions: RoadCondition[] | null; loading: boolean };

/** Vertices of a GeoJSON Point / LineString / MultiLineString as [lat, lon], plus each segment's midpoint. */
function samplePoints(g: RoadCondition['geometry']): LatLng[] {
  const c = g?.coordinates as unknown;
  const lines = (g?.type === 'Point' ? [[c]] : g?.type === 'LineString' ? [c] : g?.type === 'MultiLineString' ? c : []) as number[][][];
  const out: LatLng[] = [];
  for (const line of lines) line.forEach((p, i) => {
    if (!validCoord(p?.[1], p?.[0])) return;
    out.push([p[1], p[0]]);
    const q = line[i + 1];
    if (q && validCoord(q[1], q[0])) out.push([(p[1] + q[1]) / 2, (p[0] + q[0]) / 2]);
  });
  return out;
}

/** Ingested events relevant to route `r` driven over `trip`: an event must be near the route AND overlap the trip
 *  relevance window; a condition must be on the route AND active during the trip. The API already filters by time;
 *  this re-checks per route, so a wider or stale fetch can never make an off-time event count.
 *  Conditions match on shared OSM segment IDs when both sides have them (exact), else when most of the condition's
 *  shape lies along the route line. */
export function routeContext(r: Route, events: MapEvent[], conditions: RoadCondition[], trip: Span): RouteContext {
  const onRoute = (p: LatLng, m: number) => metersToLine(p, r.coords) <= m;
  const along = (c: RoadCondition) => {
    const hw = c.street?.match(HIGHWAY)?.[1];
    if (hw && !r.steps.some(st => new RegExp(`\\b${hw}\\b`).test(st.name))) return false;
    const pts = samplePoints(c.geometry);
    if (!pts.length) return onRoute([c.lat, c.lon], CONDITION_NEAR_M);
    return pts.filter(p => onRoute(p, CONDITION_NEAR_M)).length >= pts.length * ALONG_SHARE;
  };
  const segs = new Set(r.road_segment_ids ?? []);
  return {
    events: events.filter(e => eventInTime(e, trip) && onRoute([e.lat, e.lon], Math.max(EVENT_NEAR_M, eventImpact(e).radius_m))),
    conditions: conditions.filter(c => conditionInTime(c, trip) && (segs.size && c.road_segment_ids?.length
      ? c.road_segment_ids.some(id => segs.has(id))
      : along(c))),
  };
}

// ---- wording (facts only: no delay minutes until ml/ forecasts exist) ------------------------------------------
export const NO_EVENTS = 'No events on your way at this time.';

const sfDay = (ms: number) => new Date(ms).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: TZ });
const sfClock = (ms: number) => new Date(ms).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ });

/** An event's span in SF time with explicit dates, so a multi-day or past-day event can't read as "this week":
 *  "Wed, Sep 23, 6:00 AM – Fri, Oct 2, 6:00 PM", or "Sat, Sep 26, 10:00 AM – 4:00 PM" within one day. */
export function fmtEventTime(e: MapEvent): string {
  const a = Date.parse(e.start_time), b = e.end_time ? Date.parse(e.end_time) : NaN;
  if (!Number.isFinite(a)) return '';
  const start = `${sfDay(a)}, ${sfClock(a)}`;
  if (!Number.isFinite(b)) return `${start} (no end time listed)`;
  return `${start} – ${sfDays(b, a) === 0 ? '' : `${sfDay(b)}, `}${sfClock(b)}`;
}

/** "special_event" → "Special event". */
export const fmtCategory = (c: string | null) => c ? (c[0].toUpperCase() + c.slice(1)).replace(/_/g, ' ') : '';

// ---- event kind: what the map pin looks like -------------------------------------------------------------------
// Every DataSF event arrives as category "special_event", so the category alone can't tell a farmers market from
// Dreamforce. A real category (Ticketmaster / PredictHQ) wins; otherwise the name decides. First match wins, so the
// order matters: "Portola Music Festival" is music, "Block-Tober Fest" is a block party, "Tech Street Festival" a festival.
export type EventKind = 'music' | 'sports' | 'parade' | 'market' | 'community' | 'festival' | 'conference' | 'other';
/** Pin label, whether it's a big draw (drawn larger) or a small local one (drawn small and muted), and a typical
 *  crowd for one closed block of it (a guess for SF: Portola, Folsom St Fair, Dreamforce vs. a street's block party). */
export const EVENT_KINDS: Record<EventKind, { label: string; big: boolean; crowd: number }> = {
  music: { label: 'Music', big: true, crowd: 12_000 },
  sports: { label: 'Sports', big: true, crowd: 5_000 },
  festival: { label: 'Festival', big: true, crowd: 8_000 },
  parade: { label: 'Parade', big: true, crowd: 8_000 },
  conference: { label: 'Conference', big: true, crowd: 5_000 },
  market: { label: 'Market', big: false, crowd: 1_500 },
  community: { label: 'Community', big: false, crowd: 150 },
  other: { label: 'Other', big: false, crowd: 500 },
};
// 24×24 stroke glyphs (static strings, never data), drawn white inside the kind's coloured disc. One set for the
// legend and both pin styles (app/map-view.tsx, app/snapmap-layers.ts); colours are --ev-<kind> in app/globals.css.
const GLYPHS: Record<EventKind, string> = {
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  sports: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.7V17c0 .6-.5 1-1 1.2C7.9 18.8 7 20.2 7 22M14 14.7V17c0 .6.5 1 1 1.2 1.1.6 2 2 2 3.8M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
  parade: '<path d="M4 22V3M4 4h14l-3 4.5L18 13H4"/>',
  festival: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9Z"/>',
  conference: '<path d="M3 4h18M4 4v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4M12 16v4M8 21l4-1 4 1"/>',
  market: '<path d="M3 9h18l-1.5 11h-15ZM8 9l4-6 4 6M9 13v4M15 13v4"/>',
  community: '<path d="M3 11 12 3l9 8M5 9.5V21h14V9.5M10 21v-6h4v6"/>',
  other: '<circle cx="12" cy="12" r="3.5"/>',
};
export const eventGlyph = (k: EventKind) => `<svg viewBox="0 0 24 24" aria-hidden="true">${GLYPHS[k]}</svg>`;
const KIND_BY_CATEGORY: Record<string, EventKind> = {
  concert: 'music', concerts: 'music', music: 'music', performing_arts: 'music',
  sports: 'sports', sport: 'sports', festival: 'festival', festivals: 'festival', community: 'community',
  conference: 'conference', conferences: 'conference', expo: 'conference', expos: 'conference', parade: 'parade',
};
const KIND_BY_NAME: [EventKind, RegExp][] = [
  ['music', /\bmusic\b|concert|symphony|opera|\bjazz\b|\bdj\b/i],
  ['sports', /\bsports?\b|\bgame\b|tournament|marathon|\brace\b|\bbike\b|\b\d+k\b|cornhole|giants|warriors|49ers/i],
  ['parade', /parade|fleet week|procession|blessing|sunday streets/i],
  ['market', /market/i],
  ['community', /block part|trick.?or.?treat|treat or treat|halloween|street party|barbe?cue|\bbbq\b|picnic|feast|wedding/i],
  ['festival', /festival|\bfest\b|\bfesta\b|oktoberfest|street fair|\bfair\b|fiesta|carnival|celebration/i],
  ['conference', /conference|summit|dreamforce|unboxed|corporate|convention|\bexpo\b|\bgala\b/i],
];
export function eventKind(e: Pick<MapEvent, 'name' | 'category'>): EventKind {
  const byCat = e.category && KIND_BY_CATEGORY[e.category.toLowerCase()];
  if (byCat) return byCat;
  return KIND_BY_NAME.find(([, re]) => re.test(e.name))?.[0] ?? 'other';
}

// ---- impact area: how far out an event's crowd is likely to slow traffic ---------------------------------------
// No feed gives attendance yet (DataSF permits don't), so the crowd is estimated: the kind's typical crowd, scaled by
// how many street blocks the permit closes (^0.75: more blocks = more people, a bit less than proportionally).
// The radius grows with sqrt(crowd), i.e. the area grows with the crowd. Heuristic, not a forecast: say "est." in UI.
export const IMPACT_MIN_M = 150;
export const IMPACT_MAX_M = 1200;
export type EventImpact = { crowd: number; radius_m: number };
export function eventImpact(e: Pick<MapEvent, 'name' | 'category' | 'road_closure_ids'>): EventImpact {
  const blocks = Math.max(1, e.road_closure_ids?.length ?? 0);
  const crowd = EVENT_KINDS[eventKind(e)].crowd * blocks ** 0.75;
  const radius_m = Math.min(IMPACT_MAX_M, Math.max(IMPACT_MIN_M, 100 + 120 * Math.sqrt(crowd / 1000)));
  return { crowd, radius_m };
}
/** "~8,000 people": two significant figures, it's an estimate. */
export function fmtCrowd(n: number): string {
  const k = 10 ** Math.max(0, Math.floor(Math.log10(Math.max(n, 1))) - 1);
  return `~${(Math.round(n / k) * k).toLocaleString('en-US')} people`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function contextNote(ctx: RouteContext | null, data: ContextData): string {
  if (data.loading) return 'Checking events on your way…';
  if (!ctx || (data.events === null && data.conditions === null)) return "Couldn't check events on your way right now.";
  const { events, conditions } = ctx;
  const closures = conditions.filter(c => c.is_closure), incidents = conditions.length - closures.length;
  const parts: string[] = [];
  if (data.events === null) parts.push("Couldn't check events on your way right now.");
  else if (!events.length) parts.push(NO_EVENTS);
  else if (events.length === 1) parts.push(`${events[0].name} (${fmtEventTime(events[0])}) is near your route and may affect traffic.`);
  else parts.push(`${events.length} events near your route may affect traffic: ${events.slice(0, 2).map(e => e.name).join(', ')}${events.length > 2 ? ' and more' : ''}.`);
  if (closures.length) {
    const streets = [...new Set(closures.map(c => c.street).filter(Boolean))].slice(0, 2).join(', ');
    parts.push(`${plural(closures.length, 'road closure')} on your route${streets ? ` (${streets})` : ''}.`);
  }
  if (incidents) parts.push(`${plural(incidents, 'reported incident')} on your route.`);
  return parts.join(' ');
}

/** Short tag for the transPEAKtation card. */
export function contextTag(ctx: RouteContext | null, data: ContextData): string {
  if (data.loading || !ctx) return 'Fastest';
  if (ctx.events.length) return plural(ctx.events.length, 'event') + ' nearby';
  if (ctx.conditions.some(c => c.is_closure)) return 'Road closure';
  return data.events === null ? 'Fastest' : 'Clear';
}
