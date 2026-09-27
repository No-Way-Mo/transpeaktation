import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ESRI_WATER, hexRgb, paintWater, waterAlpha, type RGB } from './water.ts';

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
