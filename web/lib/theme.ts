// Light / dark theme: which one applies, where the choice is kept, and the inline script that sets it before the
// first paint (app/layout.tsx). Settings → Appearance offers System / Light / Dark; System = no saved choice. The palettes themselves are CSS tokens in app/globals.css, keyed on <html data-theme>.
// Plain TS (no DOM types needed) so `node --test` can run it directly.

export type Theme = 'light' | 'dark';
/** What the rider picked. 'system' is stored as no key at all, so the pre-paint script needs no third case. */
export type ThemePref = Theme | 'system';
export const THEME_KEY = 'transpeaktation.theme'; // localStorage key, next to 'transpeaktation.compass'
export const SYSTEM_DARK = '(prefers-color-scheme: dark)';

type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem?(k: string): void };
type Root = { setAttribute(name: string, value: string): void };

export const parseTheme = (v: unknown): Theme | null => (v === 'light' || v === 'dark' ? v : null);

/** The user's saved choice wins; with none (first visit), follow the OS / browser setting. */
export const resolveTheme = (stored: unknown, systemDark: boolean): Theme => parseTheme(stored) ?? (systemDark ? 'dark' : 'light');

export const otherTheme = (t: Theme): Theme => (t === 'dark' ? 'light' : 'dark');

/** Saved choice, or null if none / unreadable (private mode, blocked storage). */
export function readTheme(storage: Store | undefined): Theme | null {
  try { return parseTheme(storage?.getItem(THEME_KEY)); } catch { return null; }
}

/** Show `t` now and remember it for the next visit. Storage failing only means it isn't remembered. */
export function applyTheme(t: Theme, root: Root, storage?: Store): void {
  root.setAttribute('data-theme', t);
  try { storage?.setItem(THEME_KEY, t); } catch { /* private mode: this visit only */ }
}

/** The rider's pick: a saved light / dark, else 'system'. */
export const readThemePref = (storage: Store | undefined): ThemePref => readTheme(storage) ?? 'system';

/** Apply a pick. 'system' forgets the saved choice and shows what the OS asks for (and follows it from then on). */
export function applyThemePref(pref: ThemePref, root: Root, storage: Store | undefined, systemDark: boolean): void {
  if (pref !== 'system') return applyTheme(pref, root, storage);
  try { storage?.removeItem?.(THEME_KEY); } catch { /* private mode */ }
  root.setAttribute('data-theme', systemDark ? 'dark' : 'light');
}

/** Runs in <head> while the HTML is parsed, before anything is painted: same rule as resolveTheme. */
export const THEME_SCRIPT = `(function(){var s=null;try{s=localStorage.getItem(${JSON.stringify(THEME_KEY)})}catch(e){}`
  + `var t=s==="light"||s==="dark"?s:(window.matchMedia&&matchMedia(${JSON.stringify(SYSTEM_DARK)}).matches?"dark":"light");`
  + `document.documentElement.setAttribute("data-theme",t)})()`;
