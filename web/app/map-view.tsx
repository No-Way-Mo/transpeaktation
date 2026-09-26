'use client';
import { useEffect, useImperativeHandle, useRef, type Ref } from 'react';
import type * as Leaflet from 'leaflet';
import { labelPoint, type LatLng, type Place, type Route } from '@/lib/route.ts';

export type MapHandle = { fit(): void; focus(p: LatLng, zoom?: number): void; zoomIn(): void; zoomOut(): void };

type Props = {
  ref?: Ref<MapHandle>;
  routes: Route[];
  sel: number;
  labels?: string[];                // "12 min" bubble per route, pinned on its line
  from: Place | null;
  to: Place | null;
  marker?: LatLng | null;           // highlighted turn on the selected route
  onSelect(i: number): void;
  pad: { topLeft: [number, number]; bottomRight: [number, number] }; // room left for overlays when fitting
};

const TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
const CASING = '#060C16';

export default function MapView({ ref, routes, sel, labels, from, to, marker, onSelect, pad }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const L = useRef<typeof Leaflet>(null);
  const map = useRef<Leaflet.Map>(null);
  const layer = useRef<Leaflet.LayerGroup>(null);
  const latest = useRef({ routes, sel, labels, from, to, pad, onSelect });
  latest.current = { routes, sel, labels, from, to, pad, onSelect };

  const fit = () => {
    const { routes, sel, from, to, pad } = latest.current;
    if (!map.current) return;
    const pts: LatLng[] = routes[sel]?.coords ?? [from, to].filter(p => !!p).map(p => [p.lat, p.lon]);
    if (pts.length > 1) map.current.fitBounds(pts, { paddingTopLeft: pad.topLeft, paddingBottomRight: pad.bottomRight });
    else if (pts.length) map.current.setView(pts[0], 14);
  };

  useImperativeHandle(ref, () => ({
    fit,
    focus: (p, zoom = 16) => map.current?.setView(p, zoom),
    zoomIn: () => map.current?.zoomIn(),
    zoomOut: () => map.current?.zoomOut(),
  }));

  const draw = () => {
    const l = L.current, g = layer.current;
    if (!l || !g) return;
    const { routes, sel, labels, from, to } = latest.current;
    g.clearLayers();
    routes.forEach((r, i) => {
      if (i === sel) return;
      const pick = () => latest.current.onSelect(i);
      l.polyline(r.coords, { color: CASING, weight: 10, opacity: 0.8 }).on('click', pick).addTo(g);
      l.polyline(r.coords, { color: '#8C9AB3', weight: 6, opacity: 0.7 }).on('click', pick).addTo(g);
    });
    const r = routes[sel];
    if (r) {
      l.polyline(r.coords, { color: '#9D8CFF', weight: 16, opacity: 0.18, interactive: false }).addTo(g);
      l.polyline(r.coords, { color: CASING, weight: 10, interactive: false }).addTo(g);
      l.polyline(r.coords, { color: '#9D8CFF', weight: 6, interactive: false }).addTo(g);
    }
    // Labels last so they sit above the lines; each one selects its route, like tapping the line.
    labels?.forEach((text, i) => {
      if (!routes[i]) return;
      const icon = l.divIcon({ className: 'eta-pin', html: `<span class="eta-bubble${i === sel ? ' on' : ''}">${text}</span>` });
      l.marker(labelPoint(routes, i), { icon, keyboard: false, zIndexOffset: i === sel ? 1000 : 0, title: `Route ${i + 1}: ${text}` })
        .on('click', () => latest.current.onSelect(i)).addTo(g);
    });
    if (marker) l.circleMarker(marker, { radius: 7, color: '#9D8CFF', weight: 3, fillColor: CASING, fillOpacity: 1 }).addTo(g);
    if (from) l.circleMarker([from.lat, from.lon], { radius: 8, color: CASING, weight: 3, fillColor: '#6FD3FF', fillOpacity: 1 }).addTo(g);
    if (to) l.circleMarker([to.lat, to.lon], { radius: 8, color: CASING, weight: 3, fillColor: '#E7EDF6', fillOpacity: 1 }).addTo(g);
  };

  useEffect(() => {
    let cancelled = false;
    import('leaflet').then(mod => {
      if (cancelled || !el.current) return;
      const l = (L.current = mod.default ?? mod);
      const m = (map.current = l.map(el.current, { zoomControl: false }).setView([37.788, -122.4075], 14));
      m.attributionControl.setPrefix(false);
      l.tileLayer(TILES, { attribution: 'Tiles © Esri', maxNativeZoom: 16, maxZoom: 18 }).addTo(m);
      layer.current = l.layerGroup().addTo(m);
      draw();
      fit();
    });
    const ro = new ResizeObserver(() => map.current?.invalidateSize());
    if (el.current) ro.observe(el.current);
    return () => { cancelled = true; ro.disconnect(); map.current?.remove(); map.current = null; };
  }, []);

  useEffect(draw, [routes, sel, labels?.join(), from, to, marker]);
  // New routes or endpoints: frame them.
  useEffect(fit, [routes, from, to]);

  return <div ref={el} className="map" />;
}
