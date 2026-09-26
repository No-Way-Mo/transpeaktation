import { test } from 'node:test';
import assert from 'node:assert/strict';
import { routeContext, type MapEvent } from './context.ts';
import type { LatLng, Route } from './route.ts';
import {
  getTrafficColor, getTrafficLevel, hasRouteTraffic, MAPBOX_CONGESTION_RATIO, routeTraffic, TRAFFIC_COLORS, TRAFFIC_LEVELS,
} from './traffic.ts';

const coords: LatLng[] = [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5]];
const route = (congestion: string[] | null | undefined): Route => ({ dur: 1, dist: 1, summary: '', coords, steps: [], congestion });

test('congestion_ratio → level, at the documented thresholds (share of free-flow speed lost)', () => {
  const cases: [number, string][] = [
    [0, 'very_light'], [0.149, 'very_light'], [0.15, 'light'], [0.29, 'light'], [0.3, 'moderate'], [0.49, 'moderate'],
    [0.5, 'busy'], [0.69, 'busy'], [0.7, 'very_busy'], [0.84, 'very_busy'], [0.85, 'severe'], [1, 'severe'],
    [-0.2, 'very_light'], [1.4, 'severe'],   // clamped to [0, 1] like ingest stores it
  ];
  for (const [ratio, level] of cases) assert.equal(getTrafficLevel(ratio), level, String(ratio));
  for (const none of [null, undefined, NaN, Infinity]) assert.equal(getTrafficLevel(none), null, String(none));
});

test('level → colour: conventional green-to-red, six distinct colours', () => {
  assert.deepEqual(TRAFFIC_LEVELS.map(getTrafficColor), ['#52b69a', '#99d98c', '#f4d35e', '#f6a623', '#ef5350', '#a61b1b']);
  assert.equal(new Set(Object.values(TRAFFIC_COLORS)).size, 6);
});

test('Mapbox levels use the AGENTS.md calibration and land on four of the six levels', () => {
  assert.deepEqual(MAPBOX_CONGESTION_RATIO, { low: 0.1, moderate: 0.4, heavy: 0.65, severe: 0.85 });
  const levels = Object.values(MAPBOX_CONGESTION_RATIO).map(getTrafficLevel);
  assert.deepEqual(levels, ['very_light', 'moderate', 'busy', 'severe']);
});

test('route traffic: stretches merge per level; pieces without a reading are left to the normal route colour', () => {
  assert.deepEqual(routeTraffic(route(['low', 'heavy', 'heavy', 'unknown', 'severe'])), [
    { level: 'very_light', coords: [[0, 0], [0, 1]] },
    { level: 'busy', coords: [[0, 1], [0, 2], [0, 3]] },
    { level: 'severe', coords: [[0, 4], [0, 5]] },
  ]);
});

test('missing traffic data → the normal route, and no traffic legend', () => {
  for (const c of [null, undefined, [], ['unknown', 'unknown', 'unknown', 'unknown', 'unknown']]) {
    assert.deepEqual(routeTraffic(route(c)), [], JSON.stringify(c));
    assert.equal(hasRouteTraffic(route(c)), false, JSON.stringify(c));
  }
  assert.equal(hasRouteTraffic(undefined), false);
  assert.equal(hasRouteTraffic(route(['low', 'unknown', 'unknown', 'unknown', 'unknown'])), true);
});

test('an event on the route never creates traffic: the route is coloured only from traffic readings', () => {
  const r: Route = { ...route(null), coords: [[37.788, -122.4015], [37.7786, -122.3893]] };
  const onIt: MapEvent = { id: 'e', name: 'Big Game', category: 'sports', venue: null, lat: 37.788, lon: -122.4015,
    start_time: '2026-09-27T00:00:00Z', end_time: '2026-09-27T03:00:00Z', source: 'predicthq', status: 'active', road_closure_ids: [] };
  const trip = { from: Date.parse('2026-09-27T01:00:00Z'), to: Date.parse('2026-09-27T01:10:00Z') };
  assert.equal(routeContext(r, [onIt], [], trip).events.length, 1); // the event is on the route...
  assert.deepEqual(routeTraffic(r), []);                           // ...and still no congestion is drawn
});
