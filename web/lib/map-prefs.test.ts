import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_MAP_PREFS, LAYERS, layerOn, MAP_KEY, overlaysOn, parseMapPrefs, readMapPrefs, setOverlays, toggleLayer, writeMapPrefs } from './map-prefs.ts';

function store(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, m };
}
const blocked = { getItem(): never { throw new Error('denied'); }, setItem(): never { throw new Error('denied'); } };

test('defaults: standard map, event pins and route traffic on, demo location', () => {
  assert.deepEqual(DEFAULT_MAP_PREFS, { style: 'standard', eventPins: true, traffic: true, location: 'demo' });
  assert.deepEqual(parseMapPrefs(null), DEFAULT_MAP_PREFS);
  assert.deepEqual(parseMapPrefs('not json'), DEFAULT_MAP_PREFS);
  assert.deepEqual(parseMapPrefs('{"style":"terrain","eventPins":"no","traffic":false}'), { style: 'standard', eventPins: true, traffic: false, location: 'demo' });
});

test('choices persist: written, then read back on the next visit', () => {
  const s = store();
  const p = toggleLayer({ ...DEFAULT_MAP_PREFS, style: 'satellite' }, 'eventPins');
  writeMapPrefs(p, s);
  assert.deepEqual(readMapPrefs(s), { style: 'satellite', eventPins: false, traffic: true, location: 'demo' });
  assert.ok(s.m.has(MAP_KEY));
});

test('location mode: demo by default, device persists, anything else falls back to demo', () => {
  const s = store();
  writeMapPrefs({ ...DEFAULT_MAP_PREFS, location: 'device' }, s);
  assert.equal(readMapPrefs(s).location, 'device');
  assert.equal(parseMapPrefs('{"location":"miami"}').location, 'demo');
  assert.equal(parseMapPrefs('{"style":"satellite"}').location, 'demo');   // prefs saved before this setting existed
});

test('blocked storage: defaults, and writing does not throw', () => {
  assert.deepEqual(readMapPrefs(blocked), DEFAULT_MAP_PREFS);
  assert.deepEqual(readMapPrefs(undefined), DEFAULT_MAP_PREFS);
  assert.doesNotThrow(() => writeMapPrefs(DEFAULT_MAP_PREFS, blocked));
});

test('Event Pins and Traffic toggle; a second toggle turns them back on', () => {
  let p = toggleLayer(DEFAULT_MAP_PREFS, 'eventPins');
  assert.equal(p.eventPins, false);
  p = toggleLayer(p, 'traffic');
  assert.equal(p.traffic, false);
  assert.deepEqual(toggleLayer(toggleLayer(p, 'eventPins'), 'traffic'), DEFAULT_MAP_PREFS);
});

test('map layers button: one tap hides every layer, the next shows them all; style untouched', () => {
  const sat = { ...DEFAULT_MAP_PREFS, style: 'satellite' as const };
  assert.equal(overlaysOn(sat), true);
  const off = setOverlays(sat, !overlaysOn(sat));
  assert.deepEqual(off, { style: 'satellite', eventPins: false, traffic: false, location: 'demo' });
  assert.equal(overlaysOn(off), false);
  assert.deepEqual(setOverlays(off, !overlaysOn(off)), sat);
  // one layer switched off in Settings: the button still reads "on", and a tap turns both off
  const mixed = toggleLayer(DEFAULT_MAP_PREFS, 'traffic');
  assert.equal(overlaysOn(mixed), true);
  assert.equal(overlaysOn(setOverlays(mixed, !overlaysOn(mixed))), false);
});

test('unavailable layers cannot be switched on and always read as off', () => {
  const off = LAYERS.filter(l => !l.key);
  assert.deepEqual(off.map(l => [l.id, l.status]), [['eventActivity', 'Coming soon'], ['roadDisruptions', 'Unavailable']]);
  for (const l of off) {
    assert.equal(toggleLayer(DEFAULT_MAP_PREFS, l.id), DEFAULT_MAP_PREFS); // unchanged, same object
    assert.equal(layerOn(DEFAULT_MAP_PREFS, l), false);
  }
  assert.equal(toggleLayer(DEFAULT_MAP_PREFS, 'nope'), DEFAULT_MAP_PREFS);
  // every working layer has no "unavailable" status, and every unavailable one has one
  assert.ok(LAYERS.every(l => !!l.key !== !!l.status));
});

test('panel layout: event intelligence then mobility, in the agreed order', () => {
  assert.deepEqual(LAYERS.map(l => `${l.group}/${l.label}`), [
    'Event intelligence/Event Activity', 'Event intelligence/Event Pins', 'Mobility/Traffic', 'Mobility/Road Disruptions',
  ]);
});
