import { test } from 'node:test';
import assert from 'node:assert/strict';
import { smartSuggestions } from './suggest.ts';
import type { EventInfo } from './route.ts';

const at = (h: number, m = 0) => { const d = new Date(2026, 8, 26); d.setHours(h, m, 0, 0); return d; };
const place = { label: 'Moscone Center', sub: 'SoMa', lat: 37.784, lon: -122.401 };
// Shaped like api/ /events (its demo events).
const EVENTS: EventInfo[] = [
  { id: 'demo-oracle', venue: 'Oracle Park', keys: ['oracle', 'giants', 'ballpark'], title: 'Giants vs. Dodgers', time: '7:15 PM',
    start: [19, 15], lat: 37.7786, lon: -122.3893, crowd: { from: [17, 45], to: [19, 30], delay: 8 }, source: 'demo',
    drop: { label: 'drop-off at 4th & King', lat: 37.7765, lon: -122.3942, why: 'Skips the King St backup.', badge: 'Saves ~8 min' } },
  { id: 'demo-chase', venue: 'Chase Center', keys: ['chase', 'warriors', 'mission bay'], title: 'Concert', time: '8:00 PM',
    start: [20, 0], lat: 37.768, lon: -122.3877, crowd: { from: [18, 30], to: [20, 15], delay: 5 }, source: 'demo',
    drop: { label: 'drop-off at 16th & 3rd St', lat: 37.7665, lon: -122.389, why: 'Avoids the curb queue.', badge: 'Saves ~5 min' } },
  { id: 'demo-ferry', venue: 'Ferry Building', keys: ['ferry'], title: 'Farmers market', time: 'until 2:00 PM', start: null,
    lat: 37.7955, lon: -122.3937, crowd: { from: [8, 0], to: [14, 0], delay: 3 }, source: 'demo' },
];

test('event venue: drop-off first, plus "leave at" when the game is later today', () => {
  const s = smartSuggestions('giants', [], EVENTS, at(15));
  assert.equal(s.length, 2);
  assert.equal(s[0].dest.sub, 'drop-off at 4th & King');   // routes to the drop-off, not the stadium
  assert.equal(s[0].badge, 'Saves ~8 min');
  assert.equal(s[1].leaveMin, 195);                         // 3:00 PM -> leave 6:15 PM
  assert.equal(s[1].dest.lat, 37.7786);
});

test('no "leave at" once departure time has passed or is more than 6 h away', () => {
  assert.equal(smartSuggestions('oracle', [], EVENTS, at(18, 30)).length, 1);
  assert.equal(smartSuggestions('oracle', [], EVENTS, at(9)).length, 1);
  assert.equal(smartSuggestions('ferry', [], EVENTS, at(9)).length, 1); // no start time at all
});

test('event without a curated drop-off routes to the venue itself', () => {
  const [s] = smartSuggestions('ferry', [], EVENTS, at(9));
  assert.equal(s.dest.label, 'Ferry Building');
  assert.equal(s.dest.lat, 37.7955);
  assert.match(s.sub, /~3 min of crowd traffic/);
});

test('matching: venue prefix, keyword prefix, keyword inside a longer query', () => {
  for (const q of ['Chase', 'warr', 'going to the warriors game']) assert.equal(smartSuggestions(q, [], EVENTS, at(12))[0].dest.label, 'Chase Center', q);
});

test('non-event place, or no events loaded: one "leave now" card for the top result; nothing without results or text', () => {
  const [s] = smartSuggestions('moscone', [place], EVENTS, at(12));
  assert.equal(s.clear, true);
  assert.equal(s.dest, place);
  assert.equal(smartSuggestions('giants', [place], [], at(15))[0].clear, true);
  assert.deepEqual(smartSuggestions('moscone', [], EVENTS, at(12)), []);
  assert.deepEqual(smartSuggestions('  ', [place], EVENTS, at(12)), []);
});
