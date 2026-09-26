import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_EVENT_RADIUS_METERS, eventInTime, routeContext, type MapEvent } from './context.ts';
import {
  EVENT_GLYPH, EVENT_PIN_COLORS, EVENT_PIN_PX, EVENT_PIN_SELECTED_PX, eventDetail, eventPin, IMPACT_LABEL, impactAreas, impactCircleStyle, legendItems,
} from './event-map.ts';
import type { LatLng, Route } from './route.ts';

const ev = (id: string, extra: Partial<MapEvent> = {}): MapEvent => ({
  id, name: `Event ${id}`, category: 'special_event', venue: 'Oracle Park', lat: 37.7786, lon: -122.3893,
  start_time: '2026-09-27T02:05:00Z', end_time: '2026-09-27T05:00:00Z', source: 'predicthq', status: 'active',
  road_closure_ids: [], ...extra,
});
const CATEGORIES = ['sports', 'concert', 'performing_arts', 'conference', 'festival', 'community', 'parade', 'market', 'special_event', null];

test('every category gets the same default map pin; the pin never carries the category', () => {
  const pins = CATEGORIES.map(category => eventPin(ev('x', { category, name: 'Same name' }), false));
  for (const p of pins) assert.deepEqual(p, pins[0]);
  assert.deepEqual(pins[0], { className: 'event-pin', size: EVENT_PIN_PX, html: EVENT_GLYPH, title: 'Event: Same name' });
  for (const c of ['sports', 'concert', 'conference', 'Sports', 'Conference']) assert.ok(!JSON.stringify(pins[0]).includes(c), c);
  assert.ok(EVENT_PIN_PX >= 30 && EVENT_PIN_PX <= 32 && EVENT_PIN_SELECTED_PX >= 36 && EVENT_PIN_SELECTED_PX <= 38);
});

test('selected state: the same pin, slightly bigger and marked; its circle a little stronger', () => {
  const pin = eventPin(ev('x', { category: 'sports' }), true);
  assert.deepEqual(pin, { className: 'event-pin on', size: EVENT_PIN_SELECTED_PX, html: EVENT_GLYPH, title: 'Event: Event x' });
  const off = impactCircleStyle({ selected: false, routeActive: false }), on = impactCircleStyle({ selected: true, routeActive: false });
  assert.ok(on.fillOpacity > off.fillOpacity && on.opacity > off.opacity && on.weight >= off.weight);
});

test('selecting an event reveals its category (from the API) in the detail card, plus only fields /events has', () => {
  const d = eventDetail(ev('g', { name: 'Giants vs. Dodgers', category: 'sports' }));
  assert.equal(d.name, 'Giants vs. Dodgers');
  assert.deepEqual(d.category, { label: 'Sports', kind: 'sports' });
  assert.equal(d.venue, 'Oracle Park');
  assert.equal(d.when, 'Sat, Sep 26, 7:05 PM – 10:00 PM');         // SF time
  assert.deepEqual(d.impact, { label: 'Estimated event impact area', radius: '~0.3 mi radius', source: 'default' });
  assert.deepEqual(Object.keys(d).sort(), ['category', 'impact', 'name', 'venue', 'when']); // no attendance / delay / importance
  assert.deepEqual(eventDetail(ev('s')).category, { label: 'Special event', kind: 'other' });
  assert.equal(eventDetail(ev('n', { category: null })).category, null);
});

test('radius: the documented default when the API has none, the API value when it does', () => {
  assert.equal(DEFAULT_EVENT_RADIUS_METERS, 500);
  assert.equal(eventDetail(ev('a')).impact.source, 'default');
  const api = eventDetail(ev('b', { impactRadiusMeters: 1609 }));
  assert.deepEqual(api.impact, { label: IMPACT_LABEL, radius: '~1.0 mi radius', source: 'api' });
});

test('circles: palette colours, never traffic colours; fainter under an active route', () => {
  const city = impactCircleStyle({ selected: false, routeActive: false }), route = impactCircleStyle({ selected: false, routeActive: true });
  assert.equal(city.fillColor, '#52b69a');
  assert.ok(['#168aad', '#1a759f'].includes(city.color));
  assert.ok(city.fillOpacity >= 0.08 && city.fillOpacity <= 0.12 && city.opacity >= 0.35 && city.opacity <= 0.45);
  assert.ok(route.fillOpacity < city.fillOpacity && route.opacity < city.opacity);
});

test('circles: one per place, never merged across places; the same spot drawn once (no stacked-opacity hotspot)', () => {
  const venue = (id: string) => ev(id, { lat: 37.780138, lon: -122.394055 });
  const nearby = ev('near', { lat: 37.7805, lon: -122.3945 });            // ~60 m away: overlapping, still its own
  const bigger = ev('big', { lat: 37.780138, lon: -122.394055, impactRadiusMeters: 1200 });
  const areas = impactAreas([venue('a'), venue('b'), ev('c', { lat: 37.78014, lon: -122.39406 }), nearby, bigger], 'b');
  assert.deepEqual(areas.map(a => [a.radius, a.ids, a.selected]), [
    [1200, ['big'], false],                 // biggest first
    [DEFAULT_EVENT_RADIUS_METERS, ['a', 'b', 'c'], true],
    [DEFAULT_EVENT_RADIUS_METERS, ['near'], false],
  ]);
  assert.equal(impactAreas([ev('x', { lat: 1, lon: 1 }), ev('y', { lat: 2, lon: 2 })], null).length, 2);
});

test('pin colours are fixed, so they read the same on the light and the dark basemap', () => {
  assert.deepEqual(EVENT_PIN_COLORS, { fill: '#1a759f', accent: '#184e77', icon: '#ffffff' });
});

test('an event outside the selected time window stays hidden, however close it is', () => {
  const coords: LatLng[] = [[37.788, -122.4015], [37.7786, -122.3893]];
  const route: Route = { dur: 600, dist: 1500, summary: '', coords, steps: [] };
  const trip = { from: Date.parse('2026-09-27T12:00:00Z'), to: Date.parse('2026-09-27T12:10:00Z') }; // next morning
  const onRoute = ev('late', { lat: coords[0][0], lon: coords[0][1] });                                // ends 05:00Z
  assert.equal(eventInTime(onRoute, trip), false);
  assert.deepEqual(routeContext(route, [onRoute], [], trip).events, []);
});

test('legend: event entries only with events on the map; traffic entries only with real route traffic', () => {
  assert.deepEqual(legendItems(0, false), { events: false, traffic: false });
  assert.deepEqual(legendItems(3, false), { events: true, traffic: false });
  assert.deepEqual(legendItems(0, true), { events: false, traffic: true });
  assert.deepEqual(legendItems(5, true), { events: true, traffic: true });
});
