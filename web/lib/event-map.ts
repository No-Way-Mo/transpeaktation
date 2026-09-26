// How events look on the map, kept out of the Leaflet component so it can be tested: one universal pin (it only
// says "an event is happening here"), one geographic impact circle per event, and the detail card that is the only
// place the category shows. Plain TS so `node --test` can run it directly.
import { categoryKind, eventRadius, fmtCategory, fmtEventTime, type EventKind, type MapEvent } from './context.ts';
import { fmtDist, meters } from './route.ts';

// Fixed colours (not theme tokens): the blue reads on both the light and the dark basemap, and the white outline
// separates it from either.
export const EVENT_PIN_COLORS = { fill: '#1a759f', accent: '#184e77', icon: '#ffffff' } as const;
export const EVENT_PIN_PX = 30;
export const EVENT_PIN_SELECTED_PX = 36;
/** Generic calendar glyph (24-unit grid, drawn white). Static markup, never data. */
export const EVENT_GLYPH = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>';

export type EventPin = { className: string; size: number; html: string; title: string };
/** The marker for any event. Deliberately ignores category, source and everything else but the name (tooltip). */
export function eventPin(ev: Pick<MapEvent, 'name'>, selected: boolean): EventPin {
  const size = selected ? EVENT_PIN_SELECTED_PX : EVENT_PIN_PX;
  return { className: selected ? 'event-pin on' : 'event-pin', size, html: EVENT_GLYPH, title: `Event: ${ev.name}` };
}

// Impact circle: transPEAKtation palette, translucent #52b69a fill and a thin #168aad edge. One per event, never merged,
// never a heatmap; fainter under an active route (the route is what matters then) and a little stronger when selected.
export type CircleStyle = { fillColor: string; fillOpacity: number; color: string; opacity: number; weight: number };
export function impactCircleStyle({ selected, routeActive }: { selected: boolean; routeActive: boolean }): CircleStyle {
  const k = routeActive ? 0.7 : 1;
  return selected
    ? { fillColor: '#52b69a', fillOpacity: 0.16 * k, color: '#1a759f', opacity: 0.7 * k, weight: 2 }
    : { fillColor: '#52b69a', fillOpacity: 0.1 * k, color: '#168aad', opacity: 0.4 * k, weight: 1 };
}
/** The circles to draw: one per event, except that events on the very same spot with the same radius share one
 *  (8 PredictHQ events can sit on one venue point; 8 stacked translucent fills would read as a heatmap hotspot).
 *  Different places are never merged, however close. Biggest first, so smaller circles stay visible on top. */
export type ImpactArea = { lat: number; lon: number; radius: number; selected: boolean; ids: string[] };
export const SAME_SPOT_M = 2; // closer than this = the same point (feeds round coordinates differently)
export function impactAreas(events: MapEvent[], selectedId: string | null): ImpactArea[] {
  const out: ImpactArea[] = [];
  for (const e of events) {
    const radius = eventRadius(e).meters;
    let a = out.find(x => x.radius === radius && meters([x.lat, x.lon], [e.lat, e.lon]) < SAME_SPOT_M);
    if (!a) out.push((a = { lat: e.lat, lon: e.lon, radius, selected: false, ids: [] }));
    a.ids.push(e.id);
    a.selected ||= e.id === selectedId;
  }
  return out.sort((a, b) => b.radius - a.radius);
}

/** Subtle inner ring at half the radius, stroke only. */
export const innerRingStyle = ({ routeActive }: { routeActive: boolean }): CircleStyle =>
  ({ fillColor: '#52b69a', fillOpacity: 0, color: '#168aad', opacity: routeActive ? 0.14 : 0.2, weight: 1 });

export const IMPACT_LABEL = 'Estimated event impact area';
/** What the detail card shows on click: only fields /events actually has. No attendance, delay, road impact,
 *  congestion or importance (we have none of them). The category appears here and nowhere else. */
export type EventDetail = {
  name: string;
  category: { label: string; kind: EventKind } | null;
  venue: string | null;
  when: string;
  impact: { label: string; radius: string; source: 'api' | 'default' };
};
export function eventDetail(ev: MapEvent): EventDetail {
  const r = eventRadius(ev);
  return {
    name: ev.name,
    category: ev.category ? { label: fmtCategory(ev.category), kind: categoryKind(ev.category) } : null,
    venue: ev.venue,
    when: fmtEventTime(ev),
    impact: { label: IMPACT_LABEL, radius: `~${fmtDist(r.meters)} radius`, source: r.source },
  };
}

/** Compact map key: the event pin + circle entries whenever events are on the map; the route-traffic entries only
 *  when the selected route really has traffic readings to colour (no data = no misleading legend). */
export const legendItems = (eventCount: number, routeHasTraffic: boolean) => ({ events: eventCount > 0, traffic: routeHasTraffic });
