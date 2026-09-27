import { test } from 'node:test';
import assert from 'node:assert/strict';
import { applyTheme, applyThemePref, otherTheme, parseTheme, readTheme, readThemePref, resolveTheme, THEME_KEY, THEME_SCRIPT, type Theme } from './theme.ts';

/** In-memory localStorage; `broken` throws like a blocked / private-mode store. */
function store(init: Record<string, string> = {}, broken = false) {
  const m = new Map(Object.entries(init));
  return {
    getItem(k: string) { if (broken) throw new Error('blocked'); return m.get(k) ?? null; },
    setItem(k: string, v: string) { if (broken) throw new Error('blocked'); m.set(k, v); },
    m,
  };
}
/** Stand-in for <html>: records the attribute the code sets. */
function root() {
  const attrs: Record<string, string> = {};
  return { setAttribute(n: string, v: string) { attrs[n] = v; }, get theme() { return attrs['data-theme']; } };
}
/** Run the real inline <head> script against a fake browser (saved value, OS setting) and read what it set. */
function bootScript(storage: ReturnType<typeof store>, systemDark: boolean): string | undefined {
  const html = root();
  const window = { matchMedia: (q: string) => ({ matches: q === '(prefers-color-scheme: dark)' && systemDark }) };
  new Function('window', 'localStorage', 'matchMedia', 'document', THEME_SCRIPT)(
    window, { getItem: (k: string) => storage.getItem(k) }, window.matchMedia, { documentElement: html });
  return html.theme;
}

test('first visit: follows the OS / browser setting', () => {
  assert.equal(resolveTheme(null, true), 'dark');
  assert.equal(resolveTheme(null, false), 'light');
  assert.equal(bootScript(store(), true), 'dark');   // the pre-paint script agrees
  assert.equal(bootScript(store(), false), 'light');
});

test('a saved choice beats the OS setting; junk in storage is ignored', () => {
  assert.equal(resolveTheme('light', true), 'light');
  assert.equal(resolveTheme('dark', false), 'dark');
  assert.equal(resolveTheme('purple', true), 'dark');
  assert.equal(parseTheme('Dark'), null);
  assert.equal(bootScript(store({ [THEME_KEY]: 'light' }), true), 'light');
  assert.equal(bootScript(store({ [THEME_KEY]: 'dark' }), false), 'dark');
  assert.equal(bootScript(store({ [THEME_KEY]: 'purple' }), false), 'light');
});

test('switching light → dark and dark → light', () => {
  const html = root(), s = store();
  let t: Theme = resolveTheme(readTheme(s), false);  // light OS, first visit
  assert.equal(t, 'light');
  t = otherTheme(t); applyTheme(t, html, s);
  assert.equal(html.theme, 'dark');
  assert.equal(s.m.get(THEME_KEY), 'dark');
  t = otherTheme(t); applyTheme(t, html, s);
  assert.equal(html.theme, 'light');
  assert.equal(s.m.get(THEME_KEY), 'light');
});

test('the choice persists: a reload shows the saved theme even against the OS', () => {
  const s = store();
  applyTheme('dark', root(), s);                  // picked dark on a light OS...
  assert.equal(readTheme(s), 'dark');
  assert.equal(bootScript(s, false), 'dark');     // ...and the next page load starts dark, before paint
  applyTheme('light', root(), s);                 // picked light on a dark OS
  assert.equal(bootScript(s, true), 'light');
});

test('blocked storage: nothing throws, the OS setting still applies, the switch still works for this visit', () => {
  const s = store({}, true), html = root();
  assert.equal(readTheme(s), null);
  assert.equal(readTheme(undefined), null);
  assert.equal(bootScript(s, true), 'dark');
  assert.doesNotThrow(() => applyTheme('light', html, s));
  assert.equal(html.theme, 'light');
});

test('System / Light / Dark: System is "no saved choice", so the pre-paint script follows the OS', () => {
  const s = { ...store(), removeItem(k: string) { s.m.delete(k); } };
  assert.equal(readThemePref(s), 'system');
  const html = root();
  applyThemePref('dark', html, s, false);
  assert.equal(html.theme, 'dark');
  assert.equal(readThemePref(s), 'dark');
  assert.equal(bootScript(s, false), 'dark');
  applyThemePref('system', html, s, false);          // back to System on a light OS
  assert.equal(html.theme, 'light');
  assert.equal(readThemePref(s), 'system');
  assert.equal(s.m.has(THEME_KEY), false);
  assert.equal(bootScript(s, true), 'dark');         // next load follows the OS again
  applyThemePref('light', html, s, true);            // Light beats a dark OS, and persists
  assert.equal(html.theme, 'light');
  assert.equal(bootScript(s, true), 'light');
});

test('System with blocked storage: applies the OS theme and does not throw', () => {
  const s = store({}, true), html = root();
  assert.doesNotThrow(() => applyThemePref('system', html, s, true));
  assert.equal(html.theme, 'dark');
  assert.equal(readThemePref(s), 'system');
});
