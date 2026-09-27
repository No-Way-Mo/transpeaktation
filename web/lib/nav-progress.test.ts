import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ARRIVAL_THRESHOLD_METERS, demoFix, isArrived, navFix, navProgress, pointAlong, projectOnLine, routeEnd, type Fix } from './nav-progress.ts';
import type { LatLng, Route, Step } from './route.ts';

// A straight 2.6 km (1.6 mi) drive due north: two 1.3 km legs, then arrive.
const LON = -122.4, LAT0 = 37.77, M = 1 / 111_320; // degrees of latitude per metre
const at = (m: number, east = 0): LatLng => [LAT0 + m * M, LON + (east * M) / Math.cos((LAT0 * Math.PI) / 180)];
const step = (type: string, distance: number, duration: number, m: number): Step =>
  ({ distance, duration, name: 'Main St', maneuver: { type, location: [at(m)[1], at(m)[0]] } });
const route: Route = {
  dur: 200, dist: 2600, summary: '', coords: [at(0), at(1300), at(2600)],
  steps: [step('depart', 1300, 100, 0), step('turn', 1300, 100, 1300), step('arrive', 0, 0, 2600)],
};
const fix = (m: number, east = 0, accuracy = 10): Fix => ({ pos: at(m, east), accuracy });

test('projects a fix onto the route line', () => {
  const p = projectOnLine(at(650, 20), route.coords);
  assert.ok(Math.abs(p.along - 650) < 1);
  assert.ok(Math.abs(p.offBy - 20) < 1);
  assert.ok(Math.abs(p.length - 2600) < 1);
});

test('the bug: 1.6 mi from the destination is not arrived, and the trip still has 1.6 mi left', () => {
  assert.equal(isArrived(fix(0), route), false);
  const p = navProgress(fix(0), route)!;
  assert.equal(p.step, 0);
  assert.ok(Math.abs(p.remDist - 2600) < 1);
  assert.ok(Math.abs(p.remDur - 200) < 1);
});

test('arrival only inside the threshold of the route end', () => {
  const end = routeEnd(route)!, want = at(2600);
  assert.ok(Math.abs(end[0] - want[0]) < 1e-9 && Math.abs(end[1] - want[1]) < 1e-9);  // the provider's arrive point
  assert.equal(isArrived(fix(2600 - ARRIVAL_THRESHOLD_METERS - 10), route), false);
  assert.equal(isArrived(fix(2600 - ARRIVAL_THRESHOLD_METERS + 5), route), true);
  assert.equal(isArrived(fix(2600), route), true);
  assert.equal(isArrived(fix(2600, 0, 200), route), false);           // a vague fix can't prove arrival
  assert.equal(isArrived(fix(2600, 0, 49), route), true);
  assert.equal(isArrived(fix(2600, 300), route), false);              // off to the side of the end, not there
});

test('progress follows the fix: step, distance to the turn, what is left', () => {
  const mid = navProgress(fix(650), route)!;
  assert.equal(mid.step, 0);
  assert.ok(Math.abs(mid.toNext - 650) < 1);
  assert.ok(Math.abs(mid.remDist - 1950) < 1);
  assert.ok(Math.abs(mid.remDur - 150) < 1);                           // half of leg 1 + all of leg 2
  const leg2 = navProgress(fix(1950), route, 2)!;                      // scaled to the card's estimate
  assert.equal(leg2.step, 1);
  assert.ok(Math.abs(leg2.toNext - 650) < 1);
  assert.ok(Math.abs(leg2.remDur - 100) < 1);
  const end = navProgress(fix(2600), route)!;
  assert.equal(end.step, 2);
  assert.ok(end.remDist < 1);
});

test('untrustworthy fixes leave progress alone', () => {
  assert.equal(navProgress(fix(650, 500), route), null);               // off route
  assert.equal(navProgress(fix(650, 0, 500), route), null);            // too vague
  assert.notEqual(navProgress(fix(650, 80, 90), route), null);         // inside its own accuracy of the line
  assert.equal(navProgress(fix(650), { ...route, steps: [] }), null);
});

test('demo position: each tap moves along the route, and only the last one arrives', () => {
  // Union Square → Oracle Park as a 4-leg drive; step distances from the line itself.
  const line: LatLng[] = [[37.788, -122.4075], [37.7865, -122.4065], [37.7812, -122.3995], [37.7786, -122.3893]];
  const legs = line.slice(1).map((b, j) => projectOnLine(b, line.slice(0, j + 2)).along - projectOnLine(line[j], line.slice(0, j + 2)).along);
  const loc = (p: LatLng): [number, number] => [p[1], p[0]];
  const r: Route = {
    dur: 600, dist: legs.reduce((a, b) => a + b, 0), summary: '', coords: line,
    steps: [...legs.map((d, j) => ({ distance: d, duration: d / 5, name: 'St', maneuver: { type: j ? 'turn' : 'depart', location: loc(line[j]) } })),
      { distance: 0, duration: 0, name: '', maneuver: { type: 'arrive', location: loc(line[3]) } }],
  };
  assert.ok(r.dist > 1500);
  const start = demoFix(r, 0);
  assert.deepEqual(start.pos, line[0]);                                // starts at the demo start
  let prevDist = Infinity, prevDur = Infinity;
  for (let i = 0; i < r.steps.length - 1; i++) {
    const f = demoFix(r, i), p = navProgress(f, r)!;
    assert.equal(isArrived(f, r), false, `tap ${i}: not arrived`);
    assert.equal(p.step, i, `tap ${i}: on step ${i}`);
    assert.ok(p.remDist < prevDist && p.remDur < prevDur, `tap ${i}: less left`);
    assert.ok(p.remDist > ARRIVAL_THRESHOLD_METERS);
    prevDist = p.remDist; prevDur = p.remDur;
  }
  const end = demoFix(r, r.steps.length - 1);
  assert.equal(isArrived(end, r), true);
  assert.ok(navProgress(end, r)!.remDist < 1);
});

test('pointAlong walks the line and clamps', () => {
  assert.deepEqual(pointAlong(route.coords, 0), route.coords[0]);
  assert.ok(Math.abs(projectOnLine(pointAlong(route.coords, 1950), route.coords).along - 1950) < 1);
  assert.deepEqual(pointAlong(route.coords, 99_999), route.coords[2]);
});

test('device mode: demo taps cannot move navigation; only GPS does', () => {
  const gps = fix(650);
  const before = navProgress(navFix('device', route, 0, gps)!, route);
  for (const taps of [1, 2, 99]) {
    const f = navFix('device', route, taps, gps);
    assert.equal(f, gps);                                               // same fix: GPS, whatever was tapped
    assert.deepEqual(navProgress(f!, route), before);                  // same turn, distance and time left
    assert.equal(isArrived(f!, route), false);                         // tapping to the end can't arrive
  }
  assert.equal(navFix('device', route, 99, null), null);                // no GPS yet: nothing to navigate on
  // demo mode, same taps: they do move it, and the last one arrives
  assert.equal(navProgress(navFix('demo', route, 1, gps)!, route)!.step, 1);
  assert.equal(isArrived(navFix('demo', route, 2, gps)!, route), true);
});
