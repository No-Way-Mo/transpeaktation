'use client';
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import type * as Leaflet from 'leaflet';
import { EVENT_KINDS, eventImpact, eventKind, fmtCrowd, fmtEventTime, type EventKind, type MapEvent, type Span } from '@/lib/context.ts';
import { MAP_EXPERIMENT } from '@/lib/experiment.ts';
import { DEMO_START } from '@/lib/location.ts';
import { fmtDist, labelPoint, trafficRuns, type LatLng, type Place, type Route } from '@/lib/route.ts';
import type { MapStyle } from '@/lib/map-prefs.ts';
import type { Theme } from '@/lib/theme.ts';
import { useMapPrefs } from '@/lib/use-map-prefs.ts';
import { useTheme } from '@/lib/use-theme.ts';
import { ESRI_WATER, hexRgb, paintWater } from '@/lib/water.ts';
import { SF_BOUNDS } from '@/lib/snapmap.ts';
import { SnapMapLayers } from './snapmap-layers.ts';

// Experiment boundary: with 'snapmap' the event layer below is replaced by snapmap-layers.ts (heat + progressive pins);
// routes, labels and endpoints are drawn exactly as before.
const SNAP = MAP_EXPERIMENT === 'snapmap';
const START_REL = 1.25; // start view vs the all-of-SF zoom: where a 1440px desktop lands at zoom 14

/** `focus` dy: show the point this many px above the map's centre (to clear a bottom sheet). `pan`: move to p at
 *  the current zoom (navigation following the rider). */
export type MapHandle = { fit(): void; focus(p: LatLng, zoom?: number, dy?: number): void; pan(p: LatLng): void; zoomIn(): void; zoomOut(): void };

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
  onSelect(i: number): void;
  pad: { topLeft: [number, number]; bottomRight: [number, number] }; // room left for overlays when fitting
};

// Esri's own light / dark grey basemaps, tinted toward the palette by --map-tint (globals.css), with their water
// repainted --map-water (lib/water.ts); satellite is Esri's World Imagery from the same keyless tile server, left as is.
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const canvasUrl = (t: Theme) => `${ESRI}/Canvas/World_${t === 'dark' ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`;
// crossOrigin on both layers: one CORS request per tile, shared by the basemap and the water layer that reads its pixels.
const baseLayer = (l: typeof Leaflet, t: Theme, s: MapStyle, water: string): Leaflet.Layer => s === 'satellite'
  ? l.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, { attribution: 'Tiles © Esri, Maxar, Earthstar Geographics', maxNativeZoom: 18, maxZoom: 18 })
  : l.layerGroup([
    l.tileLayer(canvasUrl(t), { attribution: 'Tiles © Esri', maxNativeZoom: 16, maxZoom: 18, crossOrigin: 'anonymous' }),
    waterLayer(l, t, water),
  ]);

/** The basemap's water only, in `color`, on the 'water' pane: above the (tinted) tiles, so the blue is exact, and
 *  under routes and pins. A tile that fails to load just draws no water; the basemap under it is unchanged. */
function waterLayer(l: typeof Leaflet, t: Theme, color: string): Leaflet.Layer {
  const to = hexRgb(color) ?? [0x9D, 0xD5, 0xE5], from = ESRI_WATER[t];
  const Water = l.GridLayer.extend({
    createTile(c: Leaflet.Coords, done: (err: Error | undefined, tile: HTMLElement) => void) {
      const tile = document.createElement('canvas');
      tile.width = tile.height = 256;
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const g = tile.getContext('2d', { willReadFrequently: true })!;
        g.drawImage(img, 0, 0);
        const d = g.getImageData(0, 0, 256, 256);
        paintWater(d.data, from, to);
        g.putImageData(d, 0, 0);
        done(undefined, tile);
      };
      img.onerror = () => done(undefined, tile);
      img.src = l.Util.template(canvasUrl(t), c);
      return tile;
    },
  });
  return new (Water as new (o: Leaflet.GridLayerOptions) => Leaflet.GridLayer)({ pane: 'water', maxNativeZoom: 16, maxZoom: 18 });
}

export default function MapView({ ref, routes, sel, tp, labels, from, to, marker, me, events, span, routeEvents, onSelect, pad }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const L = useRef<typeof Leaflet>(null);
  const map = useRef<Leaflet.Map>(null);
  const layer = useRef<Leaflet.LayerGroup>(null);
  const base = useRef<Leaflet.Layer>(null); // basemap: a tile layer, or tiles + water in a group (lib/water.ts)
  const snap = useRef<SnapMapLayers>(null);
  const { theme } = useTheme();
  const { prefs } = useMapPrefs(); // map style + layers (Map layers button / Settings → Map & Routing)
  const look = useRef({ theme, prefs }); // Leaflet loads async: the tile layer must use the theme and style at that moment
  look.current = { theme, prefs };
  const latest = useRef({ routes, sel, tp, labels, from, to, marker, me, events, span, routeEvents, pad, onSelect });
  latest.current = { routes, sel, tp, labels, from, to, marker, me, events, span, routeEvents, pad, onSelect };

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
  }));

  // --map-water for the theme showing right now (<html data-theme> flips before React re-renders).
  const waterColor = () => (el.current ? getComputedStyle(el.current).getPropertyValue('--map-water').trim() : '');

  const draw = () => {
    const l = L.current, g = layer.current;
    if (!l || !g || !el.current) return;
    const { routes, sel, tp, labels, from, to, marker, me, span, routeEvents } = latest.current;
    const { eventPins, traffic } = look.current.prefs;
    const events = eventPins ? latest.current.events : undefined; // Event Pins off: no pins, no impact areas (snapmap: no heat)
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
    routes.forEach((r, i) => {
      if (i === sel) return;
      const pick = () => latest.current.onSelect(i);
      l.polyline(r.coords, { color: casing, weight: 10, opacity: 0.9 }).on('click', pick).addTo(g);
      l.polyline(r.coords, { color: c('--route-alt'), weight: 6 }).on('click', pick).addTo(g);
    });
    const r = routes[sel];
    if (r) {
      l.polyline(r.coords, { color: c('--route-casing-sel'), weight: 11, interactive: false }).addTo(g);
      l.polyline(r.coords, { color: line, weight: 7, interactive: false }).addTo(g);
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
    if (!SNAP) events?.forEach(ev => {
      const kind = eventKind(ev), n = EVENT_KINDS[kind].big ? 24 : 18;
      const icon = l.divIcon({ className: `event-pin k-${kind}`, iconSize: [n, n], html: eventGlyph(kind) });
      l.marker([ev.lat, ev.lon], { icon, keyboard: false, zIndexOffset: EVENT_KINDS[kind].big ? -900 : -1000, title: `${EVENT_KINDS[kind].label}: ${ev.name}` })
        .bindPopup(() => eventPopup(ev), { className: 'event-pop', closeButton: false, offset: [0, -2] }).addTo(g);
    });
    const ring = c('--marker-ring');
    if (marker) l.circleMarker(marker, { radius: 7, color: line, weight: 3, fillColor: ring, fillOpacity: 1 }).addTo(g);
    // Map convention: start = hollow ring dot, destination = teardrop pin with its tip on the spot.
    if (from) l.marker([from.lat, from.lon], { icon: l.divIcon({ className: 'origin-pin', iconSize: [18, 18] }), keyboard: false, zIndexOffset: 1500, title: `Start: ${from.label}` }).addTo(g);
    if (to) l.marker([to.lat, to.lon], { icon: l.divIcon({ className: 'dest-pin', iconSize: [28, 36], iconAnchor: [14, 35], html: DEST_PIN }), keyboard: false, zIndexOffset: 2000, title: `Destination: ${to.label}` }).addTo(g);
    if (me) l.circleMarker(me, { radius: 8, color: ring, weight: 3, fillColor: c('--action'), fillOpacity: 1, interactive: false }).addTo(g);
    snap.current?.update({
      events: events ?? [], span: span ?? { from: Date.now(), to: Date.now() },
      routeEventIds: new Set((routeEvents ?? []).map(e => e.id)), routeActive: routes.length > 0, theme: look.current.theme,
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
      const water = m.createPane('water'); // between the tile pane (200) and the routes / pins (400+)
      water.style.zIndex = '250';
      water.style.pointerEvents = 'none';
      base.current = baseLayer(l, look.current.theme, look.current.prefs.style, waterColor()).addTo(m);
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
    if (l && m && base.current) { base.current.remove(); base.current = baseLayer(l, theme, prefs.style, waterColor()).addTo(m); }
    draw();
  }, [theme, prefs.style]);
  // Event Pins / Traffic switched: redraw with or without them.
  useEffect(draw, [prefs.eventPins, prefs.traffic]);

  // span / routeEvents are rebuilt every render ("Leave now" moves by the millisecond): key them on minutes and ids.
  const spanKey = span ? `${Math.floor(span.from / 60_000)}-${Math.floor(span.to / 60_000)}` : '';
  const routeEventKey = routeEvents?.map(e => e.id).join() ?? '';
  useEffect(draw, [routes, sel, tp, labels?.join(), from, to, marker, me, events, spanKey, routeEventKey]);
  // New routes or endpoints: frame them.
  useEffect(fit, [routes, from, to]);

  return <div ref={el} className="map" data-style={prefs.style} />;
}

const DEST_PIN = '<svg viewBox="0 0 28 36" aria-hidden="true"><path class="body" d="M14 34.5C14 34.5 26.5 21.8 26.5 13.5a12.5 12.5 0 0 0-25 0C1.5 21.8 14 34.5 14 34.5Z"/><circle class="hole" cx="14" cy="13.5" r="4.75"/></svg>';

// 24×24 stroke glyphs (static strings, never data), drawn white inside the kind's coloured disc.
const GLYPHS: Record<EventKind, string> = {
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  sports: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.7V17c0 .6-.5 1-1 1.2C7.9 18.8 7 20.2 7 22M14 14.7V17c0 .6.5 1 1 1.2 1.1.6 2 2 2 3.8M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
  parade: '<path d="M4 22V3M4 4h14l-3 4.5L18 13H4"/>',
  festival: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9Z"/>',
  conference: '<path d="M3 4h18M4 4v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4M12 16v4M8 21l4-1 4 1"/>',
  market: '<path d="M3 9h18l-1.5 11h-15ZM8 9l4-6 4 6M9 13v4M15 13v4"/>',
  community: '<path d="M3 11 12 3l9 8M5 9.5V21h14V9.5M10 21v-6h4v6"/>',
  other: '<circle cx="12" cy="12" r="3.5"/>',
};
export const eventGlyph = (k: EventKind) => `<svg viewBox="0 0 24 24" aria-hidden="true">${GLYPHS[k]}</svg>`;

/** Event name, venue, time, kind: what we already have, nothing more. */
function eventPopup(ev: MapEvent): HTMLElement {
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
  return box;
}
