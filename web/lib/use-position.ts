'use client';
import { useEffect, useState } from 'react';
import type { Fix } from './nav-progress.ts';
import { ORIGIN, type Place } from './route.ts';

export const NO_LOCATION = new Error('no device location');

/** Device mode, planning from "Current location": one read of where this device is. Rejects with NO_LOCATION when
 *  there's no GPS, permission is denied or it times out. */
export function deviceLocation(): Promise<Place> {
  return new Promise((ok, fail) => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return fail(NO_LOCATION);
    navigator.geolocation.getCurrentPosition(
      p => ok({ ...ORIGIN, sub: 'This device', lat: p.coords.latitude, lon: p.coords.longitude }),
      () => fail(NO_LOCATION),
      { enableHighAccuracy: true, maximumAge: 30000, timeout: 15000 },
    );
  });
}

/** Live GPS while `on`: one navigator.geolocation watcher, cleared when `on` goes false or the caller unmounts.
 *  A failed reading (timeout, no signal) keeps the last fix; denied permission or no GPS just means no fixes. */
export function usePosition(on: boolean): Fix | null {
  const [fix, setFix] = useState<Fix | null>(null);
  useEffect(() => {
    setFix(null);
    if (!on || typeof navigator === 'undefined' || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(
      p => setFix({ pos: [p.coords.latitude, p.coords.longitude], accuracy: p.coords.accuracy }),
      () => {}, // keep the last fix; nothing here may count as arriving
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [on]);
  return fix;
}
