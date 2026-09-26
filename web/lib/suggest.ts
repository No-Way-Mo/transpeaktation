// "transPEAKtation suggestions": event-aware drop-off points and departure times shown while searching.
import { meters, mins, type Place, type Route } from './route.ts';

type Venue = {
  venue: string; keys: string[]; title: string; time: string; start?: [number, number]; lat: number; lon: number;
  drop: { label: string; lat: number; lon: number; why: string; badge: string };
  crowd: { from: [number, number]; to: [number, number]; delay: number }; // local time window + worst extra minutes nearby
};

// ponytail: hard-coded event feed from the design, so the UI works before ingest's event source (PredictHQ /
// Ticketmaster, TODO #13) and ml/'s forecasts exist. Replace with an api/ endpoint that reads Mongo `events`.
export const EVENTS: Venue[] = [
  { venue: 'Oracle Park', keys: ['oracle', 'giants', 'ballpark'], title: 'Giants vs. Dodgers', time: '7:15 PM', start: [19, 15], lat: 37.7786, lon: -122.3893,
    drop: { label: 'drop-off at 4th & King', lat: 37.7765, lon: -122.3942, why: 'Skips the King St backup. 5 min walk to the gate.', badge: 'Saves ~8 min' },
    crowd: { from: [17, 45], to: [19, 30], delay: 8 } },
  { venue: 'Chase Center', keys: ['chase', 'warriors', 'mission bay'], title: 'Concert', time: '8:00 PM', start: [20, 0], lat: 37.768, lon: -122.3877,
    drop: { label: 'drop-off at 16th & 3rd St', lat: 37.7665, lon: -122.389, why: 'Avoids the Warriors Way curb queue. 3 min walk.', badge: 'Saves ~6 min' },
    crowd: { from: [18, 30], to: [20, 15], delay: 6 } },
  { venue: 'Ferry Building', keys: ['ferry', 'farmers market', 'embarcadero'], title: 'Farmers market', time: 'until 2:00 PM', lat: 37.7955, lon: -122.3937,
    drop: { label: 'drop-off at Washington & Embarcadero', lat: 37.7962, lon: -122.3972, why: 'Keeps you out of market-day curb traffic. 4 min walk.', badge: 'Saves ~4 min' },
    crowd: { from: [8, 0], to: [14, 0], delay: 4 } },
];

export type Suggestion = {
  glyph: 'pin' | 'clock' | 'arrow'; title: string; sub: string; badge: string;
  dest: Place; note: string; leaveMin?: number; clear?: boolean;
};

const clock = (d: Date) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** Suggestions for the search text: event venues get a better drop-off (+ a "leave at" time when the event
 *  is later today); anything else gets a plain "leave now" for the top place result. */
export function smartSuggestions(q: string, results: Place[], now = new Date()): Suggestion[] {
  const ql = q.trim().toLowerCase();
  if (!ql) return [];
  const ev = EVENTS.find(e => e.venue.toLowerCase().startsWith(ql) || e.keys.some(k => k.startsWith(ql) || ql.includes(k)));
  if (!ev) {
    const top = results[0];
    return top ? [{ glyph: 'arrow', title: `${top.label}, leave now`, sub: 'No events on your way. Traffic looks normal.', badge: 'Clear',
      dest: top, note: 'No events on your way. Traffic looks normal.', clear: true }] : [];
  }
  const out: Suggestion[] = [{
    glyph: 'pin', title: `${ev.venue}, ${ev.drop.label}`, sub: `${ev.title} at ${ev.time}. ${ev.drop.why}`, badge: ev.drop.badge,
    dest: { label: ev.venue, sub: ev.drop.label, lat: ev.drop.lat, lon: ev.drop.lon },
    note: `${ev.title} at ${ev.time}. Routing you to the ${ev.drop.label}. ${ev.drop.why}`,
  }];
  if (ev.start) {
    const start = new Date(now); start.setHours(ev.start[0], ev.start[1], 0, 0);
    const leave = new Date(start.getTime() - 60 * 60000); // ~20 min drive, arrive ~40 min early
    const leaveMin = Math.round((leave.getTime() - now.getTime()) / 60000);
    if (leaveMin >= 0 && leaveMin <= 6 * 60) {
      out.push({ glyph: 'clock', title: `Leave for ${ev.venue} at ${clock(leave)}`, sub: `Arrive before traffic peaks for ${ev.title} (${ev.time}).`,
        badge: 'Beat the peak', dest: { label: ev.venue, sub: '', lat: ev.lat, lon: ev.lon }, leaveMin,
        note: `Leaving at ${clock(leave)} gets you in before traffic peaks for ${ev.title}.` });
    }
  }
  return out;
}

// ---- transPEAKtation route estimate ----------------------------------------------------------------------------
// ponytail: stand-in for ml/'s traffic forecast. Adds each event's crowd delay to a route that passes its venue
// while the crowd is there: full within 200 m of the venue fading to 0 at 700 m, ramping in/out over 30 min around
// the crowd window. Replace with prediction_metrics (Tiger) per road_segment_id once ml/ writes them.

export type Prediction = { dur: number; delay: number; events: string[] }; // seconds; events that added delay

const minuteOfDay = (ms: number) => { const d = new Date(ms); return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60; };
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Route duration once events along it are counted, for a departure at `depart` (epoch ms). */
export function predict(r: Route, depart: number, events: Venue[] = EVENTS): Prediction {
  let delay = 0;
  const hit: string[] = [];
  for (const ev of events) {
    let k = 0, d = Infinity;
    r.coords.forEach((c, i) => { const m = meters(c, [ev.lat, ev.lon]); if (m < d) { d = m; k = i; } });
    const near = clamp01((700 - d) / 500);
    if (!near) continue;
    const m = minuteOfDay(depart + (r.dur * 1000 * k) / Math.max(1, r.coords.length - 1)); // when we pass it
    const [a, b] = [ev.crowd.from, ev.crowd.to].map(([h, mm]) => h * 60 + mm);
    const s = ev.crowd.delay * 60 * near * clamp01(Math.min((m - a + 30) / 30, (b + 30 - m) / 30));
    if (s >= 30) { delay += s; hit.push(`${ev.title} at ${ev.venue}`); }
  }
  return { dur: r.dur + delay, delay, events: hit };
}

export type TransPeak = { best: number; preds: Prediction[]; tag: string; note: string };

/** transPEAKtation's pick: the route with the lowest event-aware time. `departs[i]` = departure for route i. */
export function transPeakPick(routes: Route[], departs: number[]): TransPeak {
  const preds = routes.map((r, i) => predict(r, departs[i]));
  const best = preds.reduce((b, p, i) => (p.dur < preds[b].dur ? i : b), 0);
  const saved = preds[0].dur - preds[best].dur, extra = preds[best].delay;
  if (saved >= 60) return { best, preds, tag: `Saves ~${mins(saved)} min`, note: `Skips ${preds[0].events.join(' and ')} traffic on the fastest route.` };
  if (extra >= 30) return { best, preds, tag: `+${mins(extra)} min events`, note: `Includes ~${mins(extra)} min for ${preds[best].events.join(' and ')}. Leaving earlier or later helps.` };
  return { best, preds, tag: 'Clear', note: 'No events on your way at this time.' };
}
