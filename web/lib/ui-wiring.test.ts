// No DOM test runner in this package (node --test only), so these check the wiring in the layout source: where the
// menu, layers button, Settings, theme and AI & privacy controls live, and that the old standalone buttons are gone.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = (f: string) => readFileSync(new URL(`../app/${f}`, import.meta.url), 'utf8');
const desktop = src('desktop.tsx'), mobile = src('mobile.tsx'), parts = src('parts.tsx'), menu = src('menu.tsx'), map = src('map-view.tsx');
const count = (s: string, re: RegExp) => (s.match(re) ?? []).length;

test('old standalone theme toggle and AI & privacy button are gone', () => {
  for (const s of [desktop, mobile, parts, menu]) {
    assert.doesNotMatch(s, /ThemeToggle|AiButton|theme-btn|ai-btn|aiOpen/);
  }
});

test('desktop: menu bar, the app icon opens the menu; phone: a floating ☰ opens the same menu; layers button on both maps; one dialog host each', () => {
  assert.match(desktop, /<div className="desk">\s*<AppBar n=\{n\} \/>/);
  assert.match(mobile, /<MenuButton n=\{n\} \/>/);                                  // phone: floating ☰, no bar
  assert.doesNotMatch(mobile, /<AppBar /);
  assert.match(menu, /className="layers-btn" data-nav-home aria-label="Open menu"[\s\S]{0,200}?n\.toggle\('menu'\)/);
  assert.match(menu, /data-nav-home aria-label="Main menu"[\s\S]{0,200}?<Logo /);
  assert.doesNotMatch(desktop + mobile, /MainMenu|<Icon name="menu"/);
  assert.equal(count(desktop, /<MapLayers /g), 1);
  assert.equal(count(mobile, /<MapLayers /g), 1);
  assert.equal(count(desktop, /<NavDialogs /g), 1);
  assert.equal(count(mobile, /<NavDialogs /g), 1);
});

test('phone start row: one search bar with the mic inside it; layers button is a plain on/off toggle', () => {
  assert.match(mobile, /<div className="where-to fake">[\s\S]{0,300}?<MicButton p=\{p\} \/>\s*<\/div>/);
  assert.match(menu, /className="layers-btn" aria-label="Map layers" aria-pressed=\{on\}/);
  assert.doesNotMatch(menu, /LayersBody|BottomSheet/);
});

test('theme is set only in Settings → Appearance (System / Light / Dark)', () => {
  const setters = [desktop, mobile, parts, menu, map].map(s => count(s, /setPref\(/g));
  assert.deepEqual(setters, [0, 0, 0, 1, 0]);
  assert.match(menu, /id: 'system', label: 'System'/);
});

test('AI & privacy exists once, inside Settings, with its original wording', () => {
  assert.equal(count(desktop + mobile, /<AiPrivacy /g), 0);
  assert.equal(count(menu, /<AiPrivacy /g), 1);
  assert.match(parts, /Every service and model that touches your trip, and the switches that control them\./);
  assert.match(parts, /'Where your trip goes'/);
  assert.match(menu, /'AI & privacy'/);
  // no per-trip AI / privacy strip under the route card: Settings → AI & Privacy covers it
  assert.doesNotMatch(desktop + mobile + parts, /trace-strip|onTrace/);
});

test('privacy switches keep their behaviour: voice hides the mic, the others shape /plan', () => {
  assert.match(parts, /if \(!usePrivacy\(\)\.privacy\.voice\) return null;/);
  assert.match(parts, /key: 'saveTrips', label: 'Save my trips'/);
  assert.match(parts, /key: 'aiText', label: 'AI-written explanations'/);
  assert.match(parts, /key: 'voice', label: 'Voice requests'/);
});

test('setting off tells the API (road reservation), on both layouts', () => {
  assert.match(mobile, /className="start" onClick=\{\(\) => \{[^}]*p\.start\(\);/);
  assert.match(desktop, />Directions<\/button>/);
  assert.match(desktop, /setSteps\(true\); setStep\(-1\); p\.start\(\);/);
});

test('map layers are wired to what the map draws', () => {
  assert.match(map, /const events = eventPins \? latest\.current\.events : undefined;/);
  assert.match(map, /if \(traffic\) for \(const run of trafficRuns\(r\)\)/);
  assert.match(desktop, /\{prefs\.eventPins && (MAP_EXPERIMENT !== 'snapmap' && )?<EventLegend /); // snapmap draws its own legend
});

test('notifications are a "Coming soon" note only: no permission prompt, no switch', () => {
  assert.doesNotMatch(menu, /Notification\.requestPermission|new Notification\(/);
  assert.match(menu, /Routine disruption alerts<\/span><span className="tag off">Coming soon/);
});

test('navigation arrival comes from the rider position (GPS or demo), not a button, and closes navigation', () => {
  assert.doesNotMatch(mobile, /onClick=\{p\.arrived\}/);                  // no manual "Arrived" in the nav bar
  // device mode: one watcher, only while navigating; demo mode never asks for location
  assert.match(mobile, /const gps = usePosition\(nav && !navArrived && !demo\);/);
  assert.match(mobile, /navFix\(demo \? 'demo' : 'device', r, demoStep, gps\)/); // one pipeline for both sources
  assert.match(mobile, /if \(isArrived\(fix, r\)\) \{/);
  assert.match(mobile, /setTimeout\(\(\) => finishRef\.current\('arrived'\), ARRIVED_EXIT_MS\)/);
  assert.match(mobile, /onClick=\{\(\) => finishNavigation\(navArrived \? 'arrived' : 'cancelled'\)\}>End</);
  assert.match(mobile, /\{!navArrived && \(\s*<div className="nav-stats">/);  // no stale "1.6 mi remaining" once arrived
});

test('the demo start is defined once', () => {
  const lib = (f: string) => readFileSync(new URL(`./${f}`, import.meta.url), 'utf8');
  for (const s of [desktop, mobile, parts, menu, map, lib('route.ts'), lib('use-route-planner.ts')]) assert.doesNotMatch(s, /37\.788\b/);
  assert.match(lib('location.ts'), /DEMO_START = \{ name: 'Union Square', lat: 37\.788, lon: -122\.4075 \}/);
  assert.match(menu, /<legend className="eyebrow">Location mode<\/legend>/);
});

test('device mode: the maneuver banner is not a button, only demo taps advance', () => {
  assert.match(mobile, /const TurnBox = demo \? 'button' : 'div';/);
  assert.match(mobile, /<TurnBox className="turn" onClick=\{demo \? \(\) => setDemoStep\(/);
  assert.match(mobile, /\{demo && <span className="hint">Next<\/span>\}/);
  assert.doesNotMatch(mobile, /goTo\(/);                                   // the old device-mode turn preview is gone
  assert.equal(count(mobile, /setStep\(g\.step\)|setStep\(Math\.max\(0, steps\.length - 1\)\)/g), 2); // only progress/arrival set the turn
});
