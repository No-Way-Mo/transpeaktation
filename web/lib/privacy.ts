// The rider's AI & privacy switches (kept on this device only) and the plain-language trace of what touched a trip.
// Plain TS (no DOM types needed) so `node --test` can run it directly; the React hook is lib/use-privacy.ts.
import type { Plan } from './route.ts';

/** Each switch changes behaviour end to end: saveTrips → api/ /plan save=, aiText → ai_text=, voice → mic hidden. */
export type Privacy = { saveTrips: boolean; aiText: boolean; voice: boolean };
export const DEFAULT_PRIVACY: Privacy = { saveTrips: true, aiText: true, voice: true };
export const PRIVACY_KEY = 'transpeaktation.privacy'; // localStorage, next to 'transpeaktation.theme'

type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void };

/** Saved switches over the defaults; anything unreadable or non-boolean falls back to the default. */
export function parsePrivacy(raw: string | null | undefined): Privacy {
  let v: unknown = null;
  try { v = JSON.parse(raw ?? 'null'); } catch { /* corrupt: defaults */ }
  const o = v && typeof v === 'object' ? v as Record<string, unknown> : {};
  const pick = (k: keyof Privacy) => typeof o[k] === 'boolean' ? o[k] as boolean : DEFAULT_PRIVACY[k];
  return { saveTrips: pick('saveTrips'), aiText: pick('aiText'), voice: pick('voice') };
}

export function readPrivacy(storage: Store | undefined): Privacy {
  try { return parsePrivacy(storage?.getItem(PRIVACY_KEY)); } catch { return DEFAULT_PRIVACY; }
}

/** Storage failing (private mode) only means the choice lasts this visit. */
export function writePrivacy(p: Privacy, storage: Store | undefined): void {
  try { storage?.setItem(PRIVACY_KEY, JSON.stringify(p)); } catch { /* this visit only */ }
}

/** Extra /plan query for switches that are off; empty when everything is on. */
export const privacyQuery = (p: Privacy) => `${p.saveTrips ? '' : '&save=false'}${p.aiText ? '' : '&ai_text=false'}`;

export type PlanData = Plan['data'];
/** One stop on "where this trip's data went". `outside` = sent to a company other than us; `off` = skipped. */
export type Stop = { who: string; did: string; ai?: boolean; outside?: boolean; off?: boolean };

const TRAFFIC: Record<string, string> = {
  'tiger:live': 'live', 'tiger:observed': 'recorded at that time', 'tiger:typical': 'usual for that time',
};

/** Every service and model that touched a planned trip, in the order it happened, from /plan's `data` + `source`. */
export function dataPath(d: PlanData, source: string): Stop[] {
  const gemini = d.note.startsWith('gemini'), ml = d.decision.startsWith('ml:');
  return [
    source === 'mapbox'
      ? { who: 'Mapbox', did: 'Got your exact start and destination to draw route options.', outside: true }
      : { who: 'OSRM + OpenStreetMap', did: 'Got your exact start and destination to draw route options (free public servers).', outside: true },
    { who: 'transPEAKtation data', did: `Events: ${d.events === 'mongo' ? 'live list' : 'demo events'}. `
      + `Closures: ${d.incidents === 'mongo' ? 'city feeds' : 'unavailable'}. Traffic: ${TRAFFIC[d.traffic] ?? 'unavailable'}.` },
    ml
      ? { who: 'Route model', did: `${d.decision.slice(3)} picked the route from the data above, on our servers.`, ai: true }
      : { who: 'Rule-based estimate', did: 'Picked the route from the data above with fixed rules. No AI model.' },
    gemini
      ? { who: 'Google Gemini', did: 'Worded the route card from trip facts only: times, minutes, street and event names. No addresses or coordinates.', ai: true, outside: true }
      : d.note === 'ml'
        ? { who: 'Route model', did: 'Wrote the route card itself.', ai: true }
        : { who: 'Built-in sentence', off: d.note.includes('ai text off'),
            did: d.note.includes('ai text off') ? 'You turned AI text off, so nothing went to Google.' : 'Gemini wasn’t used this time, so nothing went to Google.' },
    d.stored === 'trips'
      ? { who: 'Trip log', did: 'Saved an area-level record to forecast crowds: start and end to ~100 m, and the roads used minus a few blocks at each end. No name, account or device ID.' }
      : { who: 'Trip log', off: true, did: d.stored === 'replay' ? 'Not saved: a replay isn’t a real trip.' : 'Not saved: you turned saving off.' },
  ];
}

/** One line under the transPEAKtation card: who decided, who wrote it, whether it was kept. */
export function traceLine(d: PlanData): string {
  const pick = d.decision.startsWith('ml:') ? 'AI model' : 'Rule-based';
  const text = d.note.startsWith('gemini') ? 'Gemini text' : d.note === 'ml' ? '' : 'No AI text';
  return [pick, text, d.stored === 'trips' ? 'Saved (area)' : 'Not saved'].filter(Boolean).join(' · ');
}

/** True when a switch that shapes /plan changed since `used` planned the trip on screen. */
export const planStale = (used: Privacy, now: Privacy) => used.saveTrips !== now.saveTrips || used.aiText !== now.aiText;
