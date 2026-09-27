// Blue water on the Esri grey Canvas basemap. Those tiles are raster JPEGs with water as one flat, slightly blue-grey
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
