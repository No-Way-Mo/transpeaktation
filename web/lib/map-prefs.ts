// Map style + which map layers show: one set of choices, kept on this device only. The floating Map layers button
// (all layers on / off in one tap) and Settings → Map & Routing (style, each layer) both read and write this same
// state (lib/use-map-prefs.ts), so they can't disagree.
// Plain TS (no DOM types needed) so `node --test` can run it directly.

export type MapStyle = 'standard' | 'satellite';
/** Only layers the map can really draw get a key here; the rest are listed in LAYERS as unavailable. */
export type MapPrefs = { style: MapStyle; eventPins: boolean; traffic: boolean };
export type LayerKey = 'eventPins' | 'traffic';
export const DEFAULT_MAP_PREFS: MapPrefs = { style: 'standard', eventPins: true, traffic: true };
export const MAP_KEY = 'transpeaktation.map'; // localStorage, next to 'transpeaktation.privacy'

type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void };

/** One row in the Map layers panel. `key` = a working toggle; no key = shown, but it can't be switched on. */
export type Layer = { id: string; label: string; group: 'Event intelligence' | 'Mobility'; detail: string; key?: LayerKey; status?: 'Coming soon' | 'Unavailable' };
export const LAYERS: Layer[] = [
  { id: 'eventActivity', label: 'Event Activity', group: 'Event intelligence', status: 'Coming soon',
    detail: 'A heat map of where events draw crowds. Not built yet.' },
  { id: 'eventPins', label: 'Event Pins', group: 'Event intelligence', key: 'eventPins',
    detail: 'Events in your trip’s time window, with their estimated crowd impact area.' },
  { id: 'traffic', label: 'Traffic', group: 'Mobility', key: 'traffic',
    detail: 'Slowdowns painted on the selected route, when the route service reports them.' },
  { id: 'roadDisruptions', label: 'Road Disruptions', group: 'Mobility', status: 'Unavailable',
    detail: 'Closures aren’t drawn on the map yet. They already count toward route times.' },
];

/** Satellite: Esri World Imagery, the same keyless tile service as the standard basemap. */
export const STYLES: { id: MapStyle; label: string }[] = [
  { id: 'standard', label: 'Standard' },
  { id: 'satellite', label: 'Satellite' },
];

/** Saved choices over the defaults; anything unreadable or of the wrong type falls back to the default. */
export function parseMapPrefs(raw: string | null | undefined): MapPrefs {
  let v: unknown = null;
  try { v = JSON.parse(raw ?? 'null'); } catch { /* corrupt: defaults */ }
  const o = v && typeof v === 'object' ? v as Record<string, unknown> : {};
  const bool = (k: LayerKey) => typeof o[k] === 'boolean' ? o[k] as boolean : DEFAULT_MAP_PREFS[k];
  return { style: o.style === 'satellite' ? 'satellite' : 'standard', eventPins: bool('eventPins'), traffic: bool('traffic') };
}

export function readMapPrefs(storage: Store | undefined): MapPrefs {
  try { return parseMapPrefs(storage?.getItem(MAP_KEY)); } catch { return DEFAULT_MAP_PREFS; }
}

/** Storage failing (private mode) only means the choice lasts this visit. */
export function writeMapPrefs(p: MapPrefs, storage: Store | undefined): void {
  try { storage?.setItem(MAP_KEY, JSON.stringify(p)); } catch { /* this visit only */ }
}

/** Flip a layer by its panel id. Unavailable layers (no key) come back unchanged: they can't be switched on. */
export function toggleLayer(p: MapPrefs, id: string): MapPrefs {
  const key = LAYERS.find(l => l.id === id)?.key;
  return key ? { ...p, [key]: !p[key] } : p;
}

/** The map's layers button: pressed while any layer shows. */
export const overlaysOn = (p: MapPrefs) => p.eventPins || p.traffic;

/** One tap on the layers button: every working layer on, or every one off. The map style is left alone. */
export const setOverlays = (p: MapPrefs, on: boolean): MapPrefs => ({ ...p, eventPins: on, traffic: on });

/** A layer row's switch state: unavailable layers always read as off. */
export const layerOn = (p: MapPrefs, l: Layer) => !!l.key && p[l.key];
