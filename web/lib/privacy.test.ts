import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dataPath, DEFAULT_PRIVACY, parsePrivacy, planStale, privacyQuery, readPrivacy, traceLine, writePrivacy, type PlanData } from './privacy.ts';

const data = (over: Partial<PlanData> = {}): PlanData => ({
  at: '', replay: false, events: 'mongo', incidents: 'mongo', traffic: 'tiger:live', predictions: 'tiger',
  decision: 'heuristic', note: 'gemini:gemini-flash-lite-latest', stored: 'trips', trip_record: {}, ...over,
});

test('switches: saved choices over defaults, junk ignored, blocked storage still works', () => {
  assert.deepEqual(parsePrivacy(null), DEFAULT_PRIVACY);
  assert.deepEqual(parsePrivacy('{"aiText":false,"voice":"no"}'), { saveTrips: true, aiText: false, voice: true });
  assert.deepEqual(parsePrivacy('not json'), DEFAULT_PRIVACY);
  const blocked = { getItem(): never { throw new Error('denied'); }, setItem(): never { throw new Error('denied'); } };
  assert.deepEqual(readPrivacy(blocked), DEFAULT_PRIVACY);
  assert.doesNotThrow(() => writePrivacy(DEFAULT_PRIVACY, blocked));
});

test('only switches that are off reach /plan', () => {
  assert.equal(privacyQuery(DEFAULT_PRIVACY), '');
  assert.equal(privacyQuery({ saveTrips: false, aiText: false, voice: true }), '&save=false&ai_text=false');
  assert.equal(planStale(DEFAULT_PRIVACY, { ...DEFAULT_PRIVACY, voice: false }), false); // voice doesn't change a plan
  assert.equal(planStale(DEFAULT_PRIVACY, { ...DEFAULT_PRIVACY, aiText: false }), true);
});

test('data path names who got what, in order', () => {
  const on = dataPath(data(), 'mapbox');
  assert.deepEqual(on.map(s => s.who), ['Mapbox', 'transPEAKtation data', 'Rule-based estimate', 'Google Gemini', 'Trip log']);
  assert.deepEqual(on.filter(s => s.outside).map(s => s.who), ['Mapbox', 'Google Gemini']);
  assert.equal(on[1].did, 'Events: live list. Closures: city feeds. Traffic: live.');

  const off = dataPath(data({ decision: 'ml:gbm-v1', note: 'template (ai text off)', stored: 'off', events: 'demo', traffic: 'unavailable' }), 'osrm');
  assert.equal(off[2].who, 'Route model');
  assert.ok(off[2].ai && off[2].did.startsWith('gbm-v1'));
  assert.deepEqual([off[3].off, off[4].off], [true, true]);             // the rider's two switches show as off
  assert.match(off[3].did, /nothing went to Google/);
  assert.equal(off[1].did, 'Events: demo events. Closures: city feeds. Traffic: unavailable.');
  assert.equal(dataPath(data({ note: 'template (no GEMINI_API_KEY)' }), 'mapbox')[3].off, false); // not the rider's doing
  assert.match(dataPath(data({ stored: 'replay' }), 'mapbox')[4].did, /replay/);
});

test('trace line under the card', () => {
  assert.equal(traceLine(data()), 'Rule-based · Gemini text · Saved (area)');
  assert.equal(traceLine(data({ decision: 'ml:x', note: 'template (ai text off)', stored: 'off' })), 'AI model · No AI text · Not saved');
});
