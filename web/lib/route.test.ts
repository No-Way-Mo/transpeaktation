import { test } from 'node:test';
import assert from 'node:assert/strict';

process.env.TZ = 'America/New_York'; // a device outside SF: every clock time must still be Pacific
import { fmtDist, fmtWhen, fromPtInput, labelPoint, longerThanItLooks, mins, planPath, ptInput, ptTime, sfDays, routeTag, spokenTime, stepIcon, stepText, trafficRuns, voiceNote, type LatLng, type Prediction, type Route, type Step, type VoiceIntent } from './route.ts';

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

test('departure times', () => {
  const now = ptTime(2026, 9, 26, 15, 0);
  assert.match(fmtWhen(ptTime(2026, 9, 26, 19, 15), now), /^7:15\sPM$/);
  assert.match(fmtWhen(ptTime(2026, 9, 26, 22, 30), now), /^10:30\sPM$/);        // 1:30 AM in New York: still "today"
  assert.match(fmtWhen(ptTime(2026, 9, 26, 23, 30), now), /^11:30\sPM$/);        // already the next day in New York
  assert.match(fmtWhen(ptTime(2026, 9, 27, 8, 0), now), /^Tomorrow 8:00\sAM$/);
  assert.match(fmtWhen(ptTime(2026, 9, 29, 8, 0), now), /^Tue 8:00\sAM$/);
  assert.equal(sfDays(ptTime(2026, 9, 26, 23, 59), ptTime(2026, 9, 26, 0, 0)), 0);
  assert.equal(sfDays(ptTime(2026, 10, 1, 0, 0), ptTime(2026, 9, 30, 23, 59)), 1);  // month rollover
});

test('picker times are San Francisco time, across DST', () => {
  assert.equal(fromPtInput('2026-09-19T18:30'), Date.parse('2026-09-20T01:30:00Z')); // PDT, UTC-7
  assert.equal(fromPtInput('2026-12-01T08:00'), Date.parse('2026-12-01T16:00:00Z')); // PST, UTC-8
  assert.equal(fromPtInput('2026-11-01T12:00'), Date.parse('2026-11-01T20:00:00Z')); // DST ended that morning
  assert.equal(ptInput(Date.parse('2026-09-20T01:30:00Z')), '2026-09-19T18:30');
  assert.equal(ptInput(fromPtInput('2027-03-14T09:05')!), '2027-03-14T09:05');       // DST starts that morning
  assert.equal(ptInput(fromPtInput('2026-11-01T09:30')!), '2026-11-01T09:30');       // DST-end day round trip
  assert.equal(fromPtInput(''), null);
  assert.equal(fromPtInput('nope'), null);
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

test('spoken times pick the next occurrence', () => {
  const now = ptTime(2026, 9, 26, 15, 0), at = (d: number, h: number, m = 0) => ptTime(2026, 9, d, h, m);
  assert.equal(spokenTime('6:30', now), at(26, 18, 30));      // no am/pm at 3 PM -> this evening
  assert.equal(spokenTime('7:00 PM', now), at(26, 19));
  assert.equal(spokenTime('9 a.m.', now), at(27, 9));          // already past today -> tomorrow
  assert.equal(spokenTime('2', now), at(27, 2));               // 2 PM passed, 2 AM is next
  assert.equal(spokenTime('25:00', now), null);
  assert.equal(spokenTime('noon', now), null);
  assert.equal(spokenTime('11 pm', ptTime(2026, 9, 30, 23, 30)), ptTime(2026, 10, 1, 23, 0)); // month rollover
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

test('plan query: past times clamp to now unless replaying', () => {
  const a = { label: 'A', sub: '', lat: 37.788, lon: -122.4075 }, b = { label: 'B', sub: '', lat: 37.7786, lon: -122.3893 };
  const now = Date.parse('2026-09-26T20:00:00Z'), past = Date.parse('2026-09-20T01:30:00Z');
  assert.equal(planPath(a, b, { mode: 'now', at: 0 }, now), '/plan?from=-122.4075,37.788&to=-122.3893,37.7786');
  assert.match(planPath(a, b, { mode: 'depart', at: past }, now, false), /depart_at=2026-09-26T20%3A00%3A00.000Z$/);
  assert.match(planPath(a, b, { mode: 'arrive', at: past }, now, true), /arrive_by=2026-09-20T01%3A30%3A00.000Z&replay=true$/);
  assert.doesNotMatch(planPath(a, b, { mode: 'depart', at: now + 864e5 }, now, true), /replay/); // future: plain plan
});

test('longerThanItLooks: normal routes warn when api/ estimates a minute or more on top of the provider ETA', () => {
  const rt = { dur: 360 } as Route;
  const pred = (delay: number, blocked = false) => ({ blocked, estimate: { dur: 360 + delay, delay, why: ['AMZN Unboxed at Howard St'] } }) as Prediction;
  assert.deepEqual(longerThanItLooks(rt, pred(130)), { tag: '+2 min events', note: 'Mapbox says 6 min; AMZN Unboxed at Howard St may add ~2 min.' });
  assert.equal(longerThanItLooks(rt, pred(40)), null);   // under a minute: not worth a warning
  assert.equal(longerThanItLooks(rt, undefined), null);  // no plan yet
  assert.equal(longerThanItLooks(rt, pred(1200, true))!.tag, 'Closure ahead');
});
