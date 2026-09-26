import { test } from 'node:test';
import assert from 'node:assert/strict';
import { predict, smartSuggestions, transPeakPick } from './suggest.ts';
import type { LatLng, Route } from './route.ts';

const at = (h: number, m = 0) => { const d = new Date(2026, 8, 26); d.setHours(h, m, 0, 0); return d; };
const place = { label: 'Moscone Center', sub: 'SoMa', lat: 37.784, lon: -122.401 };

test('event venue: drop-off first, plus "leave at" when the game is later today', () => {
  const s = smartSuggestions('giants', [], at(15));
  assert.equal(s.length, 2);
  assert.equal(s[0].dest.sub, 'drop-off at 4th & King');   // routes to the drop-off, not the stadium
  assert.equal(s[0].badge, 'Saves ~8 min');
  assert.equal(s[1].leaveMin, 195);                         // 3:00 PM -> leave 6:15 PM
  assert.equal(s[1].dest.lat, 37.7786);
});

test('no "leave at" once departure time has passed or is more than 6 h away', () => {
  assert.equal(smartSuggestions('oracle', [], at(18, 30)).length, 1);
  assert.equal(smartSuggestions('oracle', [], at(9)).length, 1);
  assert.equal(smartSuggestions('ferry', [], at(9)).length, 1); // no start time at all
});

test('matching: venue prefix, keyword prefix, keyword inside a longer query', () => {
  for (const q of ['Chase', 'warr', 'going to the warriors game']) assert.equal(smartSuggestions(q, [], at(12))[0].dest.label, 'Chase Center', q);
});

test('non-event place: one "leave now" card for the top result; nothing without results or text', () => {
  const [s] = smartSuggestions('moscone', [place], at(12));
  assert.equal(s.clear, true);
  assert.equal(s.dest, place);
  assert.deepEqual(smartSuggestions('moscone', [], at(12)), []);
  assert.deepEqual(smartSuggestions('  ', [place], at(12)), []);
});

// Two 10-minute routes: one straight past Oracle Park, one ~1 km west of it.
const line = (lon: number): LatLng[] => Array.from({ length: 11 }, (_, i) => [37.774 + i * 0.001, lon]); // clear of Chase Center
const route = (coords: LatLng[], dur = 600): Route => ({ dur, dist: 2000, summary: '', coords, steps: [] });
const past = route(line(-122.3893)), around = route(line(-122.401), 660);

test('predict: event delay only near the venue and only while the crowd is there', () => {
  assert.equal(predict(past, at(12).getTime()).delay, 0);                    // noon: no crowd
  assert.equal(Math.round(predict(past, at(18, 30).getTime()).delay), 480);  // in the window: full 8 min
  const edge = predict(past, at(17, 20).getTime()).delay;                    // ramping in (passes ~17:25)
  assert.ok(edge > 0 && edge < 480, String(edge));
  assert.equal(predict(around, at(18, 30).getTime()).delay, 0);             // ~1 km away
});

test('transPeakPick: avoids the event route when it saves time, else explains the extra time', () => {
  const t = at(18, 30).getTime();
  const pick = transPeakPick([past, around], [t, t]);
  assert.equal(pick.best, 1);
  assert.equal(pick.tag, 'Saves ~7 min');                  // 18 min vs 11 min
  assert.equal(transPeakPick([past, around], [at(12).getTime(), at(12).getTime()]).tag, 'Clear');
  assert.equal(transPeakPick([past], [t]).tag, '+8 min events');
});
