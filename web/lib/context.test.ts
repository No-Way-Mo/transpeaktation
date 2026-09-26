import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  contextNote, contextTag, DEFAULT_EVENT_MIN, eventWindow, conditionWindow, fetchEvents, fmtCategory, fmtEventTime, NO_EVENTS,
  routeContext, tripSpan, validCoord, type ContextData, type MapEvent, type RoadCondition,
} from './context.ts';
import { fromSfLocal, type LatLng, type Route } from './route.ts';

// Union Square → Oracle Park-ish: straight line down 3rd St.
const coords: LatLng[] = [[37.788, -122.4015], [37.7786, -122.3893]];
const route: Route = { dur: 600, dist: 1500, summary: '3rd St', coords, steps: [], road_segment_ids: ['1-2-0', '2-3-0'] };
// A trip inside the fixture events' default time (2026-09-27 00:00-03:00Z); spatial tests use it.
const TRIP = { from: Date.parse('2026-09-27T01:00:00Z'), to: Date.parse('2026-09-27T01:10:00Z') };

const ev = (id: string, lat: number, lon: number, extra: Partial<MapEvent> = {}): MapEvent => ({
  id, name: `Event ${id}`, category: 'special_event', venue: null, lat, lon,
  start_time: '2026-09-27T00:00:00Z', end_time: '2026-09-27T03:00:00Z', source: 'street_closures', status: 'Permitted',
  road_closure_ids: [], ...extra,
});
const cond = (id: string, lat: number, lon: number, extra: Partial<RoadCondition> = {}): RoadCondition => ({
  id, kind: 'closure', category: 'street_closure', is_closure: true, description: null, street: 'Hubbell St', status: null,
  lat, lon, geometry: { type: 'Point', coordinates: [lon, lat] }, start_time: null, end_time: null, updated_at: null,
  source: 'street_closures', road_segment_ids: [], ...extra,
});
const ready: ContextData = { events: [], conditions: [], loading: false };

test('windows: events padded by lead/tail, conditions = the trip, both snapped outward to 5 min', () => {
  const t = Date.UTC(2026, 8, 27, 0, 32), trip = { from: t, to: t + 20 * 60_000 };
  assert.deepEqual(eventWindow(trip), { from: Date.UTC(2026, 8, 26, 23, 30), to: Date.UTC(2026, 8, 27, 1, 55) });
  assert.deepEqual(conditionWindow(trip), { from: Date.UTC(2026, 8, 27, 0, 30), to: Date.UTC(2026, 8, 27, 0, 55) });
});

test('routeContext: events within 300 m of the line, conditions by shared segment id else on-route midpoint', () => {
  const mid: LatLng = [(coords[0][0] + coords[1][0]) / 2, (coords[0][1] + coords[1][1]) / 2];
  const ctx = routeContext(route,
    [ev('near', mid[0] + 0.001, mid[1]), ev('far', 37.76, -122.45)],
    [cond('seg', 37.70, -122.50, { road_segment_ids: ['2-3-0'] }),   // far away but same OSM edge: counts
      cond('segmiss', mid[0], mid[1], { road_segment_ids: ['9-9-0'] }), // on the line, different edge: exact wins
      cond('geo', mid[0], mid[1]),                                        // no ids: on the line
      cond('geofar', mid[0] + 0.002, mid[1])], TRIP);                     // no ids: ~220 m off
  assert.deepEqual(ctx.events.map(e => e.id), ['near']);
  assert.deepEqual(ctx.conditions.map(c => c.id), ['seg', 'geo']);
});

test('routeContext: a line crossing the route (freeway overhead, cross street) is not "on" it; one along it is', () => {
  const mid: LatLng = [(coords[0][0] + coords[1][0]) / 2, (coords[0][1] + coords[1][1]) / 2];
  const line = (pts: LatLng[]) => ({ type: 'LineString', coordinates: pts.map(([la, lo]) => [lo, la]) });
  const crossing = cond('cross', mid[0], mid[1], { geometry: line([[mid[0] - 0.003, mid[1] - 0.003], [mid[0] + 0.003, mid[1] + 0.003]]) });
  const alongIt = cond('along', mid[0], mid[1], { geometry: line([coords[0], mid, coords[1]]) });
  assert.deepEqual(routeContext({ ...route, road_segment_ids: null }, [], [crossing, alongIt], TRIP).conditions.map(c => c.id), ['along']);
});

test('routeContext: a freeway closure point above the route counts only if the route uses that freeway', () => {
  const mid: LatLng = [(coords[0][0] + coords[1][0]) / 2, (coords[0][1] + coords[1][1]) / 2];
  const deck = cond('i80', mid[0], mid[1], { street: 'Route 80', source: 'caltrans_lane_closures' });
  const step = (name: string) => ({ distance: 1, duration: 1, name, maneuver: { type: 'turn', location: [0, 0] as [number, number] } });
  const surface = { ...route, road_segment_ids: null, steps: [step('4th Street'), step('King Street')] };
  assert.deepEqual(routeContext(surface, [], [deck], TRIP).conditions, []);
  assert.deepEqual(routeContext({ ...surface, steps: [step('I 80')] }, [], [deck], TRIP).conditions.map(c => c.id), ['i80']);
});

// ---- temporal relevance: an event counts only if near the route AND its active time overlaps the trip window ----
// Trip: arrive by Mon Sep 28, 2:00 PM SF time on the 10-min `route` → on the road 1:50–2:00 PM PDT (20:50–21:00Z).
// Trip relevance window = 12:50–3:00 PM PDT (EVENT_TAIL_MIN / EVENT_LEAD_MIN = 60 min each side).
const MON_2PM = fromSfLocal('2026-09-28T14:00');
const arriveMon = tripSpan({ mode: 'arrive', at: MON_2PM }, route.dur, fromSfLocal('2026-09-26T07:00'));
const NEAR: LatLng = [37.7833, -122.3954];            // on the route line
const sf = (wall: string) => new Date(fromSfLocal(wall)).toISOString();
const timed = (id: string, start: string, end: string | null, at: LatLng = NEAR) =>
  ev(id, at[0], at[1], { start_time: sf(start), end_time: end && sf(end) });
const ids = (evs: MapEvent[], trip = arriveMon) => routeContext(route, evs, [], trip).events.map(e => e.id);

test('tripSpan: arrive-by is the drive ending at the chosen time, not "now" and not a multi-day window', () => {
  assert.deepEqual(arriveMon, { from: MON_2PM - 600_000, to: MON_2PM });
  assert.equal(new Date(arriveMon.from).toISOString(), '2026-09-28T20:50:00.000Z');
  assert.deepEqual(eventWindow(arriveMon), { from: Date.parse('2026-09-28T19:50:00Z'), to: Date.parse('2026-09-28T22:00:00Z') });
});

test('A. overlaps the trip + near the route → included', () => {
  assert.deepEqual(ids([timed('a', '2026-09-28T13:00', '2026-09-28T17:00')]), ['a']);
});

test('B. near the route but ended before the trip window → excluded', () => {
  assert.deepEqual(ids([timed('b', '2026-09-28T08:00', '2026-09-28T12:30')]), []);  // ended 12:30, window opens 12:50
  assert.deepEqual(ids([timed('b2', '2026-09-28T08:00', '2026-09-28T13:00')]), ['b2']); // leaving crowd still counts
});

test('C. near the route but starts after the trip window → excluded', () => {
  assert.deepEqual(ids([timed('c', '2026-09-28T15:30', '2026-09-28T18:00')]), []);  // window closes 3:00 PM
  assert.deepEqual(ids([timed('c2', '2026-09-28T14:45', '2026-09-28T18:00')]), ['c2']); // arriving crowd counts
});

test('D. overlaps the trip but not near the route → excluded', () => {
  assert.deepEqual(ids([timed('d', '2026-09-28T13:00', '2026-09-28T17:00', [37.76, -122.45])]), []);
});

test('E. multi-day event that really spans the trip → included', () => {
  assert.deepEqual(ids([timed('e', '2026-09-26T09:00', '2026-09-30T18:00')]), ['e']);
});

test('F. arrive-by trip after the event already ended → excluded', () => {
  const arriveFri = tripSpan({ mode: 'arrive', at: fromSfLocal('2026-10-02T21:00') }, route.dur, fromSfLocal('2026-09-26T07:00'));
  assert.deepEqual(ids([timed('f', '2026-09-28T10:00', '2026-09-28T16:00')], arriveFri), []);
});

test('G. no end time → point-event rule: active start → start + DEFAULT_EVENT_MIN, never indefinitely', () => {
  assert.equal(DEFAULT_EVENT_MIN, 180);
  assert.deepEqual(ids([timed('g-on', '2026-09-28T11:00', null)]), ['g-on']);     // 11:00–2:00 PM overlaps 12:50–3:00
  assert.deepEqual(ids([timed('g-off', '2026-09-28T09:00', null)]), []);          // 9:00–12:00 PM ends before 12:50
  assert.deepEqual(ids([timed('g-old', '2026-09-20T13:30', null)]), []);          // last week: not "still going"
});

test('timezone: the day is SF\'s, whatever the browser zone; 11:30 PM Sun in SF is not Mon', () => {
  assert.deepEqual(ids([timed('sun', '2026-09-27T20:00', '2026-09-27T23:30')]), []);
});

test('real AMZN Unboxed record (DataSF 1560116): runs Sep 23 6 AM – Oct 2 6 PM PDT', () => {
  const amzn = ev('amzn', 37.78238435, -122.403834, { name: 'AMZN Unboxed 2026 (SF)', start_time: '2026-09-23T13:00:00Z', end_time: '2026-10-03T01:00:00Z' });
  assert.equal(fmtEventTime(amzn), 'Wed, Sep 23, 6:00 AM – Fri, Oct 2, 6:00 PM');
  // A Union Square → Oracle Park route passes ~250 m from its Howard St closure.
  const unionToOracle: Route = { ...route, coords: [[37.788, -122.4075], [37.7865, -122.4065], [37.7812, -122.3995], [37.7786, -122.3893]] };
  const tripAt = (wall: string) => tripSpan({ mode: 'arrive', at: fromSfLocal(wall) }, 360, fromSfLocal('2026-09-26T07:00'));
  const got = (wall: string) => routeContext(unionToOracle, [amzn], [], tripAt(wall)).events.map(e => e.id);
  assert.deepEqual(got('2026-09-28T14:00'), ['amzn']);   // Mon Sep 28 is inside the permit window
  assert.deepEqual(got('2026-10-03T14:00'), []);         // Sat Oct 3: ended the evening before
});

test('road conditions count only while active during the trip', () => {
  const at = (id: string, start: string | null, end: string | null) => cond(id, NEAR[0], NEAR[1], { start_time: start && sf(start), end_time: end && sf(end) });
  const got = routeContext({ ...route, road_segment_ids: null }, [], [
    at('during', '2026-09-28T13:00', '2026-09-28T16:00'),
    at('before', '2026-09-28T08:00', '2026-09-28T13:30'),         // ended before 1:50 PM departure
    at('open-recent', '2026-09-28T12:00', null),                  // no end: 6 h from start, still on
    at('open-stale', '2026-09-27T12:00', null),                   // no end, a day old: off
  ], arriveMon).conditions.map(c => c.id);
  assert.deepEqual(got, ['during', 'open-recent']);
});

test('contextNote: facts only, and never blocks on a failed feed', () => {
  assert.equal(contextNote({ events: [], conditions: [] }, ready), NO_EVENTS);
  const one = contextNote({ events: [ev('a', 0, 0, { name: 'Portola Music Festival' })], conditions: [] }, ready);
  assert.match(one, /^Portola Music Festival \(.+\) is near your route and may affect traffic\.$/);
  assert.doesNotMatch(one, /min/);                                        // no invented delay
  const many = contextNote({ events: [ev('a', 0, 0), ev('b', 0, 0), ev('c', 0, 0)], conditions: [cond('x', 0, 0), cond('y', 0, 0, { is_closure: false })] }, ready);
  assert.equal(many, '3 events near your route may affect traffic: Event a, Event b and more. 1 road closure on your route (Hubbell St). 1 reported incident on your route.');
  assert.equal(contextNote(null, { ...ready, loading: true }), 'Checking events on your way…');
  assert.equal(contextNote({ events: [], conditions: [] }, { events: null, conditions: null, loading: false }), "Couldn't check events on your way right now.");
  assert.equal(contextNote({ events: [], conditions: [cond('x', 0, 0)] }, { ...ready, events: null }),
    "Couldn't check events on your way right now. 1 road closure on your route (Hubbell St).");
});

test('contextTag', () => {
  assert.equal(contextTag({ events: [], conditions: [] }, ready), 'Clear');
  assert.equal(contextTag({ events: [ev('a', 0, 0)], conditions: [] }, ready), '1 event nearby');
  assert.equal(contextTag({ events: [], conditions: [cond('x', 0, 0)] }, ready), 'Road closure');
  assert.equal(contextTag({ events: [], conditions: [] }, { ...ready, events: null }), 'Fastest');
});

test('validCoord + fmtCategory', () => {
  for (const [lat, lon] of [[NaN, 1], [91, 0], [0, 181], [0, 0], ['37', -122], [null, null]]) assert.equal(validCoord(lat, lon), false, `${lat},${lon}`);
  assert.equal(validCoord(37.78, -122.4), true);
  assert.equal(fmtCategory('special_event'), 'Special event');
  assert.equal(fmtCategory(null), '');
});

test('fetchEvents drops records with bad coordinates or no name; API errors reject', async () => {
  const real = globalThis.fetch;
  try {
    globalThis.fetch = (async () => new Response(JSON.stringify({ events: [ev('ok', 37.78, -122.4), ev('nan', NaN, 1), ev('zero', 0, 0), { ...ev('noname', 37.78, -122.4), name: '' }] }))) as typeof fetch;
    assert.deepEqual((await fetchEvents({ from: 0, to: 1 })).map(e => e.id), ['ok']);
    globalThis.fetch = (async () => new Response(JSON.stringify({ detail: 'ingested data unavailable' }), { status: 503 })) as typeof fetch;
    await assert.rejects(fetchEvents({ from: 0, to: 1 }), /ingested data unavailable/);
  } finally {
    globalThis.fetch = real;
  }
});
