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

test('menu bar on top of both layouts, the app icon opens the menu; layers button on both maps; one dialog host each', () => {
  assert.match(desktop, /<div className="desk">\s*<AppBar n=\{n\} \/>/);
  assert.match(mobile, /<AppBar n=\{n\} className="mob-bar" \/>/);
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
  // the route card's trace strip now opens Settings at that section
  assert.equal(count(desktop + mobile, /onTrace=\{\(\) => n\.open\('settings', 'privacy'\)\}/g), 2);
});

test('privacy switches keep their behaviour: voice hides the mic, the others shape /plan', () => {
  assert.match(parts, /if \(!usePrivacy\(\)\.privacy\.voice\) return null;/);
  assert.match(parts, /key: 'saveTrips', label: 'Save my trips'/);
  assert.match(parts, /key: 'aiText', label: 'AI-written explanations'/);
  assert.match(parts, /key: 'voice', label: 'Voice requests'/);
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
