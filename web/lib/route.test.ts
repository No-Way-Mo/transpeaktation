import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtDist, mins, routeTag, stepArrow, stepText, type Step } from './route.ts';

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
