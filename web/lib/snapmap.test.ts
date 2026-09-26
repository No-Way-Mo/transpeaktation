import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { MapEvent, Span } from './context.ts';
import { parseExperiment } from './experiment.ts';
import {
  ACTIVITY_PALETTE, activityPoints, focusZoom, getEventImportance, getMinZoomForEvent, heatOpacity, heatWeight,
  legendOpacity, pinOpacity, pinScale, pinStates, ZOOMS,
} from './snapmap.ts';

const H = 3_600_000;
const T0 = Date.parse('2026-10-03T19:00:00Z');
const blocks = (n: number) => Array.from({ length: n }, (_, i) => `street_closures:${i}`);
const ev = (id: string, o: Partial<MapEvent> = {}): MapEvent => ({
  id, name: id, category: null, venue: null, lat: 37.78, lon: -122.41,
  start_time: new Date(T0).toISOString(), end_time: new Date(T0 + 3 * H).toISOString(),
  source: 'street_closures', status: 'approved', road_closure_ids: [], ...o,
});
const FAR = ZOOMS.regional, CITY = ZOOMS.city, STREET = ZOOMS.street;
const shown = (e: MapEvent, z: number, pinned?: Set<string>) => pinStates([e], z, pinned)[0].opacity;

test('importance comes from closure extent, then the PredictHQ rank floor; nothing else', () => {
  assert.deepEqual(getEventImportance(ev('a', { road_closure_ids: blocks(55) })).tier, 'major');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(6) })).tier, 'major');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(5) })).tier, 'medium');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(2) })).tier, 'medium');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(1) })).tier, 'minor');
  const phq = getEventImportance(ev('p', { source: 'predicthq' }));
  assert.deepEqual([phq.tier, phq.basis], ['medium', 'source_rank_floor']);
  const unknown = getEventImportance(ev('t', { source: 'ticketmaster' }));
  assert.deepEqual([unknown.tier, unknown.basis], ['minor', 'none']);
  // more blocks never ranks lower
  let last = -1;
  for (const n of [0, 1, 2, 3, 5, 6, 13, 55, 200]) {
    const s = getEventImportance(ev('x', { road_closure_ids: blocks(n) })).score;
    assert.ok(s >= last, `score for ${n} blocks`);
    last = s;
  }
  assert.ok(getEventImportance(ev('x', { road_closure_ids: blocks(200) })).score <= 1);
});

test('category never changes importance (no "concert > conference")', () => {
  const cats = ['concert', 'conference', 'sports', 'festival', 'community', 'special_event', null];
  for (const source of ['predicthq', 'street_closures']) {
    const scores = new Set(cats.map(c => JSON.stringify(getEventImportance(ev('x', { source, category: c, road_closure_ids: blocks(3) })))));
    assert.equal(scores.size, 1, source);
  }
});

test('missing or malformed importance fields are handled safely', () => {
  for (const bad of [undefined, null, 'abc', [null, '', 3], {}]) {
    const imp = getEventImportance(ev('x', { road_closure_ids: bad as unknown as string[] }));
    assert.equal(imp.tier, 'minor');
    assert.ok(Number.isFinite(getMinZoomForEvent(imp)));
    assert.ok(Number.isFinite(heatWeight({ road_closure_ids: bad as unknown as string[] })));
  }
  // duplicate closure ids count once
  assert.equal(getEventImportance(ev('x', { road_closure_ids: ['a', 'a', 'a', 'a', 'a', 'a'] })).tier, 'minor');
});

test('min zoom per tier; higher score arrives a little earlier inside its tier', () => {
  assert.equal(getMinZoomForEvent(getEventImportance(ev('m', { road_closure_ids: blocks(8) }))), 0);
  const med = getMinZoomForEvent(getEventImportance(ev('p', { source: 'predicthq' })));
  const medBig = getMinZoomForEvent(getEventImportance(ev('c', { road_closure_ids: blocks(5) })));
  const minor = getMinZoomForEvent(getEventImportance(ev('b', { road_closure_ids: blocks(1) })));
  const none = getMinZoomForEvent(getEventImportance(ev('t', { source: 'ticketmaster' })));
  assert.equal(med, ZOOMS.neighborhood);
  assert.ok(medBig < med && medBig >= ZOOMS.neighborhood - 0.5);
  assert.ok(minor < none && none === ZOOMS.street);
  assert.ok(med < minor);
});

test('major event visible at far zoom, minor hidden there, minor visible close in', () => {
  const major = ev('major', { road_closure_ids: blocks(16) });
  const minor = ev('minor', { road_closure_ids: blocks(1) });
  const phq = ev('phq', { source: 'predicthq' });
  assert.equal(shown(major, FAR), 1);
  assert.equal(shown(major, CITY), 1);
  assert.equal(shown(minor, FAR), 0);
  assert.equal(shown(minor, CITY), 0);
  assert.equal(shown(phq, CITY), 0);
  assert.equal(shown(phq, ZOOMS.neighborhood), 1);
  assert.equal(shown(minor, STREET), 1);
  assert.equal(shown(ev('t', { source: 'ticketmaster' }), STREET), 1);
});

test('transitions are continuous: no pin or heat jump bigger than the zoom step', () => {
  const events = [ev('a', { road_closure_ids: blocks(1) }), ev('b', { source: 'predicthq' }), ev('c', { road_closure_ids: blocks(3) })];
  for (let z = 8; z < 17; z += 0.25) {
    const a = pinStates(events, z), b = pinStates(events, z + 0.25);
    a.forEach((s, i) => assert.ok(Math.abs(b[i].opacity - s.opacity) <= 0.25 + 1e-9, `pin ${s.id} at ${z}`));
    assert.ok(Math.abs(heatOpacity(z + 0.25, false) - heatOpacity(z, false)) <= 0.07, `heat at ${z}`);
    assert.ok(b.every(s => s.opacity >= a.find(x => x.id === s.id)!.opacity), 'zooming in never hides a pin');
  }
  assert.equal(pinOpacity(14, 13.5), 0.5);
});

test('important pins are slightly larger zoomed out, normal size at street zoom', () => {
  const imp = getEventImportance(ev('m', { road_closure_ids: blocks(55) }));
  assert.ok(pinScale(imp, CITY) > 1.2 && pinScale(imp, CITY) <= 1.3);
  assert.equal(pinScale(imp, STREET), 1);
  assert.ok(pinScale(getEventImportance(ev('b', { road_closure_ids: blocks(1) })), CITY) < pinScale(imp, CITY));
});

test('heat uses only events inside the selected time window', () => {
  const trip: Span = { from: T0 + H, to: T0 + H + 20 * 60_000 };
  const now = ev('now');                                                              // 19:00-22:00: overlaps
  const later = ev('later', { start_time: new Date(T0 + 8 * H).toISOString(), end_time: new Date(T0 + 10 * H).toISOString() });
  const earlier = ev('earlier', { start_time: new Date(T0 - 9 * H).toISOString(), end_time: new Date(T0 - 5 * H).toISOString() });
  const badTime = ev('bad', { start_time: 'soon' });
  const badCoord = ev('nowhere', { lat: 0, lon: 0 });
  const pts = activityPoints([now, later, earlier, badTime, badCoord], trip);
  assert.equal(pts.length, 1);
  assert.deepEqual(pts[0], { lat: now.lat, lon: now.lon, w: 1 });
});

test('changing the time changes the activity dataset', () => {
  const events = [ev('early'), ev('late', { start_time: new Date(T0 + 8 * H).toISOString(), end_time: new Date(T0 + 10 * H).toISOString() })];
  const leaveNow: Span = { from: T0 + H, to: T0 + H + 15 * 60_000 };
  const leaveLater: Span = { from: T0 + 9 * H, to: T0 + 9 * H + 15 * 60_000 };
  assert.equal(activityPoints(events, leaveNow).length, 1);
  assert.equal(activityPoints(events, leaveLater).length, 1);
  assert.notDeepEqual(activityPoints(events, leaveNow), activityPoints(events, leaveLater).map(p => ({ ...p, lat: p.lat + 1 })));
  // same data, different window -> different events
  const a = events.filter(e => activityPoints([e], leaveNow).length).map(e => e.id);
  const b = events.filter(e => activityPoints([e], leaveLater).length).map(e => e.id);
  assert.deepEqual([a, b], [['early'], ['late']]);
});

test('heat weight: one per event plus a capped, real closure footprint', () => {
  assert.equal(heatWeight({ road_closure_ids: [] }), 1);
  assert.equal(heatWeight({ road_closure_ids: blocks(1) }), 1);
  assert.equal(heatWeight({ road_closure_ids: blocks(5) }), 2);
  assert.equal(heatWeight({ road_closure_ids: blocks(55) }), 3);
});

test('route mode: heat steps back and is gone at street zoom; route events stay; filtering unchanged', () => {
  assert.equal(heatOpacity(CITY, false), 1);
  assert.ok(heatOpacity(CITY, true) < 0.4 && heatOpacity(CITY, true) > 0);
  assert.equal(heatOpacity(STREET, true), 0);
  assert.equal(heatOpacity(15, false), 0);
  assert.equal(legendOpacity(STREET, true), 0);
  assert.ok(legendOpacity(CITY, false) > 0);
  const onRoute = ev('onroute', { road_closure_ids: blocks(1) }), other = ev('other', { road_closure_ids: blocks(1) });
  const states = pinStates([onRoute, other], CITY, new Set(['onroute']));
  assert.deepEqual(states.map(s => s.opacity), [1, 0]);           // the route's event is kept, the rest keep their rules
  const trip: Span = { from: T0, to: T0 + 30 * 60_000 };
  assert.deepEqual(activityPoints([onRoute, other], trip), activityPoints([other, onRoute], trip).reverse()); // route doesn't filter heat
});

test('clicking a pin zooms in, never out', () => {
  assert.equal(focusZoom(CITY), 14.5);
  assert.equal(focusZoom(16), 16);
});

test('palette is ours: blue-green, no traffic red / amber', () => {
  assert.equal(ACTIVITY_PALETTE[0], '#d9ed92');
  assert.equal(ACTIVITY_PALETTE.at(-1), '#184e77');
  for (const c of ACTIVITY_PALETTE) {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
    assert.ok(g >= r, `${c}: not red/amber`);
    assert.ok(b > 100 || g > 200, `${c}: blue-green`);
  }
});

test('experiment switch: on by default on this branch, NEXT_PUBLIC_MAP_EXPERIMENT=off restores the stable map', () => {
  assert.equal(parseExperiment(undefined), 'snapmap');
  assert.equal(parseExperiment('snapmap'), 'snapmap');
  assert.equal(parseExperiment('off'), 'off');
});
