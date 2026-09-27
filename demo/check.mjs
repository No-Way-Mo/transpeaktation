// Runs the simulation from index.html headlessly: node check.mjs
import { existsSync, readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const SIM = new Function(html.match(/<script id="sim">([\s\S]*?)<\/script>/)[1] + '; return SIM;')();

const W = SIM.run('W'), R = SIM.run('R'), W2 = SIM.run('W');
const round = o => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, typeof v === 'number' ? +v.toFixed(1) : v]));
console.table({ without: round(W.stats), transpeaktation: round(R.stats) });
console.log('corridors W', W.corridors.map(c => `${c.key} ${(c.share * 100).toFixed(0)}%`).join(', '));
console.log('corridors R', R.corridors.map(c => `${c.key} ${(c.share * 100).toFixed(0)}%`).join(', '));
console.log('gridlock', W.hot.names, 'peak vehicles on screen', Math.max(...W.frames.map(f => f.v.length / 4)));

const at = (run, t) => run.frames[Math.round(t / SIM.DT)];
assert.deepEqual(at(W, 22).v, at(W2, 22).v, 'simulation must be deterministic');
assert.deepEqual(at(W, 7.9).v, at(R, 7.9).v, 'both runs must be identical before transPEAKtation switches on');
assert(R.stats.stopped < W.stats.stopped / 3, 'transPEAKtation should leave far fewer AVs stopped');
assert(R.stats.speed > W.stats.speed * 1.5, 'transPEAKtation should keep traffic near the event moving');
assert(R.stats.inZone < W.stats.inZone / 4, 'transPEAKtation should keep AVs out of the impact zone');
assert(R.stats.arrivedEv > W.stats.arrivedEv * 3, 'transPEAKtation should drop off far more riders by 9:45 PM');

// replay.js (index.html act 1 and baseline.html) over baseline.data.js must reproduce SUMO's report.json.
const REPLAY = new Function(readFileSync(new URL('./replay.js', import.meta.url), 'utf8') + '; return REPLAY;')();
const win = {}; new Function('window', readFileSync(new URL('./baseline.data.js', import.meta.url), 'utf8'))(win);
const D = win.BASELINE;
// runs/ is gitignored, so the exported numbers are compared with SUMO's own files only where the run exists.
for (const [name, v] of Object.entries(D.variants)) {
  const report = new URL(`./sumo/runs/${D.run}/report.json`, import.meta.url);
  if (existsSync(report)) {
    const rep = JSON.parse(readFileSync(report)).variants[name];
    assert.deepEqual(v.counts, rep.counts, `${name}: app-user counts must match report.json`);
    for (const k in rep.completed_only_metrics) assert.equal(v.metrics[k].mean, rep.completed_only_metrics[k].mean, `${name}: ${k} must match report.json`);
    console.log(`baseline.data.js ${name} matches`, D.run);
  } else console.log('skip report.json check: run', D.run, 'not present');
  // The page's per-second all-car counts must be SUMO's own summary output, second for second.
  const summary = new URL(`./sumo/runs/${D.replay}/${name}.summary.xml`, import.meta.url);
  if (existsSync(summary)) {
    const tt = v.totals;
    let n = 0;
    for (const m of readFileSync(summary, 'utf8').matchAll(/<step time="(\d+)\.00"[^>]*?running="(\d+)" waiting="(\d+)" ended="\d+" arrived="(\d+)"[^>]*?halting="(\d+)"/g)) {
      const t = +m[1];
      if (t >= D.end) continue;
      assert.deepEqual([tt.running[t], tt.waiting[t], tt.arrived[t], tt.halting[t]], [+m[2], +m[3], +m[4], +m[5]], `${name} summary.xml second ${t}`);
      n++;
    }
    assert.equal(n, D.end, `${name}: every simulated second is in summary.xml`);
    console.log(`baseline.data.js ${name} totals match SUMO summary.xml for all ${n} seconds`);
  } else console.log('skip summary.xml check: replay', D.replay, 'not present');
}
// Act 2 of index.html replays the ML variant; it needs the model labels for its captions.
if (D.variants.ml) {
  assert(D.placeholder || (D.ml_models && D.ml_models.every(m => m.startsWith('ml:'))), 'ml variant needs ml: model labels or the placeholder flag');
  // Only the routes may differ: every app rider has the same id, requested second, start and end in both runs.
  const key = v => v.vehicles.map(([id, req, , , from, to]) => [id, req, from, to].join()).join('|');
  assert.equal(key(D.variants.ml), key(D.variants.baseline), 'ml and baseline must have the same riders, times, starts and ends');
}
const p95 = xs => [...xs].sort((a, b) => a - b)[Math.ceil(0.95 * xs.length) - 1];   // report.json uses nearest rank
for (const [name, v] of Object.entries(D.variants)) {
  const cars = REPLAY.decode(v.vehicles), s = REPLAY.series(cars, D.end), m = v.metrics, c = v.counts;
  const done = cars.filter(x => x.arrived), n = done.length;
  const dur = done.map(x => x.t1 - x.t0), wait = done.map(x => x.halt.reduce((a, h) => a + h, 0));
  assert.equal(cars.length, D.users, `${name}: every user has a row`);
  assert.equal(n, c.completed, `${name}: arrived rows = completed`);
  assert.equal(cars.filter(x => x.t0 === Infinity).length, c.not_departed, `${name}: never-started rows`);
  assert.equal(cars.filter(x => x.t0 < Infinity && !x.arrived).length, c.unfinished, `${name}: unfinished rows`);
  assert.equal(s.arr[D.end], c.completed, `${name}: arrivals match completed count`);
  assert.equal(dur.reduce((a, b) => a + b, 0), Math.round(m.duration.mean * n), `${name}: completed car-seconds = n x mean duration`);
  assert.equal(wait.reduce((a, b) => a + b, 0), Math.round(m.waitingTime.mean * n), `${name}: completed waiting = n x mean waitingTime`);
  assert.equal(done.reduce((a, x) => a + x.t0 - x.req, 0), Math.round(m.departDelay.mean * n), `${name}: departure delays`);
  assert.deepEqual([p95(dur), p95(wait)], [m.duration.p95, m.waitingTime.p95], `${name}: p95 duration and waiting`);
  for (const k of ['running', 'halting', 'waiting', 'arrived']) assert.equal(v.totals[k].length, D.end, `${name}: ${k} per second`);
  assert(v.totals.running.every((r, t) => r >= s.road[t]), `${name}: all-car totals include every app user on the road`);
  // Side panel: each second, the five groups are never negative and add up to all cars; they end where the results table does.
  const all = D.users + (D.crowd ? D.crowd.count : 0), sum = g => Object.values(g).reduce((a, b) => a + b);
  for (let t = 0; t < D.end; t++) {
    const b = REPLAY.allAt(v.totals, t, all);
    assert(sum(b) === all && Object.values(b).every(x => x >= 0), `${name}: panel groups at ${t}`);
    assert(b.arrived >= s.arr[t], `${name}: all cars include tracked arrivals at ${t}`);
  }
  const last = REPLAY.allAt(v.totals, D.end - 1, all), ac = v.all.counts;
  assert.deepEqual([last.arrived, last.moving + last.stopped, last.enter, ac.failed + ac.missing], [ac.completed, ac.unfinished, ac.not_departed, 0],
    `${name}: all-car trip results match SUMO's final per-second totals`);
  console.log(`baseline.html ${name}: ${c.completed} completed, ${c.unfinished} unfinished, ${c.not_departed} never started; match report.json`);
}
console.log('ok');
