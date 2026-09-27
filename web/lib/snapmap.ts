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
// Every threshold is RELATIVE to the zoom at which all of San Francisco fits the map (`sfZoom`, measured from the live
// viewport by snapmap-layers.ts). A desktop map frames SF at ~12.4, a phone at ~11.2; absolute zooms would put the
// "whole city" view in a different tier on each. rel = zoom - sfZoom:
//   rel <= -1.5  region (Bay Area)      heat, exceptional events only
//   rel ~ 0      whole city             heat dominates, major events (+ a trickle of the biggest medium ones)
//   rel 0.75-1.5 neighbourhood          heat fading, medium events arrive
//   rel 1.75-2.5 street                 heat gone, every relevant event
export const SF_BOUNDS: [[number, number], [number, number]] = [[37.705, -122.515], [37.835, -122.355]];
export const REL = { city: 0, neighborhood: 1.5, street: 2.5 } as const;
export const PIN_FADE = 0.75;            // zoom levels over which a pin fades in, ending at its min zoom
export const ALWAYS = -99;               // min rel zoom for pins that are never hidden

export const relZoom = (zoom: number, sfZoom: number): number => zoom - sfZoom;

/** Relative zoom at which the pin is fully shown. Higher score within a tier = a little earlier, so a tier arrives
 *  as a trickle. Major: always. Route-relevant or selected events are passed ALWAYS by the caller. */
export function getMinZoomForEvent(imp: Importance): number {
  if (imp.tier === 'major') return ALWAYS;
  if (imp.tier === 'medium') return REL.neighborhood - 0.5 * clamp01((imp.score - 0.45) / 0.25);
  return REL.street - 0.5 * clamp01((imp.score - 0.1) / 0.1);
}

/** 0 (hidden) ... 1 (shown): continuous in zoom, so pins fade in over PIN_FADE levels instead of popping. */
export const pinOpacity = (minRel: number, rel: number): number =>
  minRel <= ALWAYS ? 1 : clamp01((rel - (minRel - PIN_FADE)) / PIN_FADE);

/** Slight extra size for important pins at city zoom and out; normal size from neighbourhood zoom in. */
export const pinScale = (imp: Importance, rel: number): number =>
  1 + 0.3 * imp.score * clamp01((1 - rel) / 1.5);

export type PinState = { id: string; opacity: number; scale: number; imp: Importance };
/** Every pin's visibility at relative zoom `rel`. `pinned` = ids that stay visible at any zoom (selected, on the
 *  selected route). Independent of the heat: an event can add to the heat without having a pin. */
export function pinStates(events: MapEvent[], rel: number, pinned: ReadonlySet<string> = new Set()): PinState[] {
  return events.map(e => {
    const imp = getEventImportance(e);
    const min = pinned.has(e.id) ? ALWAYS : getMinZoomForEvent(imp);
    return { id: e.id, opacity: pinOpacity(min, rel), scale: pinScale(imp, rel), imp };
  });
}

// ---- event activity heat ----------------------------------------------------------------------------------------
// Where events are happening in the selected time window, NOT traffic. Every time-relevant event contributes, pin or
// no pin. Weight = 1 per event (a count), plus a little for a real closure footprint (a 55-block closure covers more
// street than a 1-block party). Derived, not measured; the colour is RELATIVE activity, never a crowd count.
export type HeatPoint = { lat: number; lon: number; w: number };
export const heatWeight = (e: Pick<MapEvent, 'road_closure_ids'>): number => 1 + Math.min(2, 0.25 * Math.max(0, blocksOf(e) - 1));

/** Heat points for the events relevant in the trip window: re-checks time, so a stale or wider fetch (e.g. the
 *  previous "Leave at" while the new one loads) can never paint off-time events. */
export function activityPoints(events: MapEvent[], trip: Span): HeatPoint[] {
  return events.filter(e => validCoord(e.lat, e.lon) && eventInTime(e, trip)).map(e => ({ lat: e.lat, lon: e.lon, w: heatWeight(e) }));
}

/** Kernel radius on the ground: wide when zoomed out so nearby events merge into one area (downtown + SoMa read as
 *  one region at city zoom), tighter as you zoom in so neighbourhoods separate. */
export const heatRadiusMeters = (rel: number): number => Math.min(3000, Math.max(350, 1100 * 2 ** (-0.6 * rel)));

/** Smooth, compact kernel: 1 at the event, 0 at the radius, no hard ring. */
export const kernel = (x: number): number => (x >= 1 ? 0 : (1 - x * x) ** 2);

const M_PER_DEG_LAT = 111_320;
/** Ground distance in metres (equirectangular; fine inside a city). */
export function metersBetween(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const kx = M_PER_DEG_LAT * Math.cos(((a.lat + b.lat) / 2) * Math.PI / 180);
  return Math.hypot((a.lon - b.lon) * kx, (a.lat - b.lat) * M_PER_DEG_LAT);
}

/** A peak must be at least this many weighted events stacked, so one lone event never reaches the top colour. */
export const MIN_PEAK = 4;
/** The strongest density in the time window (at any event, where peaks sit), floored at MIN_PEAK. Heat values are
 *  divided by this: the busiest cluster reaches the top of the ramp, sparse areas stay near zero. Uses every
 *  time-relevant event, not just the ones on screen, so panning doesn't restretch the colours. */
export function densityPeak(points: HeatPoint[], radiusM: number): number {
  let peak = 0;
  for (const p of points) {
    let d = 0;
    for (const q of points) d += q.w * kernel(metersBetween(p, q) / radiusM);
    if (d > peak) peak = d;
  }
  return Math.max(MIN_PEAK, peak);
}

/** Density / peak -> ramp position. A gentle curve (^0.75) gives moderate clusters (20-40% of the busiest one) the
 *  green-teal middle of the ramp instead of near-invisible mint; order is preserved and the sparse floor still holds. */
export const heatLevel = (densityOverPeak: number): number => clamp01(densityOverPeak) ** 0.75;

/** Colour ramp position t (0..1 of the peak) -> alpha. Below ~6% of the peak: nothing (sparse = normal map); a soft
 *  rise through the pale greens; the centre of a strong hotspot is clearly saturated. */
export const HEAT_FLOOR = 0.06;
export const heatAlpha = (t: number, maxAlpha: number): number => {
  const x = clamp01((t - HEAT_FLOOR) / (0.6 - HEAT_FLOOR));
  return maxAlpha * x * x * (3 - 2 * x); // smoothstep
};

/** Heat layer opacity: full at whole-city zoom and out, fading through neighbourhood zoom, gone at street zoom.
 *  With a route on screen it steps back (the route leads) and is gone from neighbourhood-street zoom. */
export function heatOpacity(rel: number, routeActive: boolean): number {
  const base = clamp01(1 - (rel - 0.25) / (REL.street - 0.25));
  if (!routeActive) return base;
  return rel >= 1.75 ? 0 : base * 0.35;
}
export const LEGEND_MIN_OPACITY = 0.08; // legend fades out with the layer
export const legendOpacity = (rel: number, routeActive: boolean): number => {
  const o = heatOpacity(rel, routeActive);
  return o < LEGEND_MIN_OPACITY ? 0 : Math.min(1, o * 1.5);
};

// Our palette, low -> very high. Deliberately no red / amber: this is event activity, not traffic.
export const ACTIVITY_PALETTE = ['#d9ed92', '#b5e48c', '#99d98c', '#76c893', '#52b69a', '#34a0a4', '#168aad', '#1a759f', '#1e6091', '#184e77'] as const;

/** Where the camera goes when a pin is clicked (relative zoom): close enough that its neighbours show, never out. */
export const focusRel = (rel: number): number => Math.max(rel, 2);
