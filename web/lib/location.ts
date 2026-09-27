// Where "Current location" is. The app's routes, events and closures are San Francisco only, so by default it plans
// and navigates from a fixed SF demo start (demo mode), wherever the device really is. Device mode (Settings → Map &
// Routing → Location mode) uses this device's GPS instead. Plain TS so `node --test` can run it directly.

export type LocationMode = 'demo' | 'device';
export const DEFAULT_LOCATION_MODE: LocationMode = 'demo';

/** The one place the demo start is defined: Union Square, which the SF route/event data is built around. */
export const DEMO_START = { name: 'Union Square', lat: 37.788, lon: -122.4075 } as const;

export const LOCATION_MODES: { id: LocationMode; label: string; sub: string }[] = [
  { id: 'demo', label: 'Demo location', sub: 'San Francisco' },
  { id: 'device', label: 'Device location', sub: 'Use this device’s GPS' },
];
