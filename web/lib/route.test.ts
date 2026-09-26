import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fmtDist, fmtWhen, fromSfLocal, labelPoint, mins, routeTag, spokenTime, stepIcon, stepText, toSfLocal, trafficRuns, voiceNote, type LatLng, type Route, type Step, type VoiceIntent } from './route.ts';

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
  assert.deepEqual(stepIcon(step('turn', 'sharp left')), { name: 'arrow', rotate: -135 });
  assert.deepEqual(stepIcon(step('turn', 'uturn')), { name: 'uturn', rotate: 0 });
  assert.deepEqual(stepIcon(step('arrive')), { name: 'flag', rotate: 0 });
  assert.deepEqual(stepIcon(step('turn', 'weird')), { name: 'arrow', rotate: 0 });
});

test('departure times, in SF time', () => {
  const now = fromSfLocal('2026-09-26T15:00');
  assert.match(fmtWhen(fromSfLocal('2026-09-26T19:15'), now), /^7:15\sPM$/);
  assert.match(fmtWhen(fromSfLocal('2026-09-27T08:00'), now), /^Tomorrow 8:00\sAM$/);
  assert.match(fmtWhen(fromSfLocal('2026-09-29T08:00'), now), /^Tue 8:00\sAM$/);
  // 11:30 PM in SF is already the next day in New York; still "today" here.
  assert.match(fmtWhen(fromSfLocal('2026-09-26T23:30'), now), /^11:30\sPM$/);
});

test('SF wall clock <-> epoch, independent of the browser time zone, across DST', () => {
  assert.equal(new Date(fromSfLocal('2026-09-28T14:00')).toISOString(), '2026-09-28T21:00:00.000Z');  // PDT, UTC-7
  assert.equal(new Date(fromSfLocal('2026-12-01T14:00')).toISOString(), '2026-12-01T22:00:00.000Z');  // PST, UTC-8
  assert.equal(toSfLocal(Date.parse('2026-09-28T21:00:00Z')), '2026-09-28T14:00');
  assert.equal(toSfLocal(fromSfLocal('2026-11-01T09:30')), '2026-11-01T09:30');                       // DST-end day
  assert.ok(Number.isNaN(fromSfLocal('nope')));
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
  // The neighbour is one long straight segment (vertices only at its ends): its middle still counts as close.
  const straight: LatLng[] = [a[0], a[29]];
  assert.ok(Math.abs(labelPoint([r(straight), r(b)], 1)[1] - -122.40) < 1e-9);
});

test('traffic: slow stretches merge per level; free-flowing and unknown ones are left to the route colour', () => {
  const coords: LatLng[] = [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5]];
  const r: Route = { dur: 1, dist: 1, summary: '', coords, steps: [], congestion: ['low', 'heavy', 'heavy', 'unknown', 'severe'] };
  assert.deepEqual(trafficRuns(r), [
    { level: 'heavy', coords: [[0, 1], [0, 2], [0, 3]] },
    { level: 'severe', coords: [[0, 4], [0, 5]] },
  ]);
  assert.deepEqual(trafficRuns({ ...r, congestion: null }), []);
});

test('spoken times pick the next occurrence, in SF time', () => {
  const pad = (n: number) => String(n).padStart(2, '0');
  const now = fromSfLocal('2026-09-26T15:00'), at = (d: number, h: number, m = 0) => fromSfLocal(`2026-09-${d}T${pad(h)}:${pad(m)}`);
  assert.equal(spokenTime('6:30', now), at(26, 18, 30));      // no am/pm at 3 PM -> this evening
  assert.equal(spokenTime('7:00 PM', now), at(26, 19));
  assert.equal(spokenTime('9 a.m.', now), at(27, 9));          // already past today -> tomorrow
  assert.equal(spokenTime('2', now), at(27, 2));               // 2 PM passed, 2 AM is next
  assert.equal(spokenTime('25:00', now), null);
  assert.equal(spokenTime('noon', now), null);
  assert.equal(spokenTime('11 pm', fromSfLocal('2026-09-30T23:30')), fromSfLocal('2026-10-01T23:00')); // month rollover
});

test('voice note never implies voice booked anything', () => {
  const chase = { label: 'Chase Center', sub: '', lat: 37.768, lon: -122.3877 };
  const v = (o: Partial<VoiceIntent>): VoiceIntent =>
    ({ transcript: 'hi', action: 'plan', destination: null, origin: null, time: null, time_mode: null, ...o });
  assert.equal(voiceNote(v({ action: 'plan_and_book', transcript: 'Book my ride to Chase Center', destination: { query: 'Chase Center', place: chase } })),
    'You said "Book my ride to Chase Center". Pick a route, then confirm to book.');
  assert.equal(voiceNote(v({ destination: { query: 'Narnia', place: null } })), 'Couldn\'t find "Narnia". Try another name.');
  assert.match(voiceNote(v({ action: 'unknown' })), /Try "Take me to/);
});
