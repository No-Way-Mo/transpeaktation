import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';

// Serves the standalone demo (../demo) at /about/demo/* so /about can embed it without a copy in public/.
// Not /demo/*: the droplet's Caddy serves a hand-copied (stale) demo there, ahead of Next.
// Only these files: the rest of demo/ (SUMO kit, notes) stays private.
const FILES: Record<string, string> = {
  'index.html': 'text/html; charset=utf-8',
  'replay.js': 'text/javascript; charset=utf-8',
  'baseline.data.js': 'text/javascript; charset=utf-8',
};

// no-cache + ETag: the browser revalidates every load (a 304 when unchanged), so an edited demo is never stale.
export async function GET(req: Request, ctx: RouteContext<'/about/demo/[file]'>) {
  const { file } = await ctx.params;
  const type = FILES[file];
  if (!type) return new Response('Not found', { status: 404 });
  const full = path.join(process.cwd(), '..', 'demo', file);
  const { mtimeMs, size } = await stat(full);
  const etag = `"${size.toString(36)}-${Math.floor(mtimeMs).toString(36)}"`;
  const headers = { 'Content-Type': type, 'Cache-Control': 'no-cache', ETag: etag };
  if (req.headers.get('if-none-match') === etag) return new Response(null, { status: 304, headers });
  return new Response(await readFile(full), { headers });
}
