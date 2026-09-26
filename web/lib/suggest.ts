// "transPEAKtation suggestions": event-aware drop-off points and departure times shown while searching.
import type { Place } from './route.ts';

type Venue = {
  venue: string; keys: string[]; title: string; time: string; start?: [number, number]; lat: number; lon: number;
  drop: { label: string; lat: number; lon: number; why: string; badge: string };
};

// ponytail: hard-coded event feed from the design, so the UI works before ingest's event source (PredictHQ /
// Ticketmaster, TODO #13) and ml/'s forecasts exist. Replace with an api/ endpoint that reads Mongo `events`.
export const EVENTS: Venue[] = [
  { venue: 'Oracle Park', keys: ['oracle', 'giants', 'ballpark'], title: 'Giants vs. Dodgers', time: '7:15 PM', start: [19, 15], lat: 37.7786, lon: -122.3893,
    drop: { label: 'drop-off at 4th & King', lat: 37.7765, lon: -122.3942, why: 'Skips the King St backup. 5 min walk to the gate.', badge: 'Saves ~8 min' } },
  { venue: 'Chase Center', keys: ['chase', 'warriors', 'mission bay'], title: 'Concert', time: '8:00 PM', start: [20, 0], lat: 37.768, lon: -122.3877,
    drop: { label: 'drop-off at 16th & 3rd St', lat: 37.7665, lon: -122.389, why: 'Avoids the Warriors Way curb queue. 3 min walk.', badge: 'Saves ~6 min' } },
  { venue: 'Ferry Building', keys: ['ferry', 'farmers market', 'embarcadero'], title: 'Farmers market', time: 'until 2:00 PM', lat: 37.7955, lon: -122.3937,
    drop: { label: 'drop-off at Washington & Embarcadero', lat: 37.7962, lon: -122.3972, why: 'Keeps you out of market-day curb traffic. 4 min walk.', badge: 'Saves ~4 min' } },
];

export type Suggestion = {
  glyph: string; title: string; sub: string; badge: string;
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
    return top ? [{ glyph: '↑', title: `${top.label}, leave now`, sub: 'No events on your way. Traffic looks normal.', badge: 'Clear',
      dest: top, note: 'No events on your way. Traffic looks normal.', clear: true }] : [];
  }
  const out: Suggestion[] = [{
    glyph: '■', title: `${ev.venue}, ${ev.drop.label}`, sub: `${ev.title} at ${ev.time}. ${ev.drop.why}`, badge: ev.drop.badge,
    dest: { label: ev.venue, sub: ev.drop.label, lat: ev.drop.lat, lon: ev.drop.lon },
    note: `${ev.title} at ${ev.time}. Routing you to the ${ev.drop.label}. ${ev.drop.why}`,
  }];
  if (ev.start) {
    const start = new Date(now); start.setHours(ev.start[0], ev.start[1], 0, 0);
    const leave = new Date(start.getTime() - 60 * 60000); // ~20 min drive, arrive ~40 min early
    const leaveMin = Math.round((leave.getTime() - now.getTime()) / 60000);
    if (leaveMin >= 0 && leaveMin <= 6 * 60) {
      out.push({ glyph: '◷', title: `Leave for ${ev.venue} at ${clock(leave)}`, sub: `Arrive before traffic peaks for ${ev.title} (${ev.time}).`,
        badge: 'Beat the peak', dest: { label: ev.venue, sub: '', lat: ev.lat, lon: ev.lon }, leaveMin,
        note: `Leaving at ${clock(leave)} gets you in before traffic peaks for ${ev.title}.` });
    }
  }
  return out;
}
