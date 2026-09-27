// Community events: riders put their own events on the map (☰ → Add Event), then find them under My Events.
// Form rules, SF-time handling, host keys and the api calls. Plain TS so `node --test` can run it; the React side is
// app/host.tsx. Contract: contracts/community_event.md (Mongo `events`, source "community").
import { EVENT_KINDS, eventActive, fmtEventTime, type CommunityInfo, type EventKind, type MapEvent } from './context.ts';
import { API, ptClock, ptTime, type Place } from './route.ts';

// Pin kinds a host can pick, stored as the category that maps to that pin (context.ts KIND_BY_CATEGORY), in the
// vocabulary ingested events use. "Other" keeps the name-based guess, like any other event with no known category.
export const CATEGORY_OPTIONS: { value: string; kind: EventKind; label: string }[] = ([
  ['concert', 'music'], ['sports', 'sports'], ['festival', 'festival'], ['parade', 'parade'],
  ['conference', 'conference'], ['market', 'market'], ['community', 'community'], ['other', 'other'],
] as const).map(([value, kind]) => ({ value, kind, label: EVENT_KINDS[kind].label }));

export const TITLE_MIN = 3, TITLE_MAX = 120, DESCRIPTION_MAX = 500, PRICE_MAX = 10_000;

/** The Add Event form. Date and times are SF wall clock ("2026-10-03", "18:30"), like the rest of the app. */
export type Draft = {
  title: string;
  place: Place | null;   // a search result, or a spot picked on the map (pinned)
  pinned: boolean;
  placeName: string;     // pinned spot: what the host calls it (search results already have a name)
  date: string; start: string; end: string;
  category: string;
  admission: 'free' | 'ticketed';
  ticketUrl: string; ticketPrice: string;
  description: string; imageUrl: string;
};
export type Field = 'title' | 'place' | 'placeName' | 'date' | 'start' | 'end' | 'category' | 'ticketUrl' | 'ticketPrice' | 'imageUrl';
export type EventBody = {
  title: string; venue: string; lat: number; lon: number; start_time: string; end_time: string;
  category: string; admission: 'free' | 'ticketed'; ticket_url: string | null; ticket_price: number | null;
  description: string | null; image_url: string | null;
};

const pad = (n: number) => String(n).padStart(2, '0');
const sfDate = (ms: number) => { const [y, mo, d] = ptClock(ms); return `${y}-${pad(mo)}-${pad(d)}`; };
const sfTime = (ms: number) => { const [, , , h, mi] = ptClock(ms); return `${pad(h)}:${pad(mi)}`; };

/** Empty form: today, from the next full hour for two hours (SF time). */
export function emptyDraft(now = Date.now()): Draft {
  const start = Math.ceil((now + 60_000) / 36e5) * 36e5;
  return {
    title: '', place: null, pinned: false, placeName: '', date: sfDate(start), start: sfTime(start), end: sfTime(start + 2 * 36e5),
    category: '', admission: 'free', ticketUrl: '', ticketPrice: '', description: '', imageUrl: '',
  };
}

/** Editing: the form filled in from the event as the api returned it. */
export function draftFromEvent(e: MapEvent): Draft {
  const a = Date.parse(e.start_time), b = e.end_time ? Date.parse(e.end_time) : a + 2 * 36e5, c = e.community;
  return {
    title: e.name, place: { label: e.venue ?? e.name, sub: '', lat: e.lat, lon: e.lon }, pinned: false, placeName: '',
    date: sfDate(a), start: sfTime(a), end: sfTime(b), category: e.category ?? '',
    admission: c?.admission ?? 'free', ticketUrl: c?.ticket_url ?? '', ticketPrice: c?.ticket_price != null ? String(c.ticket_price) : '',
    description: c?.description ?? '', imageUrl: c?.image_url ?? '',
  };
}

/** SF date + start/end clock -> epoch ms. An end at or before the start is the next day (a 10 PM – 1 AM party). */
export function eventSpan(date: string, start: string, end: string): { from: number; to: number; overnight: boolean } | null {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date), s = /^(\d{2}):(\d{2})$/.exec(start), e = /^(\d{2}):(\d{2})$/.exec(end);
  if (!d || !s || !e) return null;
  const from = ptTime(+d[1], +d[2], +d[3], +s[1], +s[2]);
  const overnight = +e[1] * 60 + +e[2] <= +s[1] * 60 + +s[2];
  const to = ptTime(+d[1], +d[2], +d[3] + (overnight ? 1 : 0), +e[1], +e[2]);
  return { from, to, overnight };
}

/** http(s) links only: a ticket or image link is opened / loaded by other riders' browsers. */
export function isWebLink(v: string): boolean {
  try {
    const u = new URL(v.trim());
    return (u.protocol === 'https:' || u.protocol === 'http:') && u.hostname.includes('.');
  } catch { return false; }
}

/** Checks the form; `body` (what POST /community/events takes) only when there are no errors. */
export function validateDraft(d: Draft, now = Date.now()): { errors: Partial<Record<Field, string>>; body: EventBody | null } {
  const errors: Partial<Record<Field, string>> = {};
  const title = d.title.trim().replace(/\s+/g, ' ');
  if (!title) errors.title = 'Give your event a name.';
  else if (title.length < TITLE_MIN) errors.title = `At least ${TITLE_MIN} characters.`;
  if (!d.place) errors.place = 'Choose where it happens.';
  else if (d.pinned && !d.placeName.trim()) errors.placeName = 'Name this place, e.g. “Dolores Park, north lawn”.';
  if (!d.date) errors.date = 'Pick a date.';
  if (!d.start) errors.start = 'Pick a start time.';
  if (!d.end) errors.end = 'Pick an end time.';
  const span = !errors.date && !errors.start && !errors.end ? eventSpan(d.date, d.start, d.end) : null;
  if (span && span.to <= now) errors.end = 'This time has already passed.';
  if (!d.category) errors.category = 'Pick a category.';
  if (d.admission === 'ticketed') {
    if (!d.ticketUrl.trim()) errors.ticketUrl = 'Add the link where people get tickets.';
    else if (!isWebLink(d.ticketUrl)) errors.ticketUrl = 'Use a full web link, starting with https://';
    const p = d.ticketPrice.trim().replace(/^\$/, '');
    if (p && !(Number.isFinite(+p) && +p >= 0 && +p <= PRICE_MAX)) errors.ticketPrice = 'Enter a price in dollars, like 15.';
  }
  if (d.imageUrl.trim() && !isWebLink(d.imageUrl)) errors.imageUrl = 'Use a full web link, starting with https://';
  if (Object.keys(errors).length || !span || !d.place) return { errors, body: null };
  const ticketed = d.admission === 'ticketed', price = d.ticketPrice.trim().replace(/^\$/, '');
  return {
    errors,
    body: {
      title, venue: (d.pinned ? d.placeName : d.place.label).trim(), lat: d.place.lat, lon: d.place.lon,
      start_time: new Date(span.from).toISOString(), end_time: new Date(span.to).toISOString(),
      category: d.category, admission: d.admission,
      ticket_url: ticketed ? d.ticketUrl.trim() : null, ticket_price: ticketed && price ? +price : null,
      description: d.description.trim() || null, image_url: d.imageUrl.trim() || null,
    },
  };
}

// ---- ownership: per-event host keys (no accounts) -----------------------------------------------------------------
// POST /community/events returns the event's host key once. It is kept here, in this browser only; the api stores
// just its hash. Holding it = host controls for that event. Storage may be blocked: then nothing is remembered.
// Keys only ever travel in request bodies: never in a URL, a share link or the map's event data.
const KEY = 'tp-hosted-events';

const readJson = <T>(key: string, fallback: T, ok: (v: unknown) => boolean): T => {
  try { const v = JSON.parse(localStorage.getItem(key) ?? 'null'); return ok(v) ? v as T : fallback; } catch { return fallback; }
};
const writeJson = (key: string, v: unknown) => {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode: not remembered */ }
};
const isRecord = (v: unknown) => !!v && typeof v === 'object' && !Array.isArray(v);

export function hostKeys(): Record<string, string> {
  const v = readJson<Record<string, unknown>>(KEY, {}, isRecord);
  return Object.fromEntries(Object.entries(v).filter(([, k]) => typeof k === 'string')) as Record<string, string>;
}
export function rememberHost(id: string, key: string) { writeJson(KEY, { ...hostKeys(), [id]: key }); }
function forgetHost(id: string) { const k = hostKeys(); delete k[id]; writeJson(KEY, k); }

/** Host controls (Edit, Advertise, Delete) need BOTH: a community event, and this browser holding its key. Never the
 *  source alone, and an ingested event (PredictHQ, DataSF) can't be claimed by having a key saved under its id. */
export const isHost = (e: Pick<MapEvent, 'id' | 'source'>, keys: Record<string, string> | ReadonlySet<string>): boolean =>
  e.source === 'community' && (keys instanceof Set ? keys.has(e.id) : !!(keys as Record<string, string>)[e.id]);

// ---- Saved Events (☰ → Saved Events): any event, kept in this browser only --------------------------------------------
// Saved by id, with the event as it was when saved, so the list shows at once and offline; opening Saved Events
// refreshes what the api still lists (lookupEvents). Nothing about saving reaches the server.
const SAVED = 'tp-saved-events';
export function savedEvents(): MapEvent[] {
  return readJson<MapEvent[]>(SAVED, [], Array.isArray).filter(e => e && typeof e.id === 'string' && typeof e.name === 'string');
}
/** Save event / Unsave event. Returns the new list. */
export function toggleSaved(ev: MapEvent): MapEvent[] {
  const list = savedEvents(), next = list.some(e => e.id === ev.id) ? list.filter(e => e.id !== ev.id) : [...list, ev];
  writeJson(SAVED, next);
  return next;
}
/** Replace saved copies with the api's current ones (`fresh`); `gone` = ids the api no longer lists. */
export function refreshSaved(fresh: MapEvent[], gone: ReadonlySet<string>): MapEvent[] {
  const byId = new Map(fresh.map(e => [e.id, e]));
  const next = savedEvents().filter(e => !gone.has(e.id)).map(e => byId.get(e.id) ?? e);
  writeJson(SAVED, next);
  return next;
}
/** Saved ids the api can look up (ids from Mongo `events`); DataSF-closure events only live in the saved copy. */
export const lookupable = (id: string) => /^evt_[0-9a-f]{16}$/.test(id);

// ---- reports (review only: a report never hides or deletes anything) --------------------------------------------------
export const REPORT_REASONS = [
  { id: 'doesnt_exist', label: 'Event doesn’t exist' },
  { id: 'incorrect_info', label: 'Incorrect information' },
  { id: 'spam', label: 'Spam' },
  { id: 'inappropriate', label: 'Inappropriate' },
  { id: 'other', label: 'Other' },
] as const;
export type ReportReason = typeof REPORT_REASONS[number]['id'];
// Only so this browser shows "Reported" instead of offering it again; the report itself carries no id of any kind.
const REPORTED = 'tp-reported-events';
export const reportedIds = (): string[] => readJson<string[]>(REPORTED, [], Array.isArray).filter(x => typeof x === 'string');

// ---- the ⋯ menu on an event card -------------------------------------------------------------------------------------
export type CardAction = 'edit' | 'advertise' | 'save' | 'unsave' | 'share' | 'delete' | 'report' | 'reported';
/** What an event's ⋯ menu offers. Anyone can advertise any event that isn't over (advertising is visibility only: it
 *  doesn't make you its host and never affects routing). The host of a community event also gets Edit and Delete, and
 *  never Report; anyone else gets Report. */
export function cardActions(e: MapEvent, o: { hosted: boolean; saved: boolean; reported: boolean; now?: number }): CardAction[] {
  const save: CardAction = o.saved ? 'unsave' : 'save';
  const advertise: CardAction[] = eventStatus(e, o.now) === 'Ended' ? [] : ['advertise'];
  if (o.hosted && e.source === 'community') {
    return [...(advertise.length ? ['edit' as const] : []), ...advertise, save, 'share', 'delete'];
  }
  return [save, 'share', ...advertise, o.reported ? 'reported' : 'report'];
}
export const CARD_LABELS: Record<CardAction, string> = {
  edit: 'Edit event', advertise: 'Advertise event', save: 'Save event', unsave: 'Unsave event', share: 'Share event',
  delete: 'Delete event', report: 'Report event', reported: 'Reported',
};

// ---- sharing ---------------------------------------------------------------------------------------------------------
/** The app link that opens on this event (`?event=<id>`) for events the api can look up; otherwise just the app. No host
 *  key, ever. */
export function shareLink(e: Pick<MapEvent, 'id'>, origin: string): string {
  return lookupable(e.id) ? `${origin}/?event=${encodeURIComponent(e.id)}` : `${origin}/`;
}
export const shareText = (e: MapEvent) => [e.name, fmtEventTime(e), e.venue].filter(Boolean).join(' · ');
/** `?event=evt_…` in a shared link, if it's a valid id. */
export function sharedEventId(search: string): string | null {
  const id = new URLSearchParams(search).get('event');
  return id && lookupable(id) ? id : null;
}

// ---- api ------------------------------------------------------------------------------------------------------------
async function send<T>(method: 'POST' | 'PUT', path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg ?? `HTTP ${res.status}` : `HTTP ${res.status}`);
  }
  return res.json();
}

/** Put the event on the map; remembers its host key here. */
export async function createEvent(body: EventBody): Promise<MapEvent> {
  const { event, host_key } = await send<{ event: MapEvent; host_key: string }>('POST', '/community/events', body);
  rememberHost(event.id, host_key);
  return event;
}
/** The events this browser hosts (the api checks every key). */
export async function fetchMyEvents(keys = hostKeys()): Promise<MapEvent[]> {
  if (!Object.keys(keys).length) return [];
  return (await send<{ events: MapEvent[] }>('POST', '/community/events/mine', { keys })).events;
}
export async function updateEvent(id: string, body: EventBody): Promise<MapEvent> {
  const host_key = hostKeys()[id];
  if (!host_key) throw new Error('This browser isn’t the host of that event.');
  return (await send<{ event: MapEvent }>('PUT', `/community/events/${encodeURIComponent(id)}`, { ...body, host_key })).event;
}
/** Delete my event (the api marks it deleted); its key is forgotten here too. */
export async function deleteEvent(id: string): Promise<void> {
  const host_key = hostKeys()[id];
  if (!host_key) throw new Error('This browser isn’t the host of that event.');
  await send('POST', `/community/events/${encodeURIComponent(id)}/delete`, { host_key });
  forgetHost(id);
}
/** Events the api still lists, by id (Saved Events, shared links). */
export async function lookupEvents(ids: string[]): Promise<MapEvent[]> {
  const ok = ids.filter(lookupable);
  return ok.length ? (await send<{ events: MapEvent[] }>('POST', '/events/lookup', { ids: ok })).events : [];
}
/** Report for review: event id, reason, details. Remembered here only to show "Reported". */
export async function reportEvent(id: string, reason: ReportReason, details: string): Promise<void> {
  await send('POST', `/events/${encodeURIComponent(id)}/report`, { reason, details: details.trim() || null });
  writeJson(REPORTED, [...new Set([...reportedIds(), id])]);
}

// ---- wording ----------------------------------------------------------------------------------------------------------
export function fmtAdmission(c: CommunityInfo | null | undefined): string {
  if (!c || c.admission === 'free') return 'Free';
  return c.ticket_price != null ? `Ticketed · $${c.ticket_price % 1 ? c.ticket_price.toFixed(2) : c.ticket_price}` : 'Ticketed';
}
export const fmtPromotion = (c: CommunityInfo | null | undefined) => c?.promotion?.status === 'none' || !c ? 'Not advertised' : 'Advertised';
/** Lifecycle from the event's own times (no end time: the map's point-event rule, context.ts eventActive). */
export function eventStatus(e: MapEvent, now = Date.now()): 'Upcoming' | 'Happening now' | 'Ended' {
  const s = eventActive(e);
  if (!s) return 'Ended';
  return now >= s.to ? 'Ended' : now >= s.from ? 'Happening now' : 'Upcoming';
}
/** Where Directions goes: the event's own spot, into the app's own route planner. */
export const eventPlace = (e: MapEvent): Place => ({ label: e.venue ?? e.name, sub: e.name, lat: e.lat, lon: e.lon });

/** The map's events plus one the host just made or opened (it may start outside the trip window being shown). The
 *  freshest copy wins, so an edit shows at once. */
export const withEvent = (events: MapEvent[], ev: MapEvent | null): MapEvent[] =>
  ev ? [...events.filter(e => e.id !== ev.id), ev] : events;

// ---- promotion (next step) --------------------------------------------------------------------------------------------
// Paid in SOL later, by anyone for any event (not only its host; paying never grants host controls). The api will switch it on only after verifying the transaction on chain (succeeded, to
// the expected recipient, for the expected amount, signature not used before), never on the client's word. Promotion is
// visibility only: it never makes a community event count for /plan. Nothing here pays, signs or marks anything.
// "Coming soon" previews only: names and what each will do. No prices, no reach or impression numbers, no payment state.
export const PROMOTION_OPTIONS = [
  { id: 'boost', title: 'Boost on map', detail: 'Make this event more visible to nearby travelers.' },
  { id: 'featured', title: 'Featured event', detail: 'Appear more prominently in event discovery.' },
  { id: 'route', title: 'Route-aware promotion', detail: 'Reach travelers whose routes pass near this event.' },
  { id: 'local', title: 'Local sponsorship', detail: 'Promote this event to people exploring the surrounding area.' },
] as const;
export const PROMOTION = { payment: 'Solana', available: false } as const;
/** Host analytics to come (event details, own events only): labels only, never a made-up number. */
export const ANALYTICS_PREVIEW = ['Views', 'Saves', 'Directions', 'Ticket clicks'] as const;
