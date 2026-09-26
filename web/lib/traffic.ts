// Traffic colours for the SELECTED route only: never city-wide, never inferred from events (event impact areas and
// traffic congestion are different things). Plain TS so `node --test` can run it directly.
//
// The metric is congestion_ratio, the one traffic_metrics / GET /traffic store (AGENTS.md "Traffic data
// normalization"): 1 - speed / free_flow_speed, 0 = free flow, 1 = stopped, i.e. the share of free-flow speed lost.
//
// Where the numbers come from today: Mapbox's per-piece `congestion` level on the route itself (Route.congestion,
// one value per coords pair, so it is tied to the exact stretch of line). Each level becomes a ratio with the
// calibration AGENTS.md already defines for mapbox_tiles (low 0.1 / moderate 0.4 / heavy 0.65 / severe 0.85).
// GET /traffic can't colour the line yet: it answers per road_segment_id, and the route only carries an ordered,
// de-duplicated list of segment ids (api/app/segments.py match()), not which coords pairs each id covers.
import type { LatLng, Route } from './route.ts';

export type TrafficLevel = 'very_light' | 'light' | 'moderate' | 'busy' | 'very_busy' | 'severe';

/** Upper bound (exclusive) of each level on congestion_ratio, i.e. the share of free-flow speed lost:
 *  under 15% ≈ free flow · 15-30% light · 30-50% moderate (down to half speed) · 50-70% busy · 70-85% very busy ·
 *  85%+ severe (near stopped, AGENTS.md's "severe" calibration point). Mapbox's four levels land in
 *  very light / moderate / busy / severe; light and very busy need measured speeds. */
export const TRAFFIC_THRESHOLDS: readonly [TrafficLevel, number][] = [
  ['very_light', 0.15], ['light', 0.3], ['moderate', 0.5], ['busy', 0.7], ['very_busy', 0.85], ['severe', Infinity],
];
export const TRAFFIC_LEVELS: readonly TrafficLevel[] = TRAFFIC_THRESHOLDS.map(([l]) => l);

// Conventional traffic colours on purpose (green → red), not the brand palette. Same in light and dark mode.
export const TRAFFIC_COLORS: Record<TrafficLevel, string> = {
  very_light: '#52b69a', light: '#99d98c', moderate: '#f4d35e', busy: '#f6a623', very_busy: '#ef5350', severe: '#a61b1b',
};
export const TRAFFIC_LABELS: Record<TrafficLevel, string> = {
  very_light: 'Very light', light: 'Light', moderate: 'Moderate', busy: 'Busy', very_busy: 'Very busy', severe: 'Severe',
};

/** congestion_ratio → level; null when there is no usable reading (the route keeps its normal colour there). */
export function getTrafficLevel(ratio: number | null | undefined): TrafficLevel | null {
  if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return null;
  const r = Math.min(1, Math.max(0, ratio));
  return TRAFFIC_THRESHOLDS.find(([, max]) => r < max)![0];
}
export const getTrafficColor = (level: TrafficLevel): string => TRAFFIC_COLORS[level];

/** Mapbox congestion level → congestion_ratio (AGENTS.md mapbox_tiles calibration). 'unknown' = no reading. */
export const MAPBOX_CONGESTION_RATIO: Record<string, number> = { low: 0.1, moderate: 0.4, heavy: 0.65, severe: 0.85 };

export type TrafficRun = { level: TrafficLevel; coords: LatLng[] };
/** The route's measured stretches, consecutive pieces of one level merged, for painting over the route line.
 *  Pieces with no reading are left out: the normal route styling shows through there. */
export function routeTraffic(r: Pick<Route, 'coords' | 'congestion'>): TrafficRun[] {
  const out: TrafficRun[] = [];
  let cur: TrafficRun | null = null;
  (r.congestion ?? []).forEach((c, k) => {
    const next = r.coords[k + 1], level = getTrafficLevel(MAPBOX_CONGESTION_RATIO[c]);
    if (!next || !level) { cur = null; return; }
    if (cur?.level === level) cur.coords.push(next);
    else out.push((cur = { level, coords: [r.coords[k], next] }));
  });
  return out;
}

/** Whether the "Traffic on your route" legend has anything true to explain. */
export const hasRouteTraffic = (r: Pick<Route, 'coords' | 'congestion'> | undefined): boolean => !!r && routeTraffic(r).length > 0;
