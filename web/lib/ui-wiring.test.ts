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

test('menu bar on top of both layouts, the ☰ opens the menu; layers button on both maps; one dialog host each', () => {
  assert.match(desktop, /<div className="desk">\s*<AppBar n=\{n\} \/>/);
  assert.match(mobile, /<AppBar n=\{n\} className="mob-bar" \/>/);
  assert.match(menu, /data-nav-home aria-label="Open menu"[\s\S]{0,200}?<Icon name="menu" /); // ☰ before the wordmark
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
  assert.match(map, /const events = eventPins \? liveEvents\(latest\.current\.events \?\? \[\], latest\.current\.eventsAt \?\? Date\.now\(\)\) : undefined;/);
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

// ---------- community events ----------
const host = src('host.tsx'), snapLayers = src('snapmap-layers.ts');
const lib = (f: string) => readFileSync(new URL(`./${f}`, import.meta.url), 'utf8');
const hosting = lib('use-hosting.ts'), community = lib('community.ts');

test('☰ Add Event / My Events / Saved Events open over the map on both layouts (no floating + on the map)', () => {
  assert.match(menu, /'host' in m\s*\? <button key=\{m\.id\} className=\{`menu-item\$\{m\.accent \? ' accent' : ''\}`\} onClick=\{\(\) => n\.host\(m\.id\)\}>/);
  assert.match(menu, /host: \(a: HostAction\) => \{ setNav\(CLOSED\); onHost\?\.\(a\); \}/); // closes the menu first
  for (const s of [desktop, mobile]) assert.match(s, /const h = useHosting\(\);\s*const n = useNav\((true|false), h\.start\);/);
  assert.match(hosting, /start: \(a: HostAction\) => a === 'addEvent' \? openForm\(emptyDraft\(\), null\) : a === 'myEvents' \? openMine\(\) : openSaved\(\)/);
  assert.match(mobile, /<div className="sheet host-sheet">[\s\S]{0,120}<HostViews /);     // phone: a bottom sheet over the map
  assert.match(desktop, /\{h\.view \? <HostViews /);                                      // desktop: the left panel
  assert.equal(count(mobile, /name="plus"/g), 0);
  assert.equal(count(desktop, /name="plus"/g), 1); // zoom in only
});

test('Add Event form: header, subtitle, required fields, free vs ticketed', () => {
  assert.match(host, /'Add an event'/);
  assert.match(host, /'Share what’s happening with people traveling nearby\.'/);
  for (const label of ['Event name', 'Location', 'Date', 'Start time', 'End time', 'Category', 'Admission']) assert.match(host, new RegExp(`>${label}<`));
  assert.match(host, /Choose on map/);
  assert.match(host, /\{d\.admission === 'ticketed' && \(\s*<div className="field-row ticket">/); // ticket link + price only when Ticketed
  assert.match(host, /<button className="start" disabled=\{h\.saving\} onClick=\{submit\}>/);
  assert.match(hosting, /setTried\(true\);\s*if \(!check\.body \|\| saving\) return;/);           // invalid forms never post
});

test('success state: Event added, View on map, Advertise event, Maybe later', () => {
  assert.match(host, /'Event added'/);
  assert.match(host, /'Your event has been added to the map\.'/);
  assert.match(host, /onClick=\{\(\) => h\.viewOnMap\(ev\)\}>View on map</);
  assert.match(host, /onClick=\{\(\) => h\.boost\(ev\)\}><Icon name="bolt" size=\{18\} \/>Advertise event</);
  assert.match(host, /onClick=\{h\.close\}>Maybe later</);
});

test('View on map / Show on map: closes the sheet, the map flies to the event with its card open', () => {
  assert.match(hosting, /const viewOnMap = \(ev: MapEvent\) => \{ setView\(null\); setSpotlight\(ev\); setFocus\(f => \(\{ id: ev\.id, n: \(f\?\.n \?\? 0\) \+ 1 \}\)\); \};/);
  for (const s of [desktop, mobile]) {
    assert.match(s, /withEvent\(p\.mapEvents, h\.spotlight\)/);
    assert.match(s, /focusEvent=\{h\.focus\} card=\{card\}\s*eventsAt=\{p\.when\.mode === 'now' \? null : p\.mapSpan\.from\} \/>/);
  }
  assert.match(map, /if \(snap\.current\) \{ snap\.current\.focus\(id\); return; \}/);
  assert.match(snapLayers, /focus\(id: string\): boolean \{[\s\S]{0,80}this\.select\(id, true\);/);
  assert.match(mobile, /useEffect\(\(\) => \{ if \(h\.focus\) sheet\.setIdx\(0\); \}, \[h\.focus\?\.n\]\);/);
  // an ended event isn't put back on the live map
  assert.match(host, /\{eventStatus\(ev\) !== 'Ended' && <button className="foot-alt" onClick=\{\(\) => h\.viewOnMap\(ev\)\}>Show on map<\/button>\}/);
});

test('every event card (map, My Events, Saved Events, details): View event + Directions, ⋯ from the same rules', () => {
  // lists
  assert.match(host, /onClick=\{\(\) => h\.viewEvent\(ev\)\}>View event<\/button>\s*<button className="ghost-btn" onClick=\{\(\) => onDirections\(ev\)\}>Directions</);
  assert.match(host, /const items = cardActions\(ev, \{ hosted: h\.isHost\(ev\), saved: h\.savedIds\.has\(ev\.id\), reported: h\.isReported\(ev\) \}\);/);
  // map cards
  assert.match(map, /for \(const \[a, label\] of \[\['view', 'View event'\], \['directions', 'Directions'\]\] as const\)/);
  assert.match(map, /for \(const a of c\.actions\(ev\)\)/);
  for (const s of [desktop, mobile]) {
    assert.match(s, /actions: ev => cardActions\(ev, \{ hosted: h\.isHost\(ev\), saved: h\.savedIds\.has\(ev\.id\), reported: h\.isReported\(ev\) \}\)/);
    assert.match(s, /on: \(a, ev\) => a === 'view' \? h\.viewEvent\(ev\) : a === 'directions' \? directions\(ev\) : h\.act\(a, ev\)/);
  }
});

test('Directions goes into this app’s route planner with the event as destination (no Google / Apple Maps)', () => {
  for (const s of [desktop, mobile]) assert.match(s, /const directions = \(ev: MapEvent\) => \{ h\.close\(\);[^}]*p\.go\(eventPlace\(ev\)\); \};/);
  assert.doesNotMatch(desktop + mobile + host + map + hosting, /maps\.google|google\.com\/maps|maps\.apple|maps:\/\/|comgooglemaps/);
});

test('host-only actions are re-checked on use, not just hidden (Edit / Delete need isHost; Report never on your own; anyone can Advertise)', () => {
  assert.match(hosting, /const host = isHost\(ev, hostIds\);/);
  assert.match(hosting, /else if \(a === 'report' && !host\) push\('report', ev\);/);
  assert.match(hosting, /else if \(a === 'edit' && host\)/);
  assert.match(hosting, /else if \(a === 'advertise'\) push\('boost', ev\);/);          // not a host control
  assert.match(hosting, /else if \(a === 'delete' && host\)/);
  assert.match(hosting, /boost: \(ev: MapEvent\) => push\('boost', ev\),/);
  assert.match(hosting, /if \(busy \|\| isHost\(ev, hostIds\)\) return;/);   // sendReport
  assert.match(community, /e\.source === 'community' && \(keys instanceof Set/);
  assert.match(map, /if \(c\.isHost\(ev\)\) box\.prepend/);                   // "Your event" only on your own
});

test('Saved Events vs My Events: separate menu entries and screens, both local to this browser', () => {
  assert.match(host, /title="Saved Events" sub="Events you saved on this browser\."/);
  assert.match(host, /title="My Events" sub="Events created on this browser appear here\."/);
  assert.match(host, /<b>No events yet\.<\/b>/);
  assert.match(host, /<b>No saved events\.<\/b>/);
  assert.doesNotMatch(host, /Add to list/);
  assert.match(hosting, /if \(a === 'save' \|\| a === 'unsave'\) \{ setSaved\(toggleSaved\(ev\)\);/);
});

test('Report: five reasons, optional details, never hides or deletes; Delete confirms first', () => {
  assert.match(host, /disabled=\{!reason \|\| h\.busy\}/);
  assert.match(host, /The event stays up while it’s checked\./);
  assert.match(community, /`\/events\/\$\{encodeURIComponent\(id\)\}\/report`, \{ reason, details: details\.trim\(\) \|\| null \}/);
  assert.doesNotMatch(community + hosting, /reporter_key|reporterKey|randomUUID|device_id|deviceId/);  // no identity / device id
  assert.match(host, /title="Delete event\?"/);
  assert.match(host, /onClick=\{\(\) => h\.confirmDelete\(ev\)\}/);
});

test('Advertise is a Coming soon preview: options with pills, disabled Coming soon, nothing paid, signed or marked advertised', () => {
  assert.match(host, /title=\{own \? 'Advertise your event' : 'Advertise this event'\} sub="Reach more people traveling nearby\."/);
  assert.match(host, /foot=\{<button className="start" disabled aria-describedby=\{note\}>Coming soon<\/button>\}/);
  assert.match(host, /\{PROMOTION_OPTIONS\.map\(o => \([\s\S]{0,400}\{SOON\}/);
  assert.match(host, /const SOON = <span className="soon-pill">Coming soon<\/span>;/);
  assert.match(host, /Promotion payments will be available with Solana\./);
  assert.match(host, /\{h\.isHost\(ev\) && <AnalyticsPreview \/>\}/);                   // analytics: host only, locked
  assert.doesNotMatch(host, /Continue<\/button>|lamports|\$\{?price/);
  for (const s of [host, hosting, community, map]) {
    assert.doesNotMatch(s, /signTransaction|signAndSend|sendTransaction|connectPhantom|\/boost|\/promot|status: 'active'/);
  }
});

test('host keys never go into a URL, a share link or the map', () => {
  assert.doesNotMatch(community, /\?[^'"`]*host_key|\/\$\{[^}]*host_key/);   // only ever a request-body field
  assert.doesNotMatch(map + snapLayers, /host_key|hostKeys/);
  assert.match(community, /export function shareLink\(e: Pick<MapEvent, 'id'>, origin: string\): string \{/);
});

test('ended events leave the live map at the map’s time; "Leave now" re-checks each minute without refetching', () => {
  assert.match(map, /if \(eventsAt != null\) return;\s*const t = setInterval\(draw, LIVE_RECHECK_MS\);/);
  assert.match(map, /useEffect\(draw, \[eventsAt\]\);/);                          // a new chosen time redraws at once
  assert.doesNotMatch(map, /setInterval\([^)]*fetch/);
});
