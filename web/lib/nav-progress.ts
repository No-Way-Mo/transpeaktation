// Live navigation: where a GPS fix puts the rider along the route, and whether they've arrived.
// Plain TS so `node --test` can run it directly.
import type { LocationMode } from './location.ts';
import { meters, type LatLng, type Route } from './route.ts';

/** Within this of the route's end counts as arrived. */
export const ARRIVAL_THRESHOLD_METERS = 40;
/** A fix vaguer than this can't prove arrival (indoors, cold start, wifi-only positioning). */
export const MAX_ARRIVAL_ACCURACY_METERS = 50;
/** Fixes vaguer than this don't move progress either. */
export const MAX_PROGRESS_ACCURACY_METERS = 100;
/** Farther than this (or the fix's accuracy, if larger) from the route line = off route: progress holds. */
export const OFF_ROUTE_METERS = 60;
/** How long "Arrived ✓" stays up before navigation closes itself. */
export const ARRIVED_EXIT_MS = 1500;

/** One reading from navigator.geolocation. */
export type Fix = { pos: LatLng; accuracy: number };
/** Where the rider is on the route: the step they're on, metres to its turn, and what's left of the trip. */
export type NavProgress = { step: number; toNext: number; remDist: number; remDur: number };

/** Nearest point of `line` to p: metres along the line to it, and how far p is from it. Flat-earth, city scale. */
export function projectOnLine(p: LatLng, line: LatLng[]): { along: number; offBy: number; length: number } {
  const k = Math.cos((p[0] * Math.PI) / 180);
  let run = 0, along = 0, offBy = line.length ? meters(p, line[0]) : Infinity;
  for (let j = 1; j < line.length; j++) {
    const a = line[j - 1], b = line[j];
    const [bx, by, px, py] = [(b[1] - a[1]) * k, b[0] - a[0], (p[1] - a[1]) * k, p[0] - a[0]];
    const len2 = bx * bx + by * by, seg = Math.sqrt(len2) * 111_320;
    const t = len2 ? Math.max(0, Math.min(1, (px * bx + py * by) / len2)) : 0;
    const d = Math.hypot(px - t * bx, py - t * by) * 111_320;
    if (d < offBy) { offBy = d; along = run + t * seg; }
    run += seg;
  }
  return { along, offBy, length: run };
}

/** The route's end, where arrival is judged (the provider's arrive point, else the line's last vertex). */
export function routeEnd(r: Route): LatLng | null {
  const last = r.steps[r.steps.length - 1]?.maneuver;
  if (last?.type === 'arrive') return [last.location[1], last.location[0]];
  return r.coords[r.coords.length - 1] ?? null;
}

/** Arrived: an accurate enough fix within ARRIVAL_THRESHOLD_METERS of the route's end. Nothing else counts. */
export function isArrived(fix: Fix, r: Route): boolean {
  const end = routeEnd(r);
  return !!end && fix.accuracy <= MAX_ARRIVAL_ACCURACY_METERS && meters(fix.pos, end) <= ARRIVAL_THRESHOLD_METERS;
}

/** Progress for a fix, or null when the fix can't be trusted (too vague, off route): keep the last progress then.
 *  `scale` stretches the provider's step timings to the picked card's estimate (as the nav bar already does). */
export function navProgress(fix: Fix, r: Route, scale = 1): NavProgress | null {
  if (fix.accuracy > MAX_PROGRESS_ACCURACY_METERS || !r.steps.length || r.coords.length < 2) return null;
  const { along, offBy, length } = projectOnLine(fix.pos, r.coords);
  if (offBy > Math.max(OFF_ROUTE_METERS, fix.accuracy) || !length) return null;
  // Steps and the line are measured differently; map the fraction travelled onto the steps' own distances.
  const total = r.steps.reduce((a, s) => a + s.distance, 0);
  const at = (along / length) * total;
  let step = 0, start = 0;
  while (step < r.steps.length - 1 && start + r.steps[step].distance <= at) start += r.steps[step++].distance;
  const cur = r.steps[step], toNext = Math.max(0, start + cur.distance - at);
  const later = r.steps.slice(step + 1).reduce((a, s) => a + s.duration, 0);
  const remDur = (later + (cur.distance ? cur.duration * (toNext / cur.distance) : 0)) * scale;
  return { step, toNext, remDist: Math.max(0, total - at), remDur };
}

/** The point `m` metres along `line` (clamped to its ends). */
export function pointAlong(line: LatLng[], m: number): LatLng {
  let run = 0;
  for (let j = 1; j < line.length; j++) {
    const seg = meters(line[j - 1], line[j]);
    if (run + seg >= m && seg) {
      const t = Math.max(0, (m - run) / seg), [a, b] = [line[j - 1], line[j]];
      return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    }
    run += seg;
  }
  return line[line.length - 1];
}

/** Demo mode's position source: a simulated fix at step i's turn, on the route line, fed to the same
 *  navProgress / isArrived as real GPS. The last step (arrive) sits exactly on the route's end; any other a metre
 *  past its turn so progress lands on that step. */
export function demoFix(r: Route, i: number): Fix {
  const last = r.steps.length - 1;
  if (i >= last) return { pos: routeEnd(r) ?? pointAlong(r.coords, Infinity), accuracy: 5 };
  const length = projectOnLine(r.coords[0], r.coords).length;
  const total = r.steps.reduce((a, s) => a + s.distance, 0);
  const before = r.steps.slice(0, i).reduce((a, s) => a + s.distance, 0);
  const along = total ? (before / total) * length : 0;
  return { pos: pointAlong(r.coords, Math.min(length, along + (i > 0 ? 1 : 0))), accuracy: 5 };
}

/** The one fix navigation runs on. Demo: the simulated rider at the tapped-to turn. Device: live GPS only, so
 *  `demoStep` (banner taps) can't move the turn, progress, what's left, the map or arrival. */
export function navFix(mode: LocationMode, r: Route, demoStep: number, gps: Fix | null): Fix | null {
  return mode === 'demo' ? demoFix(r, demoStep) : gps;
}
