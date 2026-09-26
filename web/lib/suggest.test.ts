import { test } from 'node:test';
import assert from 'node:assert/strict';
import { smartSuggestions } from './suggest.ts';

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
