// Recent searches: the places this rider actually picked, newest first, kept in this browser only (no accounts, never
// sent to api/). Plain TS (no DOM types needed) so `node --test` can run it directly; lib/use-search-history.ts is
// the React side.

import type { Place } from './route.ts';

export const HISTORY_KEY = 'transpeaktation:search-history:v1';
export const HISTORY_MAX = 10;

type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void };

const isPlace = (v: unknown): v is Place => {
  const o = v as Record<string, unknown> | null;
  return !!o && typeof o === 'object' && typeof o.label === 'string' && !!o.label.trim() && typeof o.sub === 'string'
    && Number.isFinite(o.lat) && Number.isFinite(o.lon);
};
/** Only what's needed to plan to it again ("Current location" is never stored: it's resolved when planning). */
const clean = (p: Place): Place => ({ label: p.label, sub: p.sub, lat: p.lat, lon: p.lon });

/** Same place: same name + address, or the same spot (~10 m). */
const same = (a: Place, b: Place) =>
  (a.label.trim().toLowerCase() === b.label.trim().toLowerCase() && a.sub.trim().toLowerCase() === b.sub.trim().toLowerCase())
  || (Math.abs(a.lat - b.lat) < 1e-4 && Math.abs(a.lon - b.lon) < 1e-4);

/** Stored history; anything unreadable is dropped (bad JSON or not a list = empty, bad entries skipped). */
export function parseHistory(raw: string | null | undefined): Place[] {
  let v: unknown = null;
  try { v = JSON.parse(raw ?? 'null'); } catch { /* corrupt: empty */ }
  if (!Array.isArray(v)) return [];
  const out: Place[] = [];
  for (const p of v) if (isPlace(p) && !out.some(q => same(q, p))) out.push(clean(p));
  return out.slice(0, HISTORY_MAX);
}

/** `place` on top; an earlier entry for the same place is replaced (fresh data), not duplicated. */
export function withSearch(history: Place[], place: Place): Place[] {
  if (place.current || !isPlace(place)) return history;
  return [clean(place), ...history.filter(p => !same(p, place))].slice(0, HISTORY_MAX);
}

export function readHistory(storage: Store | undefined): Place[] {
  try { return parseHistory(storage?.getItem(HISTORY_KEY)); } catch { return []; }
}

/** Storage failing (private mode) only means the history lasts this visit. */
export function writeHistory(h: Place[], storage: Store | undefined): void {
  try { h.length ? storage?.setItem(HISTORY_KEY, JSON.stringify(h)) : storage?.removeItem(HISTORY_KEY); } catch { /* this visit only */ }
}
