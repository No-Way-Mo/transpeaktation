'use client';
import { useLayoutEffect, useSyncExternalStore } from 'react';
import { applyTheme, otherTheme, readTheme, resolveTheme, SYSTEM_DARK, THEME_KEY, type Theme } from './theme.ts';

// The source of truth is <html data-theme>, set before paint by THEME_SCRIPT (app/layout.tsx); React only reads it.
const root = () => document.documentElement;
const current = (): Theme => (root().getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
const storage = () => { try { return localStorage; } catch { return undefined; } };
const resolved = () => resolveTheme(readTheme(storage()), matchMedia(SYSTEM_DARK).matches);

function subscribe(cb: () => void) {
  // Any change to the attribute (this tab's toggle, the dev-mode re-apply below) re-renders the readers.
  const mo = new MutationObserver(cb);
  mo.observe(root(), { attributes: true, attributeFilter: ['data-theme'] });
  // No saved choice yet: keep following the OS as it flips. A saved choice is left alone.
  const mq = matchMedia(SYSTEM_DARK);
  const onSystem = () => { if (!readTheme(storage())) root().setAttribute('data-theme', resolved()); };
  // Another tab picked a theme: follow it.
  const onStorage = (e: StorageEvent) => { if (e.key === THEME_KEY) root().setAttribute('data-theme', resolved()); };
  mq.addEventListener('change', onSystem);
  addEventListener('storage', onStorage);
  return () => { mo.disconnect(); mq.removeEventListener('change', onSystem); removeEventListener('storage', onStorage); };
}

/** Current theme + setters. The page only renders in the browser (app/page.tsx), so there's no server snapshot to match. */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, current, () => 'light' as Theme);
  // Dev only: Strict Mode's remount resets <html> attributes, dropping the one THEME_SCRIPT set. No-op in production.
  useLayoutEffect(() => { if (root().getAttribute('data-theme') !== resolved()) root().setAttribute('data-theme', resolved()); }, []);
  const setTheme = (t: Theme) => applyTheme(t, root(), storage());
  return { theme, setTheme, toggle: () => setTheme(otherTheme(theme)) };
}
