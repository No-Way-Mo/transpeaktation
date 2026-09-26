// "transPEAKtation suggestions": event-aware drop-off points and departure times shown while searching.
// Events come from api/ /events (Mongo `events` written by ingest/, demo events until then); the route
// estimates themselves come from api/ /plan, which runs the model server-side.
import { ptClock, ptTime, TZ, type EventInfo, type Place } from './route.ts';

export type Suggestion = {
  glyph: 'pin' | 'clock' | 'arrow'; title: string; sub: string; badge: string;
  dest: Place; note: string; leaveMin?: number; clear?: boolean;
};

const clock = (d: Date) => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: TZ });

/** Suggestions for the search text: event venues get a better drop-off (+ a "leave at" time when the event
 *  is later today); anything else gets a plain "leave now" for the top place result. */
export function smartSuggestions(q: string, results: Place[], events: EventInfo[], now = new Date()): Suggestion[] {
  const ql = q.trim().toLowerCase();
  if (!ql) return [];
  const ev = events.find(e => e.venue.toLowerCase().startsWith(ql) || e.keys.some(k => k.startsWith(ql) || ql.includes(k)));
  if (!ev) {
    const top = results[0];
    return top ? [{ glyph: 'arrow', title: `${top.label}, leave now`, sub: 'No events on your way. Traffic looks normal.', badge: 'Clear',
      dest: top, note: 'No events on your way. Traffic looks normal.', clear: true }] : [];
  }
  const out: Suggestion[] = [];
  if (ev.drop) {
    out.push({
      glyph: 'pin', title: `${ev.venue}, ${ev.drop.label}`, sub: `${ev.title} at ${ev.time}. ${ev.drop.why}`, badge: ev.drop.badge,
      dest: { label: ev.venue, sub: ev.drop.label, lat: ev.drop.lat, lon: ev.drop.lon },
      note: `${ev.title} at ${ev.time}. Routing you to the ${ev.drop.label}. ${ev.drop.why}`,
    });
  } else {
    out.push({
      glyph: 'pin', title: ev.venue, sub: `${ev.title} at ${ev.time}. Expect ~${ev.crowd.delay} min of crowd traffic nearby.`,
      badge: 'Event', dest: { label: ev.venue, sub: ev.title, lat: ev.lat, lon: ev.lon },
      note: `${ev.title} at ${ev.time}. transPEAKtation will route around the crowd where it can.`,
    });
  }
  if (ev.start) {
    const [y, mo, d] = ptClock(now.getTime()), start = ptTime(y, mo, d, ev.start[0], ev.start[1]); // SF clock, like the api's
    const leave = new Date(start - 60 * 60000); // ~20 min drive, arrive ~40 min early
    const leaveMin = Math.round((leave.getTime() - now.getTime()) / 60000);
    if (leaveMin >= 0 && leaveMin <= 6 * 60) {
      out.push({ glyph: 'clock', title: `Leave for ${ev.venue} at ${clock(leave)}`, sub: `Arrive before traffic peaks for ${ev.title} (${ev.time}).`,
        badge: 'Beat the peak', dest: { label: ev.venue, sub: '', lat: ev.lat, lon: ev.lon }, leaveMin,
        note: `Leaving at ${clock(leave)} gets you in before traffic peaks for ${ev.title}.` });
    }
  }
  return out;
}
