// Runs the simulation from index.html headlessly: node check.mjs
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const SIM = new Function(html.match(/<script id="sim">([\s\S]*?)<\/script>/)[1] + '; return SIM;')();

const W = SIM.run('W'), R = SIM.run('R'), W2 = SIM.run('W');
const round = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'number' ? +v.toFixed(1) : v]));
console.table({ without: round(W.stats), roadready: round(R.stats) });
console.log('corridors W', W.corridors.map(c => `${c.key} ${(c.share * 100).toFixed(0)}%`).join(', '));
console.log('corridors R', R.corridors.map(c => `${c.key} ${(c.share * 100).toFixed(0)}%`).join(', '));
console.log('gridlock', W.hot.names, 'peak vehicles on screen', Math.max(...W.frames.map(f => f.v.length / 4)));

const at = (run, t) => run.frames[Math.round(t / SIM.DT)];
assert.deepEqual(at(W, 22).v, at(W2, 22).v, 'simulation must be deterministic');
assert.deepEqual(at(W, 7.9).v, at(R, 7.9).v, 'both runs must be identical before RoadReady switches on');
assert(R.stats.stopped < W.stats.stopped / 3, 'RoadReady should leave far fewer AVs stopped');
assert(R.stats.speed > W.stats.speed * 1.5, 'RoadReady should keep traffic near the event moving');
assert(R.stats.inZone < W.stats.inZone / 4, 'RoadReady should keep AVs out of the impact zone');
assert(R.stats.arrivedEv > W.stats.arrivedEv * 3, 'RoadReady should drop off far more riders by 9:45 PM');
console.log('ok');
