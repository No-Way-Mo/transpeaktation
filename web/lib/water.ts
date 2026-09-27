// Our palette on the Esri grey Canvas basemap (app/map-view.tsx draws every tile through paintBasemap). Water first. Those tiles are raster JPEGs with water as one flat, slightly blue-grey
// fill (the same at every zoom we fetch, 11-16), so water is picked out of the provider's own pixels and repainted in
// --map-water. Nothing is drawn by hand: no polygons, no coastline. Plain TS so `node --test` can run it.

export type RGB = [number, number, number];

/** Esri's water fill per theme: Canvas World_Light_Gray_Base / World_Dark_Gray_Base. */
export const ESRI_WATER: Record<'light' | 'dark', RGB> = { light: [0xD0, 0xCF, 0xD4], dark: [0x23, 0x22, 0x27] };

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
// So one monotonic brightness curve per theme moves each band to its colour: order (and so every label, edge and
// anti-aliased pixel) is kept, no pixel is ever guessed at. Dark land shifts at z14 and roads brighten at z15, so dark
// has a curve per zoom band. Road class isn't in the pixels (light majors and minors are the same white); the tiles'
// own widths carry it, and thin roads' anti-aliasing reads dimmer in dark.
type Curve = [number, number][];
const LIGHT_CURVE: Curve = [[0, 0], [200, 200], [220, 212], [226, 219], [232, 236], [242, 241], [250, 251], [255, 255]];
const DARK_CURVES: [maxZoom: number, Curve][] = [
  [13, [[0, 0], [66, 28], [78, 34], [84, 48], [95, 112], [100, 126], [130, 185], [255, 255]]],
  [14, [[0, 0], [62, 28], [72, 34], [81, 55], [86, 68], [95, 118], [100, 130], [130, 185], [255, 255]]],
  [99, [[0, 0], [62, 28], [72, 34], [81, 55], [88, 84], [103, 126], [108, 142], [130, 185], [255, 255]]],
];
export const toneCurve = (t: 'light' | 'dark', z: number): Curve =>
  t === 'light' ? LIGHT_CURVE : DARK_CURVES.find(([max]) => z <= max)![1];

const luts = new Map<string, Uint8ClampedArray>();
/** 256-entry lookup of a curve (piecewise linear between its anchors). */
export function toneLut(t: 'light' | 'dark', z: number): Uint8ClampedArray {
  const curve = toneCurve(t, z), key = `${t}${curve === LIGHT_CURVE ? '' : DARK_CURVES.findIndex(([, c]) => c === curve)}`;
  let lut = luts.get(key);
  if (!lut) {
    lut = new Uint8ClampedArray(256);
    for (let v = 0, j = 0; v < 256; v++) {
      while (curve[j + 1][0] < v) j++;
      const [x0, y0] = curve[j], [x1, y1] = curve[j + 1];
      lut[v] = Math.round(y0 + (y1 - y0) * (v - x0) / (x1 - x0));
    }
    luts.set(key, lut);
  }
  return lut;
}

/** One pixel through the theme's curve. Light keeps (a little more of) the tiles' own faint cast, so buildings stay
 *  cool grey and land neutral; dark adds a slate cast that grows with brightness (charcoal land, slate roads). */
export function tone(r: number, g: number, b: number, t: 'light' | 'dark', lut: Uint8ClampedArray): RGB {
  const l = (r + g + b) / 3, v = lut[Math.round(l)];
  if (t === 'light') return [v + (r - l) * 1.5, v + (g - l) * 1.5, v + (b - l) * 1.5].map(c => Math.round(Math.min(255, Math.max(0, c)))) as RGB;
  const k = Math.min(9, 1 + 0.06 * v);
  return [v - k + (r - l), v + (g - l), v + k + (b - l)].map(c => Math.round(Math.min(255, Math.max(0, c)))) as RGB;
}

/** A w×w tile of zoom z repainted in our palette: every pixel tone-mapped (tone), then water and parks laid over in
 *  their theme colours, edges blended by how surely they are water / park. Opaque: this is the whole basemap. */
export function paintBasemap(px: Uint8ClampedArray, w: number, t: 'light' | 'dark', z: number, water: RGB, park: RGB): void {
  const n = px.length / 4, cast = new Float32Array(n), box = new Float32Array(n), K = 2, lut = toneLut(t, z);
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
    const a = Math.max(wa, pa), to = wa > 0 ? water : park, base = tone(r, g, b, t, lut);
    for (let c = 0; c < 3; c++) px[o + c] = Math.round(base[c] + (to[c] - base[c]) * a);
    px[o + 3] = 255;
  }
}
