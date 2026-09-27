import { readFile } from 'node:fs/promises';
import path from 'node:path';

// Serves the standalone demo (../demo) so /about can embed it without a copy in public/.
// Only these files: the rest of demo/ (SUMO kit, notes) stays private.
const FILES: Record<string, string> = {
  'index.html': 'text/html; charset=utf-8',
  'replay.js': 'text/javascript; charset=utf-8',
  'baseline.data.js': 'text/javascript; charset=utf-8',
};

export async function GET(_req: Request, ctx: RouteContext<'/demo/[file]'>) {
  const { file } = await ctx.params;
  const type = FILES[file];
  if (!type) return new Response('Not found', { status: 404 });
  const body = await readFile(path.join(process.cwd(), '..', 'demo', file));
  return new Response(body, { headers: { 'Content-Type': type, 'Cache-Control': 'public, max-age=3600' } });
}
