'use client';
import { useSyncExternalStore } from 'react';
import { DEFAULT_MAP_PREFS, MAP_KEY, readMapPrefs, toggleLayer, writeMapPrefs, type MapPrefs, type MapStyle } from './map-prefs.ts';

// Same pattern as lib/use-privacy.ts: one copy in memory (so choices still work when storage is blocked), mirrored to
// localStorage. The Map layers panel and Settings → Map & Routing both use this hook.
const storage = () => { try { return localStorage; } catch { return undefined; } };
const listeners = new Set<() => void>();
let current: MapPrefs | null = null;

const get = (): MapPrefs => (current ??= readMapPrefs(storage()));

function set(p: MapPrefs) {
  current = p;
  writeMapPrefs(p, storage());
  listeners.forEach(f => f());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  // Another tab changed them: follow it.
  const onStorage = (e: StorageEvent) => { if (e.key === MAP_KEY) { current = readMapPrefs(storage()); cb(); } };
  addEventListener('storage', onStorage);
  return () => { listeners.delete(cb); removeEventListener('storage', onStorage); };
}

export function useMapPrefs() {
  const prefs = useSyncExternalStore(subscribe, get, () => DEFAULT_MAP_PREFS);
  return {
    prefs,
    toggle: (id: string) => set(toggleLayer(get(), id)),
    setStyle: (style: MapStyle) => set({ ...get(), style }),
  };
}
