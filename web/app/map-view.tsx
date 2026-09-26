'use client';
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import type * as Leaflet from 'leaflet';
import { labelPoint, trafficRuns, type LatLng, type Place, type Route } from '@/lib/route.ts';

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
  onSelect(i: number): void;
  pad: { topLeft: [number, number]; bottomRight: [number, number] }; // room left for overlays when fitting
};

const dark = () => matchMedia('(prefers-color-scheme: dark)'); // browser-only: called from effects, never at import
const tiles = () => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${dark().matches ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`;

export default function MapView({ ref, routes, sel, tp, labels, from, to, marker, onSelect, pad }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const L = useRef<typeof Leaflet>(null);
  const map = useRef<Leaflet.Map>(null);
  const layer = useRef<Leaflet.LayerGroup>(null);
  const base = useRef<Leaflet.TileLayer>(null);
  const latest = useRef({ routes, sel, tp, labels, from, to, marker, pad, onSelect });
  latest.current = { routes, sel, tp, labels, from, to, marker, pad, onSelect };

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
      l.polyline(r.coords, { color: c('--route-casing-sel'), weight: 11, interactive: false }).addTo(g);
      l.polyline(r.coords, { color: line, weight: 7, interactive: false }).addTo(g);
      // Live slowdowns painted over the route, like Apple/Google: amber, orange-red, deep red.
      for (const run of trafficRuns(r)) l.polyline(run.coords, { color: c(`--traffic-${run.level}`), weight: 7, interactive: false }).addTo(g);
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
    if (from) l.circleMarker([from.lat, from.lon], { radius: 8, color: ring, weight: 3, fillColor: c('--origin'), fillOpacity: 1 }).addTo(g);
    if (to) l.circleMarker([to.lat, to.lon], { radius: 8, color: ring, weight: 3, fillColor: c('--dest'), fillOpacity: 1 }).addTo(g);
  };

  useEffect(() => {
    let cancelled = false;
    import('leaflet').then(mod => {
      if (cancelled || !el.current) return;
      const l = (L.current = mod.default ?? mod);
      const m = (map.current = l.map(el.current, { zoomControl: false }).setView([37.788, -122.4075], 14));
      m.attributionControl.setPrefix(false);
      base.current = l.tileLayer(tiles(), { attribution: 'Tiles © Esri', maxNativeZoom: 16, maxZoom: 18 }).addTo(m);
      layer.current = l.layerGroup().addTo(m);
      draw();
      fit();
    });
    const ro = new ResizeObserver(() => map.current?.invalidateSize());
    if (el.current) ro.observe(el.current);
    // System light/dark flips: swap the basemap and repaint the lines in the new theme's colours.
    const onTheme = () => { base.current?.setUrl(tiles()); draw(); };
    const mq = dark();
    mq.addEventListener('change', onTheme);
    return () => { cancelled = true; ro.disconnect(); mq.removeEventListener('change', onTheme); map.current?.remove(); map.current = null; };
  }, []);

  useEffect(draw, [routes, sel, tp, labels?.join(), from, to, marker]);
  // New routes or endpoints: frame them.
  useEffect(fit, [routes, from, to]);

  return <div ref={el} className="map" />;
}
