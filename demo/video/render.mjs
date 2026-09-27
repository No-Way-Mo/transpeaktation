// Renders pitch.html frame by frame to footage/transpeaktation-pitch.mp4 (1920x1080, 30 fps, silent).
// Needs ffmpeg, Google Chrome and footage/ from record.sh. `node render.mjs --from 60 --to 75` renders a slice.
// `node render.mjs --serve` only serves the page for preview: http://127.0.0.1:8123/demo/video/pitch.html
// `node render.mjs --stills 12,75,160` writes footage/still-<t>.jpg frames instead of the video.
// `--short` renders the 2-minute cut (pitch.html?short) to footage/transpeaktation-pitch-short.mp4.
import { spawn, spawnSync } from 'node:child_process';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize, resolve } from 'node:path';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright-core';

const { values: args } = parseArgs({ options: {
  from: { type: 'string', default: '0' }, to: { type: 'string' }, fps: { type: 'string', default: '30' },
  out: { type: 'string' }, serve: { type: 'boolean' }, stills: { type: 'string' }, short: { type: 'boolean' },
} });
const HERE = new URL('.', import.meta.url).pathname, ROOT = resolve(HERE, '../..'), FPS = +args.fps;
const at = p => join(HERE, p);
args.out ??= `footage/transpeaktation-pitch${args.short ? '-short' : ''}.mp4`;

// The simulator recording as a constant-rate, short-GOP mp4: cheap exact seeks in Chrome.
const mov = at('footage/sim.mov'), mp4 = at('footage/sim.mp4');
if (!existsSync(mov)) throw new Error('footage/sim.mov missing: run record.sh first');
if (!existsSync(mp4) || statSync(mp4).mtimeMs < statSync(mov).mtimeMs) {
  console.log('transcoding footage/sim.mov');
  const r = spawnSync('ffmpeg', ['-v', 'error', '-y', '-i', mov, '-vf', 'fps=30,scale=864:-2', '-c:v', 'libx264', '-crf', '16',
    '-g', '15', '-pix_fmt', 'yuv420p', '-an', mp4], { stdio: 'inherit' });
  if (r.status) process.exit(r.status);
}

// Static server over the repo: pitch.html loads ../index.html and ../../web/public/wordmark-light.svg.
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml', '.mp4': 'video/mp4', '.css': 'text/css' };
const server = createServer((req, res) => {
  const path = normalize(join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname)));
  if (!path.startsWith(ROOT) || !existsSync(path) || statSync(path).isDirectory()) { res.writeHead(404).end(); return; }
  const size = statSync(path).size, range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? '');
  const head = { 'content-type': TYPES[extname(path)] ?? 'application/octet-stream', 'accept-ranges': 'bytes' };
  if (range) {   // video seeking needs byte ranges
    const a = range[1] ? +range[1] : 0, b = range[2] ? +range[2] : size - 1;
    res.writeHead(206, { ...head, 'content-range': `bytes ${a}-${b}/${size}`, 'content-length': b - a + 1 });
    createReadStream(path, { start: a, end: b }).pipe(res);
  } else { res.writeHead(200, { ...head, 'content-length': size }); createReadStream(path).pipe(res); }
});
await new Promise(r => server.listen(args.serve ? 8123 : 0, '127.0.0.1', r));
const URL_ = `http://127.0.0.1:${server.address().port}/demo/video/pitch.html`;
if (args.serve) { console.log(`preview: ${URL_}`); await new Promise(() => {}); }

// Virtual clock for the demo iframe (?vt): its timers and CSS transitions/animations only move when pitch.seek
// advances them, by exactly one frame, however long a frame takes to capture.
function virtualTime() {
  if (!new URLSearchParams(location.search).has('vt')) return;
  let now = 0, id = 0;
  const q = new Map();
  window.setTimeout = (fn, ms = 0, ...a) => { q.set(++id, { at: now + (+ms || 0), fn: () => typeof fn === 'function' && fn(...a) }); return id; };
  window.clearTimeout = i => q.delete(i);
  window.__vt = dt => {
    now += dt;
    for (;;) {
      let due = null;
      for (const e of q) if (e[1].at <= now && (!due || e[1].at < due[1].at)) due = e;
      if (!due) break;
      q.delete(due[0]); due[1].fn();
    }
    for (const a of document.getAnimations()) { a.__t ??= 0; a.pause(); a.currentTime = a.__t; a.__t += dt; }
  };
}

const browser = await chromium.launch({ channel: 'chrome', args: ['--autoplay-policy=no-user-gesture-required'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('pageerror', e => console.error('page error:', e.message));
await page.addInitScript(virtualTime);
await page.goto(`${URL_}?render${args.short ? '&short' : ''}`);
await page.waitForFunction(() => window.pitch?.ready, null, { timeout: 60000 });
const { total, beats, app } = await page.evaluate(() => ({ total: window.pitch.total, beats: window.pitch.beats, app: window.pitch.app }));
console.log('scenes', beats, '\napp beats', app);

if (args.stills) {
  for (const t of args.stills.split(',').map(Number)) {
    for (let k = 0; k < 20; k++) await page.evaluate(([t, dt]) => window.pitch.seek(t, dt), [t, k ? 1 / FPS : 0]);   // settle transitions
    await page.screenshot({ path: at(`footage/still-${t}.jpg`), type: 'jpeg', quality: 90 });
  }
  await browser.close(); server.close(); process.exit(0);
}
const from = +args.from, to = Math.min(total, args.to ? +args.to : total), n = Math.round((to - from) * FPS);
const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
  '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', at(args.out)],
  { stdio: ['pipe', 'inherit', 'inherit'] });
const t0 = Date.now();
for (let i = 0; i < n; i++) {
  await page.evaluate(([t, dt]) => window.pitch.seek(t, dt), [from + i / FPS, i ? 1 / FPS : 0]);
  const jpg = await page.screenshot({ type: 'jpeg', quality: 94 });
  if (!ff.stdin.write(jpg)) await new Promise(r => ff.stdin.once('drain', r));
  if (i % 150 === 0 || i === n - 1) {
    const done = (i + 1) / n, eta = (Date.now() - t0) / done * (1 - done) / 1000;
    console.log(`${(from + i / FPS).toFixed(1)} s / ${to.toFixed(1)} s  ${(done * 100).toFixed(0)}%  eta ${Math.round(eta)} s`);
  }
}
ff.stdin.end();
await new Promise(r => ff.on('close', r));
await browser.close(); server.close();
console.log(`wrote ${args.out} (${(to - from).toFixed(1)} s)`);
