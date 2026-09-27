import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ESRI_PARK, ESRI_WATER, hexRgb, paintBasemap, paintWater, parkAlpha, waterAlpha, type RGB } from './water.ts';

const hex = (h: string) => hexRgb(h)!;
const alpha = (h: string, w: RGB) => waterAlpha(...hex(h), w);

// Colours sampled from the real Esri Canvas tiles over SF (zooms 11-16).
test('light basemap: ocean, bay and lakes are water; land, parks, blocks and roads are not', () => {
  const w = ESRI_WATER.light;
  for (const c of ['#D0CFD4', '#D1D0D5', '#D1D0D6', '#CFCED3']) assert.ok(alpha(c, w) > 0.7, c);
  assert.ok(alpha('#D1D1D3', w) > 0 && alpha('#D1D1D3', w) < 1); // JPEG-blended pixel beside a label: partly blue
  for (const c of ['#E8E8E8', '#EDEDED', '#F0F0F0', '#E0E1E3', '#E5E5E5', '#E3E8E2', '#E1E3E0', '#FBFDFA', '#FFFFFF', '#D8D8D8', '#CCCCCC', '#D0D0D0'])
    assert.equal(alpha(c, w), 0, c);
});

test('dark basemap: water yes; land, parks and neutral greys no', () => {
  const w = ESRI_WATER.dark;
  for (const c of ['#232227', '#242328', '#252429']) assert.ok(alpha(c, w) > 0.7, c);
  for (const c of ['#4D4D4F', '#48484A', '#494B4A', '#5A5C5B', '#232323', '#2A2A2A']) assert.equal(alpha(c, w), 0, c);
});

test('paintWater: water pixels take the target colour, everything else goes transparent', () => {
  const px = new Uint8ClampedArray([0xD0, 0xCF, 0xD4, 255, 0xE8, 0xE8, 0xE8, 255]);
  paintWater(px, ESRI_WATER.light, hex('#9DD5E5'));
  assert.deepEqual([...px.slice(0, 4)], [0x9D, 0xD5, 0xE5, 255]);
  assert.equal(px[7], 0);
});

test('hexRgb', () => {
  assert.deepEqual(hexRgb(' #9dd5e5 '), [157, 213, 229]);
  assert.equal(hexRgb('blue'), null);
});

test('parks: the flat green-cast fill is park, neutral land / roads / buildings are not', () => {
  assert.ok(parkAlpha(0xE1, 0xE7, 0xE1, 6, 'light') > 0.9);
  assert.ok(parkAlpha(0x48, 0x4B, 0x48, 3, 'dark') > 0.9);
  assert.equal(parkAlpha(0xED, 0xED, 0xED, 0, 'light'), 0);   // land
  assert.equal(parkAlpha(0xE1, 0xE7, 0xE1, 1, 'light'), 0);   // a lone greenish JPEG pixel among grey
  assert.equal(parkAlpha(0x45, 0x45, 0x48, -1.5, 'dark'), 0); // land
  assert.equal(parkAlpha(0x66, 0x66, 0x66, 0, 'dark'), 0);    // road
});

test('paintBasemap: water and park pixels take their colours, the rest goes transparent', () => {
  const w = 16, px = new Uint8ClampedArray(w * w * 4); // rows 0-2 water, 3-11 park, 12-15 land
  for (let i = 0; i < w * w; i++) {
    const row = Math.floor(i / w), c = row < 3 ? ESRI_WATER.light : row < 12 ? ESRI_PARK.light : [0xED, 0xED, 0xED];
    px.set([...c, 255], i * 4);
  }
  paintBasemap(px, w, 'light', hex('#9DD5E5'), hex('#C9E4B4'));
  assert.deepEqual([...px.slice(0, 4)], [0x9D, 0xD5, 0xE5, 255]);
  assert.deepEqual([...px.slice(7 * 64, 7 * 64 + 4)], [0xC9, 0xE4, 0xB4, 255]);
  assert.equal(px[w * w * 4 - 1], 0);
});
