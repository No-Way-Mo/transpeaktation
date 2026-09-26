import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtDist, fmtWhen, labelPoint, mins, routeTag, stepArrow, stepText, type LatLng, type Route, type Step } from './route.ts';

const step = (type: string, modifier?: string, name = 'Market St'): Step =>
  ({ distance: 0, duration: 0, name, maneuver: { type, modifier, location: [0, 0] } });

test('distances', () => {
  assert.equal(fmtDist(10), '50 ft');          // floor at 50 ft
  assert.equal(fmtDist(100), '350 ft');        // < 0.1 mi -> feet, nearest 50
  assert.equal(fmtDist(3218.68), '2.0 mi');
  assert.equal(fmtDist(740, 'km'), '740 m');
  assert.equal(fmtDist(2500, 'km'), '2.5 km');
});

test('route cards', () => {
  assert.equal(mins(10), 1);                    // never "0 min"
  assert.equal(routeTag(0, 900, 900), 'Fastest');
  assert.equal(routeTag(1, 1080, 900), '+3 min');
  assert.equal(routeTag(1, 910, 900), 'Similar');
});

test('turn-by-turn text', () => {
  assert.equal(stepText(step('depart', 'north'), 'Oracle Park'), 'Head north on Market St');
  assert.equal(stepText(step('depart'), 'Oracle Park'), 'Head on Market St');
  assert.equal(stepText(step('turn', 'left', ''), 'x'), 'Turn left onto the road');
  assert.equal(stepText(step('fork', 'slight right'), 'x'), 'Keep slight right onto Market St');
  assert.equal(stepText(step('arrive'), 'Oracle Park'), 'Arrive at Oracle Park');
  assert.equal(stepArrow(step('turn', 'sharp left')), '↰');
  assert.equal(stepArrow(step('arrive')), '■');
  assert.equal(stepArrow(step('turn', 'weird')), '↑');
});

test('departure times', () => {
  const now = new Date(2026, 8, 26, 15, 0).getTime();
  assert.match(fmtWhen(new Date(2026, 8, 26, 19, 15).getTime(), now), /^7:15\sPM$/);
  assert.match(fmtWhen(new Date(2026, 8, 27, 8, 0).getTime(), now), /^Tomorrow 8:00\sAM$/);
  assert.match(fmtWhen(new Date(2026, 8, 29, 8, 0).getTime(), now), /^Tue 8:00\sAM$/);
});

test('map labels sit where routes split, not on the shared stretch', () => {
  // Both routes share the first and last thirds; the second bows east in the middle.
  const lat = (i: number) => 37.77 + i * 0.001;
  const a: LatLng[] = Array.from({ length: 30 }, (_, i) => [lat(i), -122.41]);
  const b: LatLng[] = a.map(([la, lo], i) => [la, i >= 10 && i < 20 ? lo + 0.01 : lo]);
  const r = (coords: LatLng[]): Route => ({ dur: 600, dist: 2000, summary: '', coords, steps: [] });
  const p = labelPoint([r(a), r(b)], 1);
  assert.ok(Math.abs(p[1] - -122.40) < 1e-9, String(p));    // on the bowed-out stretch
  assert.deepEqual(labelPoint([r(a)], 0), a[15]);           // single route: middle
});
