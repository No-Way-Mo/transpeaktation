import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_MAP_PREFS, LAYERS, layerOn, MAP_KEY, parseMapPrefs, readMapPrefs, toggleLayer, writeMapPrefs } from './map-prefs.ts';

function store(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, m };
}
const blocked = { getItem(): never { throw new Error('denied'); }, setItem(): never { throw new Error('denied'); } };

test('defaults: standard map, event pins and route traffic on', () => {
  assert.deepEqual(DEFAULT_MAP_PREFS, { style: 'standard', eventPins: true, traffic: true });
  assert.deepEqual(parseMapPrefs(null), DEFAULT_MAP_PREFS);
  assert.deepEqual(parseMapPrefs('not json'), DEFAULT_MAP_PREFS);
  assert.deepEqual(parseMapPrefs('{"style":"terrain","eventPins":"no","traffic":false}'), { style: 'standard', eventPins: true, traffic: false });
});

test('choices persist: written, then read back on the next visit', () => {
  const s = store();
  const p = toggleLayer({ ...DEFAULT_MAP_PREFS, style: 'satellite' }, 'eventPins');
  writeMapPrefs(p, s);
  assert.deepEqual(readMapPrefs(s), { style: 'satellite', eventPins: false, traffic: true });
  assert.ok(s.m.has(MAP_KEY));
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
