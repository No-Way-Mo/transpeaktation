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
  // Not in the contract yet: no feed or model produces an impact radius today. If api/ starts sending one, the map
  // uses it instead of DEFAULT_EVENT_RADIUS_METERS (eventRadius) with no other change.
  impactRadiusMeters?: number | null;
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
export const EVENT_NEAR_M = 300;     // event point (venue / centre of its closures) within this of the route line, or its impact radius (eventRadius) if larger
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
    events: events.filter(e => eventInTime(e, trip) && onRoute([e.lat, e.lon], Math.max(EVENT_NEAR_M, eventRadius(e).meters))),
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

// ---- event category: only in an event's detail card ------------------------------------------------------------
// The map pin is the same for every event (it only says "an event is happening here"). The category shown on click is
// the API's own `category`, never guessed from the name; its icon/colour come from that value alone. DataSF permits
// all arrive as "special_event", which has no icon of its own.
export type EventKind = 'music' | 'sports' | 'parade' | 'market' | 'community' | 'festival' | 'conference' | 'other';
const KIND_BY_CATEGORY: Record<string, EventKind> = {
  concert: 'music', concerts: 'music', music: 'music', performing_arts: 'music',
  sports: 'sports', sport: 'sports', festival: 'festival', festivals: 'festival', community: 'community',
  conference: 'conference', conferences: 'conference', expo: 'conference', expos: 'conference', parade: 'parade',
  market: 'market', markets: 'market',
};
export const categoryKind = (category: string | null): EventKind => (category && KIND_BY_CATEGORY[category.toLowerCase()]) || 'other';

// ---- impact area --------------------------------------------------------------------------------------------------
/** VISUALIZATION DEFAULT, NOT A PREDICTION. /events carries no impact radius and no model produces one yet, so every
 *  event gets this same circle (no per-category sizes: we don't know them). A real per-event value
 *  (event.impactRadiusMeters from api/) replaces it through eventRadius without touching the map. UI wording:
 *  "Estimated event impact area". */
export const DEFAULT_EVENT_RADIUS_METERS = 500;
export type EventRadius = { meters: number; source: 'api' | 'default' };
export function eventRadius(e: Pick<MapEvent, 'impactRadiusMeters'>): EventRadius {
  const m = e.impactRadiusMeters;
  return typeof m === 'number' && Number.isFinite(m) && m > 0 ? { meters: m, source: 'api' } : { meters: DEFAULT_EVENT_RADIUS_METERS, source: 'default' };
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
