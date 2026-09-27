'use client';
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import type * as Leaflet from 'leaflet';
import { CARD_LABELS, fmtAdmission, isWebLink, type CardAction } from '@/lib/community.ts';
import { EVENT_KINDS, eventGlyph, eventImpact, eventKind, fmtCrowd, fmtEventTime, LIVE_RECHECK_MS, liveEvents, type MapEvent, type Span } from '@/lib/context.ts';
import { MAP_EXPERIMENT } from '@/lib/experiment.ts';
import { DEMO_START } from '@/lib/location.ts';
import { fmtDist, labelPoint, trafficRuns, type LatLng, type Place, type Route } from '@/lib/route.ts';
import type { MapStyle } from '@/lib/map-prefs.ts';
import { baseOf, type Theme } from '@/lib/theme.ts';
import { useMapPrefs } from '@/lib/use-map-prefs.ts';
import { useTheme } from '@/lib/use-theme.ts';
import { hexRgb, paintBasemap } from '@/lib/water.ts';
import { SF_BOUNDS } from '@/lib/snapmap.ts';
import { pulseOnce, SnapMapLayers } from './snapmap-layers.ts';

// Experiment boundary: with 'snapmap' the event layer below is replaced by snapmap-layers.ts (heat + progressive pins);
// routes, labels and endpoints are drawn exactly as before.
const SNAP = MAP_EXPERIMENT === 'snapmap';
const START_REL = 1.25; // start view vs the all-of-SF zoom: where a 1440px desktop lands at zoom 14

/** `focus` dy: show the point this many px above the map's centre (to clear a bottom sheet). `pan`: move to p at
 *  the current zoom (navigation following the rider). `center`: the spot under the map's centre ("Choose on map"). */
export type MapHandle = { fit(): void; focus(p: LatLng, zoom?: number, dy?: number): void; pan(p: LatLng): void; zoomIn(): void; zoomOut(): void; center(): LatLng | null; closePopup(): void };
/** What an event card on the map can do (app/host.tsx, lib/community.ts cardActions): `isHost` = this browser holds
 *  the key of this community event; `actions` = its ⋯ menu; `on` = View event, Directions or a ⋯ item. */
export type CardControls = {
  isHost(ev: MapEvent): boolean;
  actions(ev: MapEvent): CardAction[];
  on(a: CardAction | 'view' | 'directions', ev: MapEvent): void;
};

type Props = {
  ref?: Ref<MapHandle>;
  routes: Route[];
  sel: number;
  tp?: boolean;                     // selected card is transPEAKtation's: draw its route in the brand colour
  labels?: string[];                // "12 min" bubble per route, pinned on its line
  from: Place | null;
  to: Place | null;
  marker?: LatLng | null;           // highlighted turn on the selected route
  me?: LatLng | null;               // the rider's live GPS position while navigating
  events?: MapEvent[];              // ingested events in the trip's time window
  span?: Span;                      // the trip span those events were fetched for (snapmap: heat time filter)
  routeEvents?: MapEvent[] | null;  // events near the selected route (snapmap: kept visible at every zoom)
  focusEvent?: { id: string; n: number } | null; // bring this event into view, card open, one pulse (n: each request)
  eventsAt?: number | null;         // the map's time (Leave at / Arrive by departure); null = now, re-checked each minute
  card?: CardControls;              // View event / Directions / ⋯ on every event card
  onSelect(i: number): void;
  pad: { topLeft: [number, number]; bottomRight: [number, number] }; // room left for overlays when fitting
};

// Esri's own light / dark grey basemaps, repainted in our palette pixel by pixel (lib/water.ts paintBasemap: land,
// buildings and roads tone-mapped, water / parks in --map-water / --map-park); satellite is Esri's World Imagery
// from the same keyless tile server, left as is.
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const canvasUrl = (t: Theme) => `${ESRI}/Canvas/World_${baseOf(t) === 'dark' ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
type Fills = { water: string; park: string };
const baseLayer = (l: typeof Leaflet, t: Theme, s: MapStyle, fills: Fills): Leaflet.Layer => s === 'satellite'
  ? l.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, { attribution: 'Tiles © Esri, Maxar, Earthstar Geographics', maxNativeZoom: 18, maxZoom: 18 })
  : canvasLayer(l, t, fills);

/** The grey Canvas tiles, fetched with CORS so their pixels can be read, drawn through paintBasemap. A tile that
 *  fails to load stays empty (the map's --canvas background shows), as a plain tile layer would. */
function canvasLayer(l: typeof Leaflet, t: Theme, fills: Fills): Leaflet.Layer {
  const water = hexRgb(fills.water) ?? [0x9D, 0xD5, 0xE5], park = hexRgb(fills.park) ?? [0xB9, 0xD7, 0xA8];
  const Canvas = l.GridLayer.extend({
    createTile(c: Leaflet.Coords, done: (err: Error | undefined, tile: HTMLElement) => void) {
      const tile = document.createElement('canvas');
      tile.width = tile.height = 256;
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const g = tile.getContext('2d', { willReadFrequently: true })!;
        g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, 256, 256);
        paintBasemap(d.data, 256, baseOf(t), c.z, water, park);
        g.putImageData(d, 0, 0);
        done(undefined, tile);
      };
      img.onerror = () => done(undefined, tile);
      img.src = l.Util.template(canvasUrl(t), c);
      return tile;
    },
  });
  return new (Canvas as new (o: Leaflet.GridLayerOptions) => Leaflet.GridLayer)({ attribution: 'Tiles © Esri', maxNativeZoom: 16, maxZoom: 18 });
}

export default function MapView({ ref, routes, sel, tp, labels, from, to, marker, me, events, span, routeEvents, focusEvent, eventsAt = null, card, onSelect, pad }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const L = useRef<typeof Leaflet>(null);
  const map = useRef<Leaflet.Map>(null);
  const layer = useRef<Leaflet.LayerGroup>(null);
  const base = useRef<Leaflet.Layer>(null); // basemap: satellite tiles, or the repainted Canvas tiles (lib/water.ts)
  const snap = useRef<SnapMapLayers>(null);
  const pins = useRef(new Map<string, Leaflet.Marker>()); // stable map: event pins by id (focusEvent)
  const { theme } = useTheme();
  const { prefs } = useMapPrefs(); // map style + layers (Map layers button / Settings → Map & Routing)
  const look = useRef({ theme, prefs }); // Leaflet loads async: the tile layer must use the theme and style at that moment
  look.current = { theme, prefs };
  const latest = useRef({ routes, sel, tp, labels, from, to, marker, me, events, span, routeEvents, pad, onSelect, card, eventsAt });
  latest.current = { routes, sel, tp, labels, from, to, marker, me, events, span, routeEvents, pad, onSelect, card, eventsAt };
  /** Every event's card: community extras, View event / Directions and the ⋯ menu. */
  const decorate = (ev: MapEvent, box: HTMLElement) => {
    const c = latest.current.card;
    if (c) eventCardControls(ev, box, c, () => map.current?.closePopup());
  };

  const fit = () => {
    const { routes, sel, from, to, pad } = latest.current;
    if (!map.current) return;
    const pts: LatLng[] = routes[sel]?.coords ?? [from, to].filter(p => !!p).map(p => [p.lat, p.lon]);
    if (pts.length > 1) map.current.fitBounds(pts, { paddingTopLeft: pad.topLeft, paddingBottomRight: pad.bottomRight });
    else if (pts.length) {
      // One point (start screen): centre it in the space the overlays leave, not behind the sheet.
      // snapmap: street level on a desktop, but no closer than the same zoom relative to all of SF on a narrower
      // screen, so a phone opens with the heat and pins a desktop shows (lib/snapmap.ts zoom tiers).
      const zoom = SNAP ? Math.min(14, map.current.getBoundsZoom(SF_BOUNDS) + START_REL) : 14;
      map.current.setView(pts[0], zoom, { animate: false });
      map.current.panBy([(pad.bottomRight[0] - pad.topLeft[0]) / 2, (pad.bottomRight[1] - pad.topLeft[1]) / 2], { animate: false });
    }
  };

  useImperativeHandle(ref, () => ({
    fit,
    focus: (p, zoom = 16, dy = 0) => {
      const m = map.current;
      if (m) m.setView(dy ? m.unproject(m.project(p, zoom).add([0, dy]), zoom) : p, zoom);
    },
    pan: p => map.current?.panTo(p),
    zoomIn: () => map.current?.zoomIn(),
    zoomOut: () => map.current?.zoomOut(),
    center: () => { const c = map.current?.getCenter(); return c ? [c.lat, c.lng] : null; },
    closePopup: () => { map.current?.closePopup(); },
  }));

  // --map-water / --map-park for the theme showing right now (<html data-theme> flips before React re-renders).
  const fills = (): Fills => {
    const cs = el.current ? getComputedStyle(el.current) : null;
    return { water: cs?.getPropertyValue('--map-water').trim() ?? '', park: cs?.getPropertyValue('--map-park').trim() ?? '' };
  };

  const draw = () => {
    const l = L.current, g = layer.current;
    if (!l || !g || !el.current) return;
    const { routes, sel, tp, labels, from, to, marker, me, span, routeEvents } = latest.current;
    const { eventPins, traffic } = look.current.prefs;
    // Event Pins off: no pins, no impact areas (snapmap: no heat). On: only events that haven't ended at the map's time.
    const events = eventPins ? liveEvents(latest.current.events ?? [], latest.current.eventsAt ?? Date.now()) : undefined;
    // Colours come from the CSS theme tokens, so light/dark and brand changes stay in globals.css.
    const cs = getComputedStyle(el.current), c = (n: string) => cs.getPropertyValue(n).trim();
    const casing = c('--route-casing'), line = c(tp ? '--brand-line' : '--route');
    g.clearLayers();
    // Estimated impact areas under everything else: a faint dashed outer ring (where traffic may slow) and a
    // stronger core. Biggest first so a small event's area stays visible on top of a big one.
    if (!SNAP) [...(events ?? [])].map(ev => ({ ev, kind: eventKind(ev), r: eventImpact(ev).radius_m })).sort((a, b) => b.r - a.r)
      .forEach(({ ev, kind, r }) => {
        const col = c(`--ev-${kind}`), quiet = !EVENT_KINDS[kind].big;
        l.circle([ev.lat, ev.lon], { radius: r, color: col, weight: 1.5, opacity: quiet ? 0.35 : 0.6, dashArray: '4 5', fillColor: col, fillOpacity: quiet ? 0.05 : 0.08, interactive: false }).addTo(g);
        l.circle([ev.lat, ev.lon], { radius: r * 0.45, stroke: false, fillColor: col, fillOpacity: quiet ? 0.08 : 0.14, interactive: false }).addTo(g);
      });
    // Alternatives keep their colour but step back (thinner, ~70%) so the selected route leads; clicking swaps them.
    routes.forEach((r, i) => {
      if (i === sel) return;
      const pick = () => latest.current.onSelect(i);
      l.polyline(r.coords, { color: casing, weight: 9, opacity: 0.6 }).on('click', pick).addTo(g);
      l.polyline(r.coords, { color: c('--route-alt'), weight: 5, opacity: 0.75, className: 'alt-line' }).on('click', pick).addTo(g);
    });
    const r = routes[sel];
    if (r) {
      l.polyline(r.coords, { color: c('--route-casing-sel'), weight: 11, opacity: 0.9, interactive: false }).addTo(g);
      l.polyline(r.coords, { color: line, weight: 7, interactive: false, className: 'sel-line' }).addTo(g);
      // Live slowdowns painted over the route, like Apple/Google: amber, orange-red, deep red.
      if (traffic) for (const run of trafficRuns(r)) l.polyline(run.coords, { color: c(`--traffic-${run.level}`), weight: 7, interactive: false }).addTo(g);
    }
    // Labels sit above the lines; each one selects its route, like tapping the line.
    labels?.forEach((text, i) => {
      if (!routes[i]) return;
      const cls = i === sel ? (tp ? ' on tp' : ' on') : '';
      const icon = l.divIcon({ className: 'eta-pin', html: `<span class="eta-bubble${cls}">${text}</span>` });
      l.marker(labelPoint(routes, i), { icon, keyboard: false, zIndexOffset: i === sel ? 1000 : 0, title: `Route ${i + 1}: ${text}` })
        .on('click', () => latest.current.onSelect(i)).addTo(g);
    });
    // Event pins under the ETA labels; the popup is built from text nodes, never HTML from the data.
    // Colour + glyph per kind; big draws (festivals, concerts, conferences...) larger than block parties and markets.
    pins.current.clear();
    if (!SNAP) events?.forEach(ev => {
      const kind = eventKind(ev), n = EVENT_KINDS[kind].big ? 24 : 18;
      const icon = l.divIcon({ className: `event-pin k-${kind}`, iconSize: [n, n], html: eventGlyph(kind) });
      pins.current.set(ev.id, l.marker([ev.lat, ev.lon], { icon, keyboard: false, zIndexOffset: EVENT_KINDS[kind].big ? -900 : -1000, title: `${EVENT_KINDS[kind].label}: ${ev.name}` })
        .bindPopup(() => eventPopup(ev, decorate), { className: 'event-pop', closeButton: false, offset: [0, -2] }).addTo(g));
    });
    const ring = c('--marker-ring');
    if (marker) l.circleMarker(marker, { radius: 7, color: line, weight: 3, fillColor: ring, fillOpacity: 1 }).addTo(g);
    // Map convention: start = hollow ring dot, destination = teardrop pin with its tip on the spot.
    if (from) l.marker([from.lat, from.lon], { icon: l.divIcon({ className: 'origin-pin', iconSize: [18, 18] }), keyboard: false, zIndexOffset: 1500, title: `Start: ${from.label}` }).addTo(g);
    if (to) l.marker([to.lat, to.lon], { icon: l.divIcon({ className: 'dest-pin', iconSize: [28, 36], iconAnchor: [14, 35], html: DEST_PIN }), keyboard: false, zIndexOffset: 2000, title: `Destination: ${to.label}` }).addTo(g);
    if (me) l.circleMarker(me, { radius: 8, color: ring, weight: 3, fillColor: c('--action'), fillOpacity: 1, interactive: false }).addTo(g);
    snap.current?.update({
      events: events ?? [], span: span ?? { from: Date.now(), to: Date.now() },
      routeEventIds: new Set((routeEvents ?? []).map(e => e.id)), routeActive: routes.length > 0, theme: look.current.theme, decorate,
    });
  };

  useEffect(() => {
    let cancelled = false;
    import('leaflet').then(mod => {
      if (cancelled || !el.current) return;
      const l = (L.current = mod.default ?? mod);
      // snapmap: quarter-level zoom steps, so pins and heat change gradually as you wheel / pinch.
      const m = (map.current = l.map(el.current, { zoomControl: false, ...(SNAP ? { zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 100 } : {}) }).setView([DEMO_START.lat, DEMO_START.lon], 14));
      m.attributionControl.setPrefix(false);
      base.current = baseLayer(l, look.current.theme, look.current.prefs.style, fills()).addTo(m);
      layer.current = l.layerGroup().addTo(m);
      if (SNAP) snap.current = new SnapMapLayers(l, m);
      draw();
      fit();
    });
    const ro = new ResizeObserver(() => map.current?.invalidateSize());
    if (el.current) ro.observe(el.current);
    return () => { cancelled = true; ro.disconnect(); snap.current?.destroy(); snap.current = null; map.current?.remove(); map.current = null; };
  }, []);

  // Theme (Settings, or the OS on System) or map style changed: swap the basemap (its attribution too) and repaint the
  // lines and markers in the new theme's colours. The first run just repeats what the map was created with.
  useEffect(() => {
    const l = L.current, m = map.current;
    if (l && m && base.current) { base.current.remove(); base.current = baseLayer(l, theme, prefs.style, fills()).addTo(m); }
    draw();
  }, [theme, prefs.style]);
  // "Leave now": time moves on with the map open, so re-check once a minute and an event that ends leaves the map.
  // Redraw only (client-side filter): no refetch, no React render. A chosen time is fixed, so no timer then.
  useEffect(() => {
    if (eventsAt != null) return;
    const t = setInterval(draw, LIVE_RECHECK_MS);
    return () => clearInterval(t);
  }, [eventsAt]);
  useEffect(draw, [eventsAt]);
  // Event Pins / Traffic switched: redraw with or without them.
  useEffect(draw, [prefs.eventPins, prefs.traffic]);

  // span / routeEvents are rebuilt every render ("Leave now" moves by the millisecond): key them on minutes and ids.
  const spanKey = span ? `${Math.floor(span.from / 60_000)}-${Math.floor(span.to / 60_000)}` : '';
  const routeEventKey = routeEvents?.map(e => e.id).join() ?? '';
  useEffect(draw, [routes, sel, tp, labels?.join(), from, to, marker, me, events, spanKey, routeEventKey]);
  // New routes or endpoints: frame them.
  useEffect(fit, [routes, from, to]);
  // "View on map": after the draw above has the event, fly to it with its card open and one pulse.
  useEffect(() => {
    const m = map.current, id = focusEvent?.id;
    if (!m || !id) return;
    if (snap.current) { snap.current.focus(id); return; }
    const pin = pins.current.get(id);
    if (!pin) return;
    m.setView(pin.getLatLng(), Math.max(m.getZoom(), 16));
    pin.openPopup();
    pulseOnce(pin.getElement());
  }, [focusEvent?.n]);

  return (
    <>
      <div ref={el} className="map" data-style={prefs.style} />
      {theme === 'pride' && <PrideGradient />}
    </>
  );
}

const FLAG = ['#E40303', '#FF8C00', '#FFED00', '#008026', '#24408E', '#732982'];
/** Pride theme: the flag as SVG gradients (globals.css). #pride-route strokes the route lines: it repeats and slides
 *  along the line, so the rainbow flows toward the destination (still with reduced motion). #pride-flag fills the
 *  destination pin with the six hard stripes. */
function PrideGradient() {
  const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const stops = [...FLAG, FLAG[0]];
  return (
    <svg className="pride-defs" width="0" height="0" aria-hidden="true">
      <linearGradient id="pride-route" x1="0" y1="0" x2="0.5" y2="0.5" spreadMethod="repeat">
        {stops.map((c, i) => <stop key={i} offset={i / (stops.length - 1)} stopColor={c} />)}
        {!still && <animateTransform attributeName="gradientTransform" type="translate" from="0 0" to="0.5 0.5" dur="3s" repeatCount="indefinite" />}
      </linearGradient>
      <linearGradient id="pride-flag" x1="0" y1="0" x2="0" y2="1">
        {FLAG.flatMap((c, i) => [
          <stop key={`${i}a`} offset={i / FLAG.length} stopColor={c} />,
          <stop key={`${i}b`} offset={(i + 1) / FLAG.length} stopColor={c} />,
        ])}
      </linearGradient>
    </svg>
  );
}

const DEST_PIN = '<svg viewBox="0 0 28 36" aria-hidden="true"><path class="body" d="M14 34.5C14 34.5 26.5 21.8 26.5 13.5a12.5 12.5 0 0 0-25 0C1.5 21.8 14 34.5 14 34.5Z"/><circle class="hole" cx="14" cy="13.5" r="4.75"/></svg>';

/** Event name, venue, time, kind: what we already have, nothing more. */
function eventPopup(ev: MapEvent, decorate?: (ev: MapEvent, card: HTMLElement) => void): HTMLElement {
  const box = document.createElement('div');
  const kind = eventKind(ev), tag = box.appendChild(document.createElement('div'));
  tag.className = `kind k-${kind}`;
  tag.textContent = EVENT_KINDS[kind].label;
  const { crowd, radius_m } = eventImpact(ev);
  const impact = `${fmtCrowd(crowd)} (est.) · may slow traffic within ${fmtDist(radius_m)}`;
  for (const [cls, text] of [['name', ev.name], ['sub', ev.venue], ['sub', fmtEventTime(ev)], ['sub impact', impact]]) {
    if (!text) continue;
    const line = box.appendChild(document.createElement('div'));
    line.className = cls!;
    line.textContent = text;
  }
  decorate?.(ev, box);
  return box;
}

const el = <K extends keyof HTMLElementTagNameMap>(parent: HTMLElement, tag: K, cls: string, text?: string) => {
  const e = parent.appendChild(document.createElement(tag));
  e.className = cls;
  if (text) e.textContent = text;
  return e;
};

/** Every event card: a community event's extras (text nodes only, never HTML from the data), then View event +
 *  Directions and the ⋯ menu (lib/community.ts cardActions: host items only for this browser's own community event).
 *  "Your event" on top when this browser hosts it. */
function eventCardControls(ev: MapEvent, box: HTMLElement, c: CardControls, close: () => void) {
  const info = ev.community;
  if (info) {
    const line = el(box, 'div', 'sub admission', fmtAdmission(info));
    if (info.admission === 'ticketed' && info.ticket_url && isWebLink(info.ticket_url)) {
      line.append(' · ');
      const a = el(line, 'a', 'ticket-link', 'Tickets ↗');
      a.href = info.ticket_url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    }
    if (info.description) el(box, 'div', 'sub desc', info.description);
  }
  if (c.isHost(ev)) box.prepend(Object.assign(document.createElement('div'), { className: 'host-eyebrow', textContent: 'Your event' }));
  const go = (a: CardAction | 'view' | 'directions') => { if (a !== 'save' && a !== 'unsave') close(); c.on(a, ev); };
  const row = el(box, 'div', 'card-actions');
  for (const [a, label] of [['view', 'View event'], ['directions', 'Directions']] as const) {
    el(row, 'button', 'ghost-btn', label).addEventListener('click', () => go(a));
  }
  // ⋯ top right: a small menu built from the same rules as the lists; rebuilt each time it opens (saved state changes).
  const more = el(box, 'div', 'more card-more');
  const btn = el(more, 'button', 'more-btn', '⋯');
  btn.setAttribute('aria-label', `More for ${ev.name}`); btn.setAttribute('aria-haspopup', 'menu'); btn.setAttribute('aria-expanded', 'false');
  let pop: HTMLElement | null = null;
  const shut = () => { pop?.remove(); pop = null; btn.setAttribute('aria-expanded', 'false'); };
  btn.addEventListener('click', () => {
    if (pop) return shut();
    pop = el(more, 'div', 'more-pop');
    pop.setAttribute('role', 'menu');
    for (const a of c.actions(ev)) {
      const item = el(pop, 'button', `more-item${a === 'delete' || a === 'report' ? ' danger' : ''}`, CARD_LABELS[a]);
      item.setAttribute('role', 'menuitem');
      if (a === 'reported') item.disabled = true;
      item.addEventListener('click', () => { shut(); go(a); });
    }
    btn.setAttribute('aria-expanded', 'true');
    pop.querySelector<HTMLElement>('button:not([disabled])')?.focus();
  });
  more.addEventListener('keydown', e => { if (e.key === 'Escape' && pop) { e.stopPropagation(); shut(); btn.focus(); } });
}
