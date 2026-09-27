// Our palette on the Esri grey Canvas basemap (app/map-view.tsx draws every tile through paintBasemap). Water first. Those tiles are raster JPEGs with water as one flat, slightly blue-grey
// fill (the same at every zoom we fetch, 11-16), so water is picked out of the provider's own pixels and repainted in
// --map-water. Nothing is drawn by hand: no polygons, no coastline. Plain TS so `node --test` can run it.

import type { Base } from './theme.ts';

export type RGB = [number, number, number];

/** Esri's water fill per theme: Canvas World_Light_Gray_Base / World_Dark_Gray_Base. */
export const ESRI_WATER: Record<Base, RGB> = { light: [0xD0, 0xCF, 0xD4], dark: [0x23, 0x22, 0x27] };

const ramp = (v: number, lo: number, hi: number) => (v <= lo ? 0 : v >= hi ? 1 : (v - lo) / (hi - lo));

/** 0-1: how surely a pixel is water. Close to the water fill (JPEG noise is ±3) AND carrying its faint blue cast, so
 *  neutral greys of the same brightness (road casings, blocks, buildings) stay untouched; mixed edge pixels fade. */
export function waterAlpha(r: number, g: number, b: number, [wr, wg, wb]: RGB): number {
  const d = Math.max(Math.abs(r - wr), Math.abs(g - wg), Math.abs(b - wb));
  return (1 - ramp(d, 4, 12)) * ramp(b - (r + g) / 2, 1.5, 3.5);
}

/** "#9DD5E5" → [157, 213, 229]; null if it isn't a 6-digit hex colour. */
export function hexRgb(hex: string): RGB | null {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : null;
}

// Parks get the same treatment: the Canvas tiles paint green space as one flat grey with a faint green cast (+6 light,
// +3 dark). That cast is barely above JPEG noise in dark mode, so it's averaged over a 5×5 box before deciding.
/** Esri's park fill per theme, same two basemaps. */
export const ESRI_PARK: Record<'light' | 'dark', RGB> = { light: [0xE1, 0xE7, 0xE1], dark: [0x48, 0x4B, 0x48] };
const PARK_CAST: Record<'light' | 'dark', [number, number]> = { light: [2, 4], dark: [1.2, 2.4] };

/** 0-1: how surely a pixel is park, given its colour and its neighbourhood's average green cast. */
export function parkAlpha(r: number, g: number, b: number, cast: number, t: 'light' | 'dark'): number {
  const [pr, pg, pb] = ESRI_PARK[t], [lo, hi] = PARK_CAST[t];
  const d = Math.max(Math.abs(r - pr), Math.abs(g - pg), Math.abs(b - pb));
  return (1 - ramp(d, 4, 12)) * ramp(cast, lo, hi);
}

// Everything else is tone-mapped, not classified. The Canvas tiles draw each feature as its own flat grey band, in
// the same order at every zoom we fetch (measured on SF tiles, z11-16):
//   light: labels < buildings ~224 < land ~232-239 < roads ~254
//   dark:  land ~72-78 < buildings ~81 (z14+) < roads ~95-103 < labels ~120-130
// So one monotonic curve per theme moves each band to its colour: order (and so every label, edge and anti-aliased
// pixel) is kept, no pixel is ever guessed at. Light maps brightness to brightness; dark maps it straight to the dark
// map palette (DARK_MAP), so its bands land on exact colours. Dark land shifts at z14 and roads brighten at z15, so dark
// has a curve per zoom band.
// Road class isn't in the pixels' colour (majors and minors are the same grey), only in their width. At z12 minor
// streets are thin enough that their anti-aliasing reads dimmer, so brightness splits them. From z13 dark measures
// width (majorRoads) and lerps between the curve with roads in the minor colour and the one with them in the major.
type Curve = [number, number][];
type ColorCurve = [number, RGB][];
const LIGHT_CURVE: Curve = [[0, 0], [200, 200], [220, 212], [226, 219], [232, 236], [242, 241], [250, 251], [255, 255]];
/** Dark map palette: charcoal land, subtle buildings, dim minor roads, brighter majors, muted slate labels. */
export const DARK_MAP = {
  land: [0x18, 0x21, 0x26], building: [0x29, 0x34, 0x3A], minor: [0x48, 0x55, 0x5D], major: [0x75, 0x82, 0x8A],
  label: [0xA2, 0xAF, 0xB7],
} satisfies Record<string, RGB>;
const { land, building, minor, major, label } = DARK_MAP;
const BLACK: RGB = [0, 0, 0], WHITE: RGB = [255, 255, 255];
type RoadClass = 'minor' | 'major';
/** Per zoom band: the dark curve with its roads in `road`'s colour, the tiles' road grey (`lo`: darkest pixel
 *  counted as road for width), the half-width (px) above which a road is major (0 = split by brightness) and how far
 *  (px) a major road's colour carries along it past where its width wobbles below that (JPEG noise). */
const DARK_BANDS: { maxZoom: number; lo: number; half: number; bridge: number; curve(road: RGB): ColorCurve }[] = [
  { maxZoom: 12, lo: 0, half: 0, bridge: 0, curve: () => [[0, BLACK], [66, land], [82, land], [88, minor], [91, minor], [95, major], [130, label], [255, WHITE]] },
  // half: between the measured half-widths (SF tiles) of minor streets and majors: z13 1 / 1.5-2, z14 1-1.5 / 2+,
  // z15 1-1.5 / 2+, z16 1.5 / 3-3.5.
  { maxZoom: 13, lo: 85, half: 1.2, bridge: 2, curve: road => [[0, BLACK], [66, land], [82, land], [96, road], [130, label], [255, WHITE]] },
  { maxZoom: 14, lo: 87, half: 1.7, bridge: 4, curve: road => [[0, BLACK], [62, land], [76, land], [81, building], [85, building], [97, road], [130, label], [255, WHITE]] },
  { maxZoom: 15, lo: 92, half: 1.7, bridge: 0, curve: road => [[0, BLACK], [62, land], [76, land], [81, building], [86, building], [103, road], [130, label], [255, WHITE]] },
  { maxZoom: 99, lo: 92, half: 2.4, bridge: 0, curve: road => [[0, BLACK], [62, land], [76, land], [81, building], [86, building], [103, road], [130, label], [255, WHITE]] },
];
const MIN_RUN = 10; // px of major-road centre line; shorter = a crossing or a label blob
const band = (z: number) => DARK_BANDS.findIndex(b => z <= b.maxZoom);
const gray = (c: Curve): ColorCurve => c.map(([x, y]) => [x, [y, y, y]]);
/** The theme's curve at zoom z; dark with its roads in the minor (default) or major colour. */
export const toneCurve = (t: 'light' | 'dark', z: number, road: RoadClass = 'minor'): ColorCurve =>
  t === 'light' ? gray(LIGHT_CURVE) : DARK_BANDS[band(z)].curve(road === 'major' ? major : minor);

const luts = new Map<string, Uint8ClampedArray>();
/** 256 × RGB lookup of the theme's curve at zoom z (piecewise linear between its anchors): entry v is at [3v, 3v+3). */
export function toneLut(t: 'light' | 'dark', z: number, road: RoadClass = 'minor'): Uint8ClampedArray {
  const key = t === 'light' ? t : `${t}${band(z)}${road}`;
  let lut = luts.get(key);
  if (!lut) {
    const curve = toneCurve(t, z, road);
    lut = new Uint8ClampedArray(256 * 3);
    for (let v = 0, j = 0; v < 256; v++) {
      while (curve[j + 1][0] < v) j++;
      const [x0, c0] = curve[j], [x1, c1] = curve[j + 1], f = (v - x0) / (x1 - x0);
      for (let c = 0; c < 3; c++) lut[v * 3 + c] = Math.round(c0[c] + (c1[c] - c0[c]) * f);
    }
    luts.set(key, lut);
  }
  return lut;
}

/** One pixel through the theme's curve, plus (a little of) the tiles' own faint cast so anti-aliased edges stay
 *  smooth. Light keeps more of it, so buildings stay cool grey and land neutral. */
export function tone(r: number, g: number, b: number, t: 'light' | 'dark', lut: Uint8ClampedArray): RGB {
  const l = (r + g + b) / 3, i = Math.round(l) * 3, k = t === 'light' ? 1.5 : 1;
  return [lut[i] + (r - l) * k, lut[i + 1] + (g - l) * k, lut[i + 2] + (b - l) * k].map(c => Math.round(Math.min(255, Math.max(0, c)))) as RGB;
}

/** Two-pass chamfer distance (px, 1 / √2 steps) from every pixel to the nearest one where `seed` is 0. Off-tile
 *  counts as far, so a road running off the edge keeps its width. */
function distance(seed: Uint8Array, w: number): Float32Array {
  const d = new Float32Array(w * w), D = Math.SQRT2, INF = 1e6;
  for (let i = 0; i < w * w; i++) d[i] = seed[i] ? INF : 0;
  const at = (x: number, y: number) => (x < 0 || y < 0 || x >= w || y >= w ? INF : d[y * w + x]);
  for (let y = 0; y < w; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (d[i]) d[i] = Math.min(d[i], at(x - 1, y) + 1, at(x, y - 1) + 1, at(x - 1, y - 1) + D, at(x + 1, y - 1) + D);
  }
  for (let y = w - 1; y >= 0; y--) for (let x = w - 1; x >= 0; x--) {
    const i = y * w + x;
    if (d[i]) d[i] = Math.min(d[i], at(x + 1, y) + 1, at(x, y + 1) + 1, at(x + 1, y + 1) + D, at(x - 1, y + 1) + D);
  }
  return d;
}

/** 0-1 per pixel: how surely it's on a major road (dark tiles, zoom z), by width. A morphological opening: pixels
 *  deeper than the band's half-width inside the road grey are major-road centres, and everything within that reach
 *  of a centre is major, so narrow streets (and their crossings, and label strokes) never are. null at zooms where
 *  brightness alone splits the classes. */
export function majorRoads(px: Uint8ClampedArray, w: number, z: number): Float32Array | null {
  const { lo, half, bridge } = DARK_BANDS[band(z)];
  if (!half) return null;
  const n = w * w, road = new Uint8Array(n);
  for (let i = 0; i < n; i++) road[i] = px[i * 4] + px[i * 4 + 1] + px[i * 4 + 2] >= lo * 3 ? 1 : 0;
  const depth = distance(road, w), notCentre = new Uint8Array(n);
  for (let i = 0; i < n; i++) notCentre[i] = depth[i] > half ? 0 : 1;
  // A crossing of two streets is ~1.4× deeper than either, but only as a blob: drop centres that don't run along a road.
  const seen = new Uint8Array(n), run: number[] = [], stack: number[] = [];
  for (let s = 0; s < n; s++) {
    if (notCentre[s] || seen[s]) continue;
    run.length = 0; stack.push(s); seen[s] = 1;
    while (stack.length) {
      const i = stack.pop()!, x = i % w, y = (i - x) / w;
      run.push(i);
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const xx = x + dx, yy = y + dy, j = yy * w + xx;
        if (xx >= 0 && yy >= 0 && xx < w && yy < w && !notCentre[j] && !seen[j]) { seen[j] = 1; stack.push(j); }
      }
    }
    if (run.length < MIN_RUN) for (const i of run) notCentre[i] = 1;
  }
  const reach = distance(notCentre, w), out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.min(1, Math.max(0, half + 1.5 + bridge - reach[i]));
  return out;
}

/** A w×w tile of zoom z repainted in our palette: every pixel tone-mapped (tone; dark roads by class, majorRoads),
 *  then water and parks laid over in their theme colours, edges blended by how surely they are water / park.
 *  Opaque: this is the whole basemap. */
export function paintBasemap(px: Uint8ClampedArray, w: number, t: 'light' | 'dark', z: number, water: RGB, park: RGB): void {
  const n = px.length / 4, cast = new Float32Array(n), box = new Float32Array(n), K = 2, lut = toneLut(t, z);
  const majors = t === 'dark' ? majorRoads(px, w, z) : null, majorLut = majors && toneLut(t, z, 'major');
  for (let i = 0; i < n; i++) cast[i] = px[i * 4 + 1] - (px[i * 4] + px[i * 4 + 2]) / 2;
  // separable box blur, edges clamped
  const pass = (src: Float32Array, dst: Float32Array, dx: number, dy: number) => {
    for (let y = 0; y < w; y++) for (let x = 0; x < w; x++) {
      let s = 0;
      for (let k = -K; k <= K; k++) {
        const xx = Math.min(w - 1, Math.max(0, x + k * dx)), yy = Math.min(w - 1, Math.max(0, y + k * dy));
        s += src[yy * w + xx];
      }
      dst[y * w + x] = s / (2 * K + 1);
    }
  };
  pass(cast, box, 1, 0); pass(box, cast, 0, 1);
  for (let i = 0, o = 0; i < n; i++, o += 4) {
    const r = px[o], g = px[o + 1], b = px[o + 2];
    const wa = waterAlpha(r, g, b, ESRI_WATER[t]), pa = wa > 0 ? 0 : parkAlpha(r, g, b, cast[i], t);
    const a = Math.max(wa, pa), to = wa > 0 ? water : park, m = majors ? majors[i] : 0;
    let base = tone(r, g, b, t, lut);
    if (m > 0) { const hi = tone(r, g, b, t, majorLut!); base = base.map((c, k) => c + (hi[k] - c) * m) as RGB; }
    for (let c = 0; c < 3; c++) px[o + c] = Math.round(base[c] + (to[c] - base[c]) * a);
    px[o + 3] = 255;
  }
}
