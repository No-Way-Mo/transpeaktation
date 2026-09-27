import { test } from 'node:test';
import assert from 'node:assert/strict';

import type { MapEvent, Span } from './context.ts';
import { parseExperiment } from './experiment.ts';
import {
  ACTIVITY_PALETTE, activityPoints, densityPeak, focusRel, getEventImportance, getMinZoomForEvent, HEAT_FLOOR, heatAlpha, heatLevel,
  heatOpacity, heatRadiusMeters, heatWeight, kernel, legendOpacity, metersBetween, MIN_PEAK, pinOpacity, pinScale, pinStates,
  REL, relZoom, type HeatPoint,
} from './snapmap.ts';

const H = 3_600_000;
const T0 = Date.parse('2026-10-03T19:00:00Z');
const blocks = (n: number) => Array.from({ length: n }, (_, i) => `street_closures:${i}`);
const ev = (id: string, o: Partial<MapEvent> = {}): MapEvent => ({
  id, name: id, category: null, venue: null, lat: 37.78, lon: -122.41,
  start_time: new Date(T0).toISOString(), end_time: new Date(T0 + 3 * H).toISOString(),
  source: 'street_closures', status: 'approved', road_closure_ids: [], ...o,
});
// Relative zooms (levels above the zoom where all of SF fits the map)
const REGION = -2, CITY = 0, HOOD = REL.neighborhood, STREET = REL.street;
const shown = (e: MapEvent, rel: number, pinned?: Set<string>) => pinStates([e], rel, pinned)[0].opacity;

test('importance comes from closure extent, then the PredictHQ rank floor; nothing else', () => {
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(55) })).tier, 'major');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(6) })).tier, 'major');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(5) })).tier, 'medium');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(2) })).tier, 'medium');
  assert.equal(getEventImportance(ev('a', { road_closure_ids: blocks(1) })).tier, 'minor');
  const phq = getEventImportance(ev('p', { source: 'predicthq' }));
  assert.deepEqual([phq.tier, phq.basis], ['medium', 'source_rank_floor']);
  const unknown = getEventImportance(ev('t', { source: 'ticketmaster' }));
  assert.deepEqual([unknown.tier, unknown.basis], ['minor', 'none']);
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
  assert.equal(getEventImportance(ev('x', { road_closure_ids: ['a', 'a', 'a', 'a', 'a', 'a'] })).tier, 'minor');
});

test('thresholds are relative to the zoom where all of SF fits', () => {
  assert.equal(relZoom(12.4, 12.4), 0);   // desktop whole-SF view
  assert.equal(relZoom(11.2, 11.2), 0);   // phone whole-SF view: same tier
  assert.equal(relZoom(14.9, 12.4), 2.5);
});

test('min zoom per tier; higher score arrives a little earlier inside its tier', () => {
  const med = getMinZoomForEvent(getEventImportance(ev('p', { source: 'predicthq' })));
  const medBig = getMinZoomForEvent(getEventImportance(ev('c', { road_closure_ids: blocks(5) })));
  const minor = getMinZoomForEvent(getEventImportance(ev('b', { road_closure_ids: blocks(1) })));
  const none = getMinZoomForEvent(getEventImportance(ev('t', { source: 'ticketmaster' })));
  assert.ok(getMinZoomForEvent(getEventImportance(ev('m', { road_closure_ids: blocks(8) }))) < REGION);
  assert.equal(med, REL.neighborhood);
  assert.ok(medBig < med && medBig >= REL.neighborhood - 0.5);
  assert.ok(med < minor && minor < none && none === REL.street);
});

test('whole-city view: major events only; medium arrive at neighbourhood; all at street', () => {
  const major = ev('major', { road_closure_ids: blocks(16) });
  const minor = ev('minor', { road_closure_ids: blocks(1) });
  const phq = ev('phq', { source: 'predicthq' });
  const bigMedium = ev('m5', { road_closure_ids: blocks(5) });
  for (const rel of [REGION, CITY]) assert.equal(shown(major, rel), 1);
  for (const rel of [REGION, CITY]) for (const e of [minor, phq, bigMedium]) assert.equal(shown(e, rel), 0, `${e.id} at ${rel}`);
  assert.ok(shown(bigMedium, 0.5) > 0 && shown(phq, 0.5) === 0, 'the biggest medium events trickle in first');
  assert.equal(shown(phq, HOOD), 1);
  assert.equal(shown(minor, 1), 0);
  assert.ok(shown(minor, HOOD) > 0 && shown(minor, HOOD) < 0.5, 'minor events are only starting to arrive at neighbourhood zoom');
  assert.equal(shown(minor, STREET), 1);
  assert.equal(shown(ev('t', { source: 'ticketmaster' }), STREET), 1);
});

test('transitions are continuous: zooming in never hides a pin, heat and radius only shrink', () => {
  const events = [ev('a', { road_closure_ids: blocks(1) }), ev('b', { source: 'predicthq' }), ev('c', { road_closure_ids: blocks(3) })];
  for (let rel = -3; rel < 4; rel += 0.25) {
    const a = pinStates(events, rel), b = pinStates(events, rel + 0.25);
    a.forEach((s, i) => {
      assert.ok(b[i].opacity >= s.opacity, `pin ${s.id} at ${rel}`);
      assert.ok(b[i].opacity - s.opacity <= 0.34, `pin ${s.id} jumps at ${rel}`);
    });
    assert.ok(heatOpacity(rel + 0.25, false) <= heatOpacity(rel, false));
    assert.ok(heatOpacity(rel, false) - heatOpacity(rel + 0.25, false) <= 0.12, `heat jumps at ${rel}`);
    assert.ok(heatRadiusMeters(rel + 0.25) <= heatRadiusMeters(rel));
  }
  assert.equal(pinOpacity(1.5, 1.5 - 0.375), 0.5);
});

test('heat: dominant at city zoom, weaker at neighbourhood, gone at street', () => {
  assert.equal(heatOpacity(REGION, false), 1);
  assert.equal(heatOpacity(CITY, false), 1);
  assert.ok(heatOpacity(HOOD, false) > 0.3 && heatOpacity(HOOD, false) < 0.6);
  assert.equal(heatOpacity(STREET, false), 0);
  assert.ok(heatRadiusMeters(REGION) > heatRadiusMeters(CITY) && heatRadiusMeters(CITY) > heatRadiusMeters(HOOD));
  assert.ok(heatRadiusMeters(CITY) >= 1000, 'city zoom: ~1 km kernels so downtown + SoMa merge');
});

test('important pins are slightly larger zoomed out, normal size from neighbourhood zoom', () => {
  const imp = getEventImportance(ev('m', { road_closure_ids: blocks(55) }));
  assert.ok(pinScale(imp, CITY) > 1.15 && pinScale(imp, CITY) <= 1.3);
  assert.equal(pinScale(imp, HOOD), 1);
});

test('heat uses only events inside the selected time window', () => {
  const trip: Span = { from: T0 + H, to: T0 + H + 20 * 60_000 };
  const now = ev('now');
  const later = ev('later', { start_time: new Date(T0 + 8 * H).toISOString(), end_time: new Date(T0 + 10 * H).toISOString() });
  const earlier = ev('earlier', { start_time: new Date(T0 - 9 * H).toISOString(), end_time: new Date(T0 - 5 * H).toISOString() });
  const pts = activityPoints([now, later, earlier, ev('bad', { start_time: 'soon' }), ev('nowhere', { lat: 0, lon: 0 })], trip);
  assert.deepEqual(pts, [{ lat: now.lat, lon: now.lon, w: 1 }]);
});

test('changing the time changes the activity dataset', () => {
  const events = [ev('early'), ev('late', { lon: -122.4, start_time: new Date(T0 + 8 * H).toISOString(), end_time: new Date(T0 + 10 * H).toISOString() })];
  const a = activityPoints(events, { from: T0 + H, to: T0 + H + 15 * 60_000 });
  const b = activityPoints(events, { from: T0 + 9 * H, to: T0 + 9 * H + 15 * 60_000 });
  assert.deepEqual([a.map(p => p.lon), b.map(p => p.lon)], [[-122.41], [-122.4]]);
});

test('heat does not require a pin: every time-relevant event contributes, pins are chosen separately', () => {
  const trip: Span = { from: T0 + H, to: T0 + H + 20 * 60_000 };
  const events = [ev('major', { road_closure_ids: blocks(16) }), ...Array.from({ length: 30 }, (_, i) => ev(`phq${i}`, { source: 'predicthq', lat: 37.78 + i * 1e-4 }))];
  assert.equal(activityPoints(events, trip).length, 31);
  const pins = pinStates(events, CITY).filter(s => s.opacity > 0);
  assert.deepEqual(pins.map(s => s.id), ['major']);
});

test('heat weight: one per event plus a capped, real closure footprint', () => {
  assert.equal(heatWeight({ road_closure_ids: [] }), 1);
  assert.equal(heatWeight({ road_closure_ids: blocks(5) }), 2);
  assert.equal(heatWeight({ road_closure_ids: blocks(55) }), 3);
});

test('kernel is smooth and compact; distance is in metres', () => {
  assert.equal(kernel(0), 1);
  assert.equal(kernel(1), 0);
  assert.equal(kernel(2), 0);
  assert.ok(kernel(0.5) > 0.5 && kernel(0.5) < 0.6);
  const d = metersBetween({ lat: 37.78, lon: -122.41 }, { lat: 37.79, lon: -122.41 });
  assert.ok(Math.abs(d - 1113) < 5);
});

test('normalisation: the densest cluster reaches the top, a lone event never does', () => {
  const at = (lat: number, lon: number, w = 1): HeatPoint => ({ lat, lon, w });
  const downtown = Array.from({ length: 12 }, (_, i) => at(37.785 + (i % 4) * 0.002, -122.405 + Math.floor(i / 4) * 0.002));
  const lone = at(37.74, -122.48);
  const pts = [...downtown, lone];
  const peak = densityPeak(pts, 1100);
  assert.ok(peak > 8, `downtown stacks up (${peak.toFixed(1)})`);
  assert.ok(1 / peak < 0.15, 'a lone event is a faint glow next to downtown');
  assert.equal(densityPeak([lone], 1100), MIN_PEAK, 'a lone event alone is floored, not stretched to the top');
  assert.equal(densityPeak([], 1100), MIN_PEAK);
  assert.ok(heatAlpha(heatLevel(1 / MIN_PEAK), 0.8) < 0.8 * 0.6, 'lone event alone: a soft glow, never saturated');
  assert.ok(heatLevel(1 / MIN_PEAK) < 0.4, 'lone event alone: green, not the blue end of the ramp');
});

test('ramp position: order preserved, moderate clusters lifted, bounded', () => {
  assert.equal(heatLevel(0), 0);
  assert.equal(heatLevel(1), 1);
  assert.equal(heatLevel(5), 1);
  assert.ok(heatLevel(0.3) > 0.3 && heatLevel(0.3) < 0.45);
  for (let x = 0; x < 1; x += 0.05) assert.ok(heatLevel(x + 0.05) > heatLevel(x));
});

test('alpha ramp: transparent below the floor, saturated at the hotspot centre', () => {
  assert.equal(heatAlpha(0, 0.8), 0);
  assert.equal(heatAlpha(HEAT_FLOOR, 0.8), 0);
  assert.ok(heatAlpha(0.2, 0.8) > 0 && heatAlpha(0.2, 0.8) < 0.2);
  assert.equal(heatAlpha(0.6, 0.8), 0.8);
  assert.equal(heatAlpha(1, 0.8), 0.8);
});

test('route mode: heat steps back and is gone from neighbourhood zoom; route events stay; filtering unchanged', () => {
  assert.ok(heatOpacity(CITY, true) < 0.4 && heatOpacity(CITY, true) > 0);
  assert.equal(heatOpacity(1.75, true), 0);
  assert.equal(legendOpacity(STREET, true), 0);
  assert.ok(legendOpacity(CITY, false) > 0);
  const onRoute = ev('onroute', { road_closure_ids: blocks(1) }), other = ev('other', { road_closure_ids: blocks(1) });
  assert.deepEqual(pinStates([onRoute, other], CITY, new Set(['onroute'])).map(s => s.opacity), [1, 0]);
  const trip: Span = { from: T0, to: T0 + 30 * 60_000 };
  assert.deepEqual(activityPoints([onRoute, other], trip), activityPoints([other, onRoute], trip).reverse());
});

test('clicking a pin zooms in to at least neighbourhood-street, never out', () => {
  assert.equal(focusRel(CITY), 2);
  assert.equal(focusRel(3), 3);
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
  assert.equal(parseExperiment('off'), 'off');
});
