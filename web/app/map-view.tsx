'use client';
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import type * as Leaflet from 'leaflet';
import type { EventKind, MapEvent } from '@/lib/context.ts';
import { eventDetail, eventPin, impactAreas, impactCircleStyle, innerRingStyle } from '@/lib/event-map.ts';
import { labelPoint, type LatLng, type Place, type Route } from '@/lib/route.ts';
import type { Theme } from '@/lib/theme.ts';
import { getTrafficColor, routeTraffic } from '@/lib/traffic.ts';
import { useTheme } from '@/lib/use-theme.ts';

export type MapHandle = { fit(): void; focus(p: LatLng, zoom?: number): void; zoomIn(): void; zoomOut(): void };

type Props = {
  ref?: Ref<MapHandle>;
  routes: Route[];
  sel: number;
  tp?: boolean;                     // selected card is transPEAKtation's: draw its route in the brand colour
  labels?: string[];                // "12 min" bubble per route, pinned on its line
  from: Place | null;
  to: Place | null;
  marker?: LatLng | null;           // highlighted turn on the selected route
  events?: MapEvent[];              // ingested events in the trip's time window
  onSelect(i: number): void;
  pad: { topLeft: [number, number]; bottomRight: [number, number] }; // room left for overlays when fitting
};

// Esri's own light / dark grey basemaps, tinted toward the palette by --map-tint (globals.css).
const tiles = (t: Theme) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${t === 'dark' ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`;

export default function MapView({ ref, routes, sel, tp, labels, from, to, marker, events, onSelect, pad }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const L = useRef<typeof Leaflet>(null);
  const map = useRef<Leaflet.Map>(null);
  const layer = useRef<Leaflet.LayerGroup>(null);   // routes, ETA labels, turn marker, start / destination
  const evLayer = useRef<Leaflet.LayerGroup>(null); // event impact circles + pins, redrawn on their own
  const selected = useRef<string | null>(null);     // event whose detail card is open
  const base = useRef<Leaflet.TileLayer>(null);
  const { theme } = useTheme();
  const themeNow = useRef(theme); // Leaflet loads async: the tile layer must use the theme at that moment
  themeNow.current = theme;
  const latest = useRef({ routes, sel, tp, labels, from, to, marker, events, pad, onSelect });
  latest.current = { routes, sel, tp, labels, from, to, marker, events, pad, onSelect };

  const fit = () => {
    const { routes, sel, from, to, pad } = latest.current;
    if (!map.current) return;
    const pts: LatLng[] = routes[sel]?.coords ?? [from, to].filter(p => !!p).map(p => [p.lat, p.lon]);
    if (pts.length > 1) map.current.fitBounds(pts, { paddingTopLeft: pad.topLeft, paddingBottomRight: pad.bottomRight });
    else if (pts.length) {
      // One point (start screen): centre it in the space the overlays leave, not behind the sheet.
      map.current.setView(pts[0], 14, { animate: false });
      map.current.panBy([(pad.bottomRight[0] - pad.topLeft[0]) / 2, (pad.bottomRight[1] - pad.topLeft[1]) / 2], { animate: false });
    }
  };

  useImperativeHandle(ref, () => ({
    fit,
    focus: (p, zoom = 16) => map.current?.setView(p, zoom),
    zoomIn: () => map.current?.zoomIn(),
    zoomOut: () => map.current?.zoomOut(),
  }));

  // Layer order, bottom → top: basemap · event impact circles ('eventAreas' pane) · route casing · route line ·
  // traffic stretches · ETA labels / event pins · start / destination · popups.
  const draw = () => {
    const l = L.current, g = layer.current;
    if (!l || !g || !el.current) return;
    const { routes, sel, tp, labels, from, to, marker } = latest.current;
    // Colours come from the CSS theme tokens, so light/dark and brand changes stay in globals.css.
    const cs = getComputedStyle(el.current), c = (n: string) => cs.getPropertyValue(n).trim();
    const casing = c('--route-casing'), line = c(tp ? '--brand-line' : '--route');
    g.clearLayers();
    routes.forEach((r, i) => {
      if (i === sel) return;
      const pick = () => latest.current.onSelect(i);
      l.polyline(r.coords, { color: casing, weight: 10, opacity: 0.9 }).on('click', pick).addTo(g);
      l.polyline(r.coords, { color: c('--route-alt'), weight: 6 }).on('click', pick).addTo(g);
    });
    const r = routes[sel];
    if (r) {
      // One continuous route: navy casing + the normal line, then only the stretches with a real traffic reading
      // painted over it (lib/traffic.ts). No reading = the normal line shows. Events never colour it.
      l.polyline(r.coords, { color: c('--route-casing-sel'), weight: 11, interactive: false }).addTo(g);
      l.polyline(r.coords, { color: line, weight: 7, interactive: false }).addTo(g);
      for (const run of routeTraffic(r)) l.polyline(run.coords, { color: getTrafficColor(run.level), weight: 7, interactive: false }).addTo(g);
    }
    // Labels sit above the lines; each one selects its route, like tapping the line.
    labels?.forEach((text, i) => {
      if (!routes[i]) return;
      const cls = i === sel ? (tp ? ' on tp' : ' on') : '';
      const icon = l.divIcon({ className: 'eta-pin', html: `<span class="eta-bubble${cls}">${text}</span>` });
      l.marker(labelPoint(routes, i), { icon, keyboard: false, zIndexOffset: i === sel ? 1000 : 0, title: `Route ${i + 1}: ${text}` })
        .on('click', () => latest.current.onSelect(i)).addTo(g);
    });
    const ring = c('--marker-ring');
    if (marker) l.circleMarker(marker, { radius: 7, color: line, weight: 3, fillColor: ring, fillOpacity: 1 }).addTo(g);
    // Map convention: start = hollow ring dot, destination = teardrop pin with its tip on the spot.
    if (from) l.marker([from.lat, from.lon], { icon: l.divIcon({ className: 'origin-pin', iconSize: [18, 18] }), keyboard: false, zIndexOffset: 1500, title: `Start: ${from.label}` }).addTo(g);
    if (to) l.marker([to.lat, to.lon], { icon: l.divIcon({ className: 'dest-pin', iconSize: [28, 36], iconAnchor: [14, 35], html: DEST_PIN }), keyboard: false, zIndexOffset: 2000, title: `Destination: ${to.label}` }).addTo(g);
  };

  // Events: the same pin for every event and one geographic circle (metres, so it scales with zoom) per event, never
  // merged across places (impactAreas). Circles sit in their own pane under the route lines.
  const drawEvents = () => {
    const l = L.current, g = evLayer.current, m = map.current;
    if (!l || !g || !m) return;
    const { events, routes } = latest.current, routeActive = routes.length > 0, list = events ?? [];
    g.clearLayers();
    if (selected.current && !list.some(e => e.id === selected.current)) m.closePopup(); // its event left the window
    for (const a of impactAreas(list, selected.current)) {
      l.circle([a.lat, a.lon], { radius: a.radius, pane: 'eventAreas', interactive: false, ...impactCircleStyle({ selected: a.selected, routeActive }) }).addTo(g);
      l.circle([a.lat, a.lon], { radius: a.radius / 2, pane: 'eventAreas', interactive: false, ...innerRingStyle({ routeActive }) }).addTo(g);
    }
    list.forEach(ev => {
      const on = ev.id === selected.current, pin = eventPin(ev, on);
      const icon = l.divIcon({ className: pin.className, iconSize: [pin.size, pin.size], html: pin.html });
      l.marker([ev.lat, ev.lon], { icon, keyboard: false, zIndexOffset: on ? 800 : -900, title: pin.title })
        .on('click', () => openEvent(ev)).addTo(g);
    });
  };

  /** Select an event: bigger pin, stronger circle, and its detail card. Closing the card (×, a map click, another
   *  event's pin) deselects it. */
  const openEvent = (ev: MapEvent) => {
    const l = L.current, m = map.current;
    if (!l || !m) return;
    l.popup({ className: 'event-pop', offset: [0, -14], maxWidth: 280, autoPanPadding: [24, 24] })
      .setLatLng([ev.lat, ev.lon]).setContent(eventPopup(ev))
      .on('remove', () => { if (selected.current === ev.id) { selected.current = null; drawEvents(); } })
      .openOn(m); // closes the previous card first, which deselects that event
    selected.current = ev.id;
    drawEvents();
  };

  useEffect(() => {
    let cancelled = false;
    import('leaflet').then(mod => {
      if (cancelled || !el.current) return;
      const l = (L.current = mod.default ?? mod);
      const m = (map.current = l.map(el.current, { zoomControl: false }).setView([37.788, -122.4075], 14));
      m.attributionControl.setPrefix(false);
      base.current = l.tileLayer(tiles(themeNow.current), { attribution: 'Tiles © Esri', maxNativeZoom: 16, maxZoom: 18 }).addTo(m);
      m.createPane('eventAreas').style.zIndex = '350'; // above the tiles (200), below the route lines (overlayPane, 400)
      evLayer.current = l.layerGroup().addTo(m);
      layer.current = l.layerGroup().addTo(m);
      drawEvents();
      draw();
      fit();
    });
    const ro = new ResizeObserver(() => map.current?.invalidateSize());
    if (el.current) ro.observe(el.current);
    return () => { cancelled = true; ro.disconnect(); map.current?.remove(); map.current = null; };
  }, []);

  // Light/dark switch (toggle, or the OS when nothing is saved): swap the basemap and repaint the lines and markers
  // in the new theme's colours. The first run just repeats what the map was created with.
  useEffect(() => { base.current?.setUrl(tiles(theme)); draw(); drawEvents(); }, [theme]);

  useEffect(draw, [routes, sel, tp, labels?.join(), from, to, marker]);
  // Events redraw when they change or a route appears / goes (circles fade under a route), not on every route pick.
  useEffect(drawEvents, [events, routes.length > 0]);
  // New routes or endpoints: frame them.
  useEffect(fit, [routes, from, to]);

  return <div ref={el} className="map" />;
}

const DEST_PIN = '<svg viewBox="0 0 28 36" aria-hidden="true"><path class="body" d="M14 34.5C14 34.5 26.5 21.8 26.5 13.5a12.5 12.5 0 0 0-25 0C1.5 21.8 14 34.5 14 34.5Z"/><circle class="hole" cx="14" cy="13.5" r="4.75"/></svg>';

// Category icons, used ONLY inside the detail card (the map pin is the same for every event). 24×24 stroke glyphs,
// static strings, never data.
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

/** Detail card: name, the API's category (with its icon), venue, time and the estimated impact area. Text comes in
 *  as text nodes, never as HTML from the data. */
function eventPopup(ev: MapEvent): HTMLElement {
  const d = eventDetail(ev), box = document.createElement('div');
  const line = (cls: string, text: string | null) => {
    if (!text) return;
    const n = box.appendChild(document.createElement('div'));
    n.className = cls;
    n.textContent = text;
  };
  line('name', d.name);
  if (d.category) {
    const tag = box.appendChild(document.createElement('div'));
    tag.className = `kind k-${d.category.kind}`;
    tag.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${GLYPHS[d.category.kind]}</svg>`; // static glyph only
    tag.appendChild(document.createTextNode(d.category.label));
  }
  line('sub', d.venue);
  line('sub', d.when);
  line('impact', d.impact.label);
  line('sub', d.impact.radius);
  return box;
}
