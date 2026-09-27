'use client';
import { useLayoutEffect, useSyncExternalStore } from 'react';
import { applyThemePref, parseTheme, readTheme, readThemePref, resolveTheme, SYSTEM_DARK, THEME_KEY, type Theme, type ThemePref } from './theme.ts';

// The source of truth is <html data-theme>, set before paint by THEME_SCRIPT (app/layout.tsx); React only reads it.
// The pick (System / Light / Dark / Pride) is the saved key, which the attribute alone can't tell apart (System on a dark OS
// looks like Dark), so picks also ping `picked`.
const root = () => document.documentElement;
const current = (): Theme => parseTheme(root().getAttribute('data-theme')) ?? 'light';
const storage = () => { try { return localStorage; } catch { return undefined; } };
const systemDark = () => matchMedia(SYSTEM_DARK).matches;
const resolved = () => resolveTheme(readTheme(storage()), systemDark());
const picked = new Set<() => void>();
let memPref: ThemePref | null = null; // this visit's pick, for when storage is blocked
const pref = (): ThemePref => { const saved = readThemePref(storage()); return saved === 'system' && memPref ? memPref : saved; };

function subscribe(cb: () => void) {
  // Any change to the attribute (a pick in Settings, the dev-mode re-apply below) re-renders the readers.
  const mo = new MutationObserver(cb);
  mo.observe(root(), { attributes: true, attributeFilter: ['data-theme'] });
  picked.add(cb);
  // System: keep following the OS as it flips. A saved choice is left alone.
  const mq = matchMedia(SYSTEM_DARK);
  const onSystem = () => { if (pref() === 'system') root().setAttribute('data-theme', resolved()); };
  // Another tab picked a theme: follow it.
  const onStorage = (e: StorageEvent) => { if (e.key === THEME_KEY) { memPref = null; root().setAttribute('data-theme', resolved()); cb(); } };
  mq.addEventListener('change', onSystem);
  addEventListener('storage', onStorage);
  return () => { mo.disconnect(); picked.delete(cb); mq.removeEventListener('change', onSystem); removeEventListener('storage', onStorage); };
}

/** Current theme, the rider's pick, and its setter. The page only renders in the browser (app/page.tsx). */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, current, () => 'light' as Theme);
  const choice = useSyncExternalStore(subscribe, pref, () => 'system' as ThemePref);
  // Dev only: Strict Mode's remount resets <html> attributes, dropping the one THEME_SCRIPT set. No-op in production.
  useLayoutEffect(() => {
    const want = memPref && memPref !== 'system' ? memPref : resolved();
    if (root().getAttribute('data-theme') !== want) root().setAttribute('data-theme', want);
  }, []);
  const setPref = (p: ThemePref) => {
    memPref = p;
    applyThemePref(p, root(), storage(), systemDark());
    picked.forEach(f => f());
  };
  return { theme, pref: choice, setPref };
}
