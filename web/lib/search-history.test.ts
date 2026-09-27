import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { HISTORY_KEY, HISTORY_MAX, parseHistory, readHistory, withSearch, writeHistory } from './search-history.ts';
import type { Place } from './route.ts';

function store(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, removeItem: (k: string) => { m.delete(k); }, m };
}
const blocked = { getItem(): never { throw new Error('denied'); }, setItem(): never { throw new Error('denied'); }, removeItem(): never { throw new Error('denied'); } };
const place = (label: string, lat: number, lon = -122.4, sub = `${label} St`): Place => ({ label, sub, lat, lon });
const oracle = place('Oracle Park', 37.7786, -122.3893, '24 Willie Mays Plaza');
const chase = place('Chase Center', 37.768, -122.3877, '1 Warriors Way');

test('starts empty when nothing is stored', () => {
  assert.deepEqual(readHistory(store()), []);
  assert.deepEqual(readHistory(undefined), []);
});

test('adding a search puts it in history', () => {
  assert.deepEqual(withSearch([], oracle), [oracle]);
});

test('newest first', () => {
  const h = withSearch(withSearch([], oracle), chase);
  assert.deepEqual(h.map(p => p.label), ['Chase Center', 'Oracle Park']);
});

test('persists: written, then read back on the next visit', () => {
  const s = store();
  writeHistory(withSearch(withSearch([], oracle), chase), s);
  assert.ok(s.m.has(HISTORY_KEY));
  assert.deepEqual(readHistory(s), [chase, oracle]);
  writeHistory([], s);  // cleared: the key goes away
  assert.ok(!s.m.has(HISTORY_KEY));
});

test('same place again moves to the top with its fresh data, no duplicate row', () => {
  const h = withSearch(withSearch(withSearch([], oracle), chase), { ...oracle, sub: '24 Willie Mays Plz' });
  assert.deepEqual(h.map(p => p.label), ['Oracle Park', 'Chase Center']);
  assert.equal(h[0].sub, '24 Willie Mays Plz');
  // matched by name + address too (case-insensitive), even if the geocoder moved the pin a bit
  const moved = withSearch(h, { ...chase, label: 'chase center', lat: chase.lat + 0.001 });
  assert.equal(moved.length, 2);
  assert.equal(moved[0].lat, chase.lat + 0.001);
});

test(`keeps the ${HISTORY_MAX} most recent`, () => {
  let h: Place[] = [];
  for (let i = 0; i < HISTORY_MAX + 5; i++) h = withSearch(h, place(`P${i}`, 37.7 + i * 0.01));
  assert.equal(h.length, HISTORY_MAX);
  assert.equal(h[0].label, `P${HISTORY_MAX + 4}`);
  assert.equal(h.at(-1)!.label, 'P5');
});

test('"Current location" and extra fields are never stored', () => {
  assert.deepEqual(withSearch([], { ...oracle, current: true }), []);
  assert.deepEqual(withSearch([], { ...oracle, extra: 1 } as Place), [oracle]);
});

test('malformed storage never throws: bad JSON, wrong shape, bad entries, blocked storage', () => {
  for (const raw of ['not json', '{"label":"x"}', '42', 'null', '""']) assert.deepEqual(readHistory(store({ [HISTORY_KEY]: raw })), []);
  const mixed = JSON.stringify([null, 'Oracle', { label: 'NaN', sub: '', lat: 'x', lon: 1 }, { label: '', sub: '', lat: 1, lon: 1 },
    oracle, { ...oracle }, chase]);
  assert.deepEqual(parseHistory(mixed), [oracle, chase]);
  assert.deepEqual(parseHistory(JSON.stringify(Array.from({ length: 30 }, (_, i) => place(`P${i}`, 37 + i)))).length, HISTORY_MAX);
  assert.deepEqual(readHistory(blocked), []);
  assert.doesNotThrow(() => writeHistory([oracle], blocked));
});

// No DOM test runner here (node --test only): check the wiring in the source, like lib/ui-wiring.test.ts.
const src = (f: string) => readFileSync(new URL(f, import.meta.url), 'utf8');
const parts = src('../app/parts.tsx'), mobile = src('../app/mobile.tsx'), route = src('./route.ts'), planner = src('./use-route-planner.ts');

test('no hardcoded recents; both Recent lists are the stored history', () => {
  assert.doesNotMatch(route + parts + mobile, /RECENT\b|Willie Mays|Warriors Way/);
  assert.match(parts, /const recent = useSearchHistory\(\);/);
  assert.match(parts, /No recent searches/);
  assert.match(parts, /if \(!q\.trim\(\)\) return <RecentPlaces p=\{p\} \/>;/);
  assert.match(mobile, /<RecentPlaces p=\{p\} \/>/);
});

test('a recent row plans it exactly like a search result: p.go with the stored place', () => {
  assert.match(parts, /recent\.map\(pl => <PlaceRow [^>]*onPick=\{\(\) => p\.go\(pl\)\} \/>\)/);
  assert.match(parts, /results\.map\(pl => <PlaceRow [^>]*onPick=\{\(\) => p\.go\(pl\)\} plain \/>\)/);
});

test('picks are saved: search results / recents (go), route-screen suggestions (pick), voice destination', () => {
  assert.match(planner, /const go = \(dest: Place\) => \{\s*addSearchHistoryItem\(dest\);/);
  assert.match(planner, /const pick = \(field: Field, p: Place\) => \{\s*addSearchHistoryItem\(p\);/);
  assert.match(planner, /if \(!dest\) return false;\s*addSearchHistoryItem\(dest\);/);
});
