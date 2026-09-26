// Snap-Map-style progressive disclosure for event pins + an "Event activity" heat layer (experiment, see
// lib/experiment.ts). Pure functions only, so `node --test` covers every rule; app/snapmap-layers.ts draws them.
//
// What the importance score may use (web sees only the /events MapEvent, contracts/map_context.schema.json):
//   1. closure extent  road_closure_ids: DataSF street blocks closed for the event. A real footprint.
//   2. source floor    PredictHQ events are only ingested at rank >= 30 (ingest/pull/feeds.py PHQ_MIN_RANK:
//                      "below ~30 is a neighbourhood-sized event"), so each one is at least neighbourhood-sized.
// Never category ("concert > conference" is not a fact we have), never a guessed attendance. Mongo `events` does hold
// PredictHQ attendance / rank and seeded venue capacity, but /events doesn't send them; exposing them there is the
// way to rank PredictHQ events against each other. Until then they all sit on the same floor.
// The score only decides visibility and a little prominence; it never changes event data.
import { eventInTime, validCoord, type MapEvent, type Span } from './context.ts';

export type Tier = 'major' | 'medium' | 'minor';
export type Importance = { tier: Tier; score: number; basis: 'closure_extent' | 'source_rank_floor' | 'none' };

export const MAJOR_BLOCKS = 6;          // closes >= 6 street blocks: a citywide-scale street event
export const MEDIUM_BLOCKS = 2;
export const RANK_FLOOR_SOURCE = 'predicthq';

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const blocksOf = (e: Pick<MapEvent, 'road_closure_ids'>) =>
  Array.isArray(e.road_closure_ids) ? new Set(e.road_closure_ids.filter(x => typeof x === 'string' && x)).size : 0;

/** Deterministic rank from real fields only. score in [0, 1]: major 0.75-1, medium 0.45-0.7, minor 0.1-0.2. */
export function getEventImportance(e: Pick<MapEvent, 'source' | 'road_closure_ids'>): Importance {
  const blocks = blocksOf(e);
  if (blocks >= MAJOR_BLOCKS) {
    // 6 blocks -> 0.75 ... 60+ blocks -> 1 (log: the 55-block Fleet Week closure outranks a 6-block fair, not 9x)
    return { tier: 'major', score: 0.75 + 0.25 * clamp01(Math.log(blocks / MAJOR_BLOCKS) / Math.log(10)), basis: 'closure_extent' };
  }
  if (blocks >= MEDIUM_BLOCKS) {
    return { tier: 'medium', score: 0.45 + 0.25 * (blocks - MEDIUM_BLOCKS) / (MAJOR_BLOCKS - MEDIUM_BLOCKS), basis: 'closure_extent' };
  }
  if (e.source === RANK_FLOOR_SOURCE) return { tier: 'medium', score: 0.45, basis: 'source_rank_floor' };
  if (blocks === 1) return { tier: 'minor', score: 0.2, basis: 'closure_extent' };
  return { tier: 'minor', score: 0.1, basis: 'none' };
}

// ---- zoom -------------------------------------------------------------------------------------------------------
// Leaflet zooms for SF: 9 = Bay Area, 11 = the whole city, 12.5 = a few neighbourhoods, 14+ = streets.
export const ZOOMS = { regional: 9, city: 11, neighborhood: 12.5, street: 14 } as const;
export const PIN_FADE = 1;              // zoom levels over which a pin fades in, ending at its min zoom
export const ALWAYS = 0;                // min zoom for pins that are never hidden

/** Zoom at which the pin is fully shown. Higher score within a tier = shows a little earlier, so a tier arrives as
 *  a gradual trickle, not all at once. Major: always. Route-relevant or selected events are passed ALWAYS by the caller. */
export function getMinZoomForEvent(imp: Importance): number {
  if (imp.tier === 'major') return ALWAYS;
  if (imp.tier === 'medium') return ZOOMS.neighborhood - 0.5 * clamp01((imp.score - 0.45) / 0.25);
  return ZOOMS.street - 0.5 * clamp01((imp.score - 0.1) / 0.1);
}

/** 0 (hidden) ... 1 (shown): continuous in zoom, so pins fade in over PIN_FADE levels instead of popping. */
export const pinOpacity = (minZoom: number, zoom: number): number =>
  minZoom <= ALWAYS ? 1 : clamp01(zoom - (minZoom - PIN_FADE));

/** Slight extra size for important pins when zoomed out; back to normal size at street zoom. */
export const pinScale = (imp: Importance, zoom: number): number =>
  1 + 0.3 * imp.score * clamp01((13 - zoom) / 2);

export type PinState = { id: string; opacity: number; scale: number; imp: Importance };
/** Every pin's visibility at `zoom`. `pinned` = ids that stay visible at any zoom (selected, on the selected route). */
export function pinStates(events: MapEvent[], zoom: number, pinned: ReadonlySet<string> = new Set()): PinState[] {
  return events.map(e => {
    const imp = getEventImportance(e);
    const min = pinned.has(e.id) ? ALWAYS : getMinZoomForEvent(imp);
    return { id: e.id, opacity: pinOpacity(min, zoom), scale: pinScale(imp, zoom), imp };
  });
}

// ---- event activity heat ----------------------------------------------------------------------------------------
// Where events are happening in the selected time window, NOT traffic. Weight = 1 per event (a count), plus a little
// for a real closure footprint (a 55-block closure covers more street than a 1-block party). Derived, not measured.
export type HeatPoint = { lat: number; lon: number; w: number };
export const heatWeight = (e: Pick<MapEvent, 'road_closure_ids'>): number => 1 + Math.min(2, 0.25 * Math.max(0, blocksOf(e) - 1));

/** Heat points for the events relevant in the trip window: re-checks time, so a stale or wider fetch (e.g. the
 *  previous "Leave at" while the new one loads) can never paint off-time events. */
export function activityPoints(events: MapEvent[], trip: Span): HeatPoint[] {
  return events.filter(e => validCoord(e.lat, e.lon) && eventInTime(e, trip)).map(e => ({ lat: e.lat, lon: e.lon, w: heatWeight(e) }));
}

/** Heat layer opacity: full at city zoom and out, fading through neighbourhood zoom, gone at street zoom. With a
 *  route on screen it steps back (the route leads) and is gone from street zoom. */
export function heatOpacity(zoom: number, routeActive: boolean): number {
  const base = clamp01(1 - (zoom - ZOOMS.city) / (15 - ZOOMS.city));
  if (!routeActive) return base;
  return zoom >= ZOOMS.street ? 0 : base * 0.35;
}
export const LEGEND_MIN_OPACITY = 0.08; // legend fades out with the layer
export const legendOpacity = (zoom: number, routeActive: boolean): number => {
  const o = heatOpacity(zoom, routeActive);
  return o < LEGEND_MIN_OPACITY ? 0 : Math.min(1, o * 1.5);
};

/** Heat kernel radius in screen px: small blobs merge into a regional glow when zoomed out, and split into
 *  neighbourhoods as you zoom in (same px = less ground). */
export const heatRadius = (zoom: number): number => Math.round(Math.min(46, Math.max(16, 16 + (zoom - ZOOMS.regional) * 6)));
/** Weight that saturates the colour ramp. More events share each pixel when zoomed out, so the ceiling rises there;
 *  the colour is relative activity, not a count. */
export const heatCeiling = (zoom: number): number => 4 * Math.max(1, 2 ** ((12 - zoom) * 0.5));

// Our palette, low -> very high. Deliberately no red / amber / green: this is event activity, not traffic.
export const ACTIVITY_PALETTE = ['#d9ed92', '#b5e48c', '#99d98c', '#76c893', '#52b69a', '#34a0a4', '#168aad', '#1a759f', '#1e6091', '#184e77'] as const;

/** Where the camera goes when a pin is clicked: close enough that the event's neighbours show, never out. */
export const focusZoom = (current: number): number => Math.max(current, 14.5);
