// Blue water on the Esri grey Canvas basemap. Those tiles are raster JPEGs with water as one flat, slightly blue-grey
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

/** Turn a tile's RGBA pixels into a water-only layer: `to` where it's water, transparent everywhere else. */
export function paintWater(px: Uint8ClampedArray, water: RGB, to: RGB): void {
  for (let i = 0; i < px.length; i += 4) {
    const a = waterAlpha(px[i], px[i + 1], px[i + 2], water);
    px[i] = to[0]; px[i + 1] = to[1]; px[i + 2] = to[2]; px[i + 3] = Math.round(a * 255);
  }
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

/** A w×w tile's water and parks in their theme colours, transparent everywhere else (roads, labels, buildings). */
export function paintBasemap(px: Uint8ClampedArray, w: number, t: 'light' | 'dark', water: RGB, park: RGB): void {
  const n = px.length / 4, cast = new Float32Array(n), box = new Float32Array(n), K = 2;
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
    const to = wa > 0 ? water : park;
    px[o] = to[0]; px[o + 1] = to[1]; px[o + 2] = to[2]; px[o + 3] = Math.round(Math.max(wa, pa) * 255);
  }
}
