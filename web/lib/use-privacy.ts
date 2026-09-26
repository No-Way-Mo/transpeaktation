'use client';
import { useSyncExternalStore } from 'react';
import { DEFAULT_PRIVACY, PRIVACY_KEY, readPrivacy, writePrivacy, type Privacy } from './privacy.ts';

// One copy in memory (so switches still work when storage is blocked), mirrored to localStorage.
const storage = () => { try { return localStorage; } catch { return undefined; } };
const listeners = new Set<() => void>();
let current: Privacy | null = null;

/** The switches right now; for code outside React (the /plan request). */
export const getPrivacy = (): Privacy => (current ??= readPrivacy(storage()));

export function setPrivacy(p: Privacy) {
  current = p;
  writePrivacy(p, storage());
  listeners.forEach(f => f());
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  // Another tab changed them: follow it.
  const onStorage = (e: StorageEvent) => { if (e.key === PRIVACY_KEY) { current = readPrivacy(storage()); cb(); } };
  addEventListener('storage', onStorage);
  return () => { listeners.delete(cb); removeEventListener('storage', onStorage); };
}

/** Current switches + a setter for one of them. The page only renders in the browser (app/page.tsx). */
export function usePrivacy() {
  const privacy = useSyncExternalStore(subscribe, getPrivacy, () => DEFAULT_PRIVACY);
  return { privacy, set: (k: keyof Privacy, v: boolean) => setPrivacy({ ...getPrivacy(), [k]: v }) };
}
