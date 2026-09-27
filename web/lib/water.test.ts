import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ESRI_PARK, ESRI_WATER, hexRgb, majorRoads, paintBasemap, parkAlpha, tone, toneLut, waterAlpha, type RGB } from './water.ts';

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

test('paintBasemap: water and park pixels take their colours, the rest is tone-mapped and opaque', () => {
  const w = 16, px = new Uint8ClampedArray(w * w * 4); // rows 0-2 water, 3-11 park, 12-15 land
  for (let i = 0; i < w * w; i++) {
    const row = Math.floor(i / w), c = row < 3 ? ESRI_WATER.light : row < 12 ? ESRI_PARK.light : [0xEE, 0xEE, 0xEE];
    px.set([...c, 255], i * 4);
  }
  paintBasemap(px, w, 'light', 16, hex('#9DD5E5'), hex('#B9D7A8'));
  assert.deepEqual([...px.slice(0, 4)], [0x9D, 0xD5, 0xE5, 255]);
  assert.deepEqual([...px.slice(7 * 64, 7 * 64 + 4)], [0xB9, 0xD7, 0xA8, 255]);
  assert.deepEqual([...px.slice(w * w * 4 - 4)], [...tone(0xEE, 0xEE, 0xEE, 'light', toneLut('light', 16)), 255]);
});

// Grey bands sampled from the real tiles (lib/water.ts): the curve must keep their order and land near the targets.
const lum = ([r, g, b]: RGB) => (r + g + b) / 3;
const near = (got: RGB, want: string, tol: number) => got.every((c, i) => Math.abs(c - hex(want)[i]) <= tol);

test('tone curves are monotonic, so labels, edges and anti-aliasing keep their order', () => {
  for (const [t, z, road] of [['light', 16, 'minor'], ['dark', 12, 'minor'], ['dark', 13, 'major'], ['dark', 14, 'minor'], ['dark', 16, 'major']] as const) {
    const lut = toneLut(t, z, road), at = (v: number) => lum([lut[v * 3], lut[v * 3 + 1], lut[v * 3 + 2]]);
    for (let v = 1; v < 256; v++) assert.ok(at(v) >= at(v - 1), `${t} z${z} at ${v}`);
    assert.equal(at(0), 0); assert.equal(at(255), 255);
  }
});

test('light: buildings cool grey < land < white roads; dark label text untouched', () => {
  const lut = toneLut('light', 16), t = (h: string) => tone(...hex(h), 'light', lut);
  const bldg = t('#DEE0E2'), land = t('#EEEEEE'), road = t('#FEFEFE'), label = t('#6E6E6E');
  assert.ok(lum(bldg) < lum(land) && lum(land) < lum(road));
  assert.ok(near(bldg, '#D8DBDE', 4), `${bldg}`);
  assert.ok(near(land, '#F0F1EF', 3), `${land}`);
  assert.ok(lum(road) >= 253);
  assert.deepEqual(label, hex('#6E6E6E'));
  assert.ok(bldg[2] > bldg[0]); // keeps its cool cast
});

test('dark: charcoal land < subtle buildings < minor roads < major roads < labels, at every zoom band', () => {
  // [zoom, land, building, road grey] sampled from the real tiles; z12 splits minor / major by brightness alone.
  for (const [z, land, bldg, road] of [[12, '#4E4E50', null, '#5A5A5C'], [13, '#4E4E50', null, '#606062'], [14, '#48484A', '#515153', '#616163'], [16, '#48484A', '#515153', '#676769']] as const) {
    const t = (h: string, c: 'minor' | 'major' = 'minor') => tone(...hex(h), 'dark', toneLut('dark', z, c));
    const l = t(land), mn = t(road), mj = z === 12 ? t('#606062') : t(road, 'major'), label = t('#828284');
    assert.ok(near(l, '#182126', 4), `z${z} land ${l}`);
    if (bldg) { const b = t(bldg); assert.ok(near(b, '#29343A', 4), `z${z} bldg ${b}`); assert.ok(lum(l) < lum(b) && lum(b) < lum(mn)); }
    assert.ok(near(mn, '#48555D', 4), `z${z} minor ${mn}`);
    assert.ok(near(mj, '#75828A', 4), `z${z} major ${mj}`);
    assert.ok(lum(label) > lum(mj) && mn[2] > mn[0]); // labels brightest; roads slate (cool)
  }
});

test('majorRoads: a wide road is major, a narrow street and its crossing are not', () => {
  // 64×64 dark tile at z16: land, a 10 px avenue across (rows 20-29) and a 3 px street down (cols 40-42).
  const w = 64, px = new Uint8ClampedArray(w * w * 4);
  for (let y = 0; y < w; y++) for (let x = 0; x < w; x++) {
    const v = (y >= 20 && y < 30) || (x >= 40 && x < 43) ? 0x67 : 0x48;
    px.set([v, v, v, 255], (y * w + x) * 4);
  }
  const m = majorRoads(px, w, 16)!;
  assert.equal(m[25 * w + 10], 1);  // avenue
  assert.equal(m[50 * w + 41], 0);  // street, well away from the avenue
  assert.equal(m[5 * w + 10], 0);   // land
  assert.equal(majorRoads(px, w, 12), null); // z12: brightness splits them
});
