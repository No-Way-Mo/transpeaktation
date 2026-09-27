'use client';
import { useSyncExternalStore } from 'react';
import type { Place } from './route.ts';
import { HISTORY_KEY, readHistory, withSearch, writeHistory } from './search-history.ts';

// Same pattern as lib/use-map-prefs.ts: one copy in memory (so it still works when storage is blocked), mirrored to
// localStorage.
const storage = () => { try { return localStorage; } catch { return undefined; } };
const listeners = new Set<() => void>();
const EMPTY: Place[] = [];
let current: Place[] | null = null;

export const getSearchHistory = (): Place[] => (current ??= readHistory(storage()));

function set(h: Place[]) {
  current = h;
  writeHistory(h, storage());
  listeners.forEach(f => f());
}

/** The rider picked `place` (search result, recent, voice): it goes to the top of Recent. */
export const addSearchHistoryItem = (place: Place) => set(withSearch(getSearchHistory(), place));
export const clearSearchHistory = () => set([]);

function subscribe(cb: () => void) {
  listeners.add(cb);
  // Another tab searched: follow it.
  const onStorage = (e: StorageEvent) => { if (e.key === HISTORY_KEY || e.key === null) { current = readHistory(storage()); cb(); } };
  addEventListener('storage', onStorage);
  return () => { listeners.delete(cb); removeEventListener('storage', onStorage); };
}

/** Recent searches, newest first (empty on the server). */
export const useSearchHistory = () => useSyncExternalStore(subscribe, getSearchHistory, () => EMPTY);
