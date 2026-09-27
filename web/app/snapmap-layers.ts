// Leaflet drawing for the snapmap experiment (lib/experiment.ts): an "Event activity" heat canvas under the routes,
// progressive event pins, and a tiny legend. All rules live in lib/snapmap.ts; this file only draws them.
// No plugin: the heat layer is an additive density grid (kernel sized in metres), normalised to the busiest cluster in
// the time window, coloured through our palette as a lookup table.
import type * as Leaflet from 'leaflet';
import { EVENT_KINDS, eventGlyph, eventKind, fmtCategory, fmtEventTime, type MapEvent, type Span } from '@/lib/context.ts';
import {
  ACTIVITY_PALETTE, activityPoints, densityPeak, focusRel, heatAlpha, heatLevel, heatOpacity, heatRadiusMeters, kernel, legendOpacity,
  pinStates, relZoom, SF_BOUNDS, type HeatPoint,
} from '@/lib/snapmap.ts';
import type { Theme } from '@/lib/theme.ts';

export type SnapState = {
  events: MapEvent[];              // ingested events for the trip window (planner's mapEvents)
  span: Span;                      // the trip span they were fetched for
  routeEventIds: ReadonlySet<string>; // events on the selected route: shown at every zoom
  routeActive: boolean;
  theme: Theme;
};

const PANE = 'snap-activity';      // between tiles (200) and route lines (400): heat never covers a route
const RES = 0.4;                   // heat computed at 0.4x resolution: it's a soft glow, ~6x fewer pixels
const PAD = 0.25;                  // pins kept for this much of the view beyond each edge (smooth panning)
const MAX_ALPHA: Record<Theme, number> = { light: 0.78, dark: 0.8 }; // hotspot centre; edges fade to 0 (heatAlpha)

/** Palette as a 256-entry RGB lookup, low -> high. */
function paletteLut(): Uint8ClampedArray {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 1;
  const g = c.getContext('2d')!, grad = g.createLinearGradient(0, 0, 256, 0);
  ACTIVITY_PALETTE.forEach((col, i) => grad.addColorStop(i / (ACTIVITY_PALETTE.length - 1), col));
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 1);
  return g.getImageData(0, 0, 256, 1).data;
}

export class SnapMapLayers {
  private L: typeof Leaflet;
  private map: Leaflet.Map;
  private canvas: HTMLCanvasElement;
  private lut = paletteLut();
  private points: HeatPoint[] = [];
  private bounds: Leaflet.LatLngBounds | null = null;
  private pins = new Map<string, Leaflet.Marker>();
  private group: Leaflet.LayerGroup;
  private legend: HTMLDivElement;
  private state: SnapState | null = null;
  private selected: string | null = null;
  private byId = new Map<string, MapEvent>();
  private peakKey = '';
  private peak = 1;

  constructor(L: typeof Leaflet, map: Leaflet.Map) {
    this.L = L; this.map = map;
    const pane = map.createPane(PANE);
    pane.style.zIndex = '350';
    pane.style.pointerEvents = 'none';
    this.canvas = L.DomUtil.create('canvas', 'snap-heat leaflet-zoom-animated', pane) as HTMLCanvasElement;
    this.group = L.layerGroup().addTo(map);
    this.legend = L.DomUtil.create('div', 'activity-legend', map.getContainer()) as HTMLDivElement;
    this.legend.setAttribute('aria-label', 'Event activity: low to high. Where events are happening, not traffic.');
    this.legend.innerHTML = '<span class="t">Event activity</span><span class="ramp"><b>Low</b><i></i><b>High</b></span>';
    map.on('zoom viewreset resize', this.redraw, this);
    map.on('moveend', this.refresh, this);
    map.on('zoomanim', this.animateZoom, this);
    map.on('popupclose', this.onPopupClose, this);
    // iOS can drop a canvas's pixels while the app is in the background (and a 2D context can be lost / restored).
    // Nothing else repaints the heat until the map moves, so repaint when the page is shown again.
    document.addEventListener('visibilitychange', this.onShow);
    addEventListener('pageshow', this.onShow);
    this.canvas.addEventListener('contextrestored', this.onShow);
  }

  private onShow = () => { if (document.visibilityState === 'visible') this.redraw(); };

  destroy() {
    document.removeEventListener('visibilitychange', this.onShow);
    removeEventListener('pageshow', this.onShow);
    this.canvas.removeEventListener('contextrestored', this.onShow);
    this.map.off('zoom viewreset resize', this.redraw, this);
    this.map.off('moveend', this.refresh, this);
    this.map.off('zoomanim', this.animateZoom, this);
    this.map.off('popupclose', this.onPopupClose, this);
    this.group.remove();
    this.canvas.remove();
    this.legend.remove();
  }

  update(s: SnapState) {
    this.state = s;
    this.byId = new Map(s.events.map(e => [e.id, e]));
    if (this.selected && !this.byId.has(this.selected)) this.selected = null; // left the time window
    this.points = activityPoints(s.events, s.span);
    this.peakKey = '';
    this.refresh();
  }

  private refresh() { this.redraw(); }

  private redraw() {
    this.drawHeat();
    this.drawPins();
    const s = this.state;
    // No events to show (layers off, or none in the window): no key for an empty layer. Shown = fully opaque, so pins
    // under it never read through; it still fades in / out with the layer (CSS transition).
    if (s) this.legend.style.opacity = this.points.length && legendOpacity(this.rel(), s.routeActive) > 0 ? '1' : '0';
  }

  /** Zoom relative to the one that fits all of SF in this map's current size (lib/snapmap.ts). */
  private rel(): number {
    return relZoom(this.map.getZoom(), this.map.getBoundsZoom(this.L.latLngBounds(SF_BOUNDS)));
  }

  // ---- heat -------------------------------------------------------------------------------------------------
  private drawHeat() {
    const { map, canvas, L } = this, s = this.state;
    const size = map.getSize(), w = Math.max(1, Math.round(size.x * RES)), h = Math.max(1, Math.round(size.y * RES));
    const zoom = map.getZoom(), rel = this.rel();
    const topLeft = map.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setTransform(canvas, topLeft, 1);
    canvas.style.width = `${size.x}px`; canvas.style.height = `${size.y}px`;
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    this.bounds = map.getBounds();
    const opacity = s ? heatOpacity(rel, s.routeActive) : 0;
    canvas.style.opacity = String(opacity);
    const g = canvas.getContext('2d')!;
    g.clearRect(0, 0, w, h);
    if (!s || opacity <= 0 || !this.points.length) return;

    // Kernel radius on the ground -> grid cells at this zoom.
    const radiusM = heatRadiusMeters(rel);
    const key = `${radiusM.toFixed(0)}|${this.points.length}`;
    if (key !== this.peakKey) { this.peak = densityPeak(this.points, radiusM); this.peakKey = key; }
    const mPerPx = 40_075_016.686 * Math.cos(map.getCenter().lat * Math.PI / 180) / (256 * 2 ** zoom);
    const r = radiusM / mPerPx * RES, r2 = r * r;
    // 1. additive density (float, exact kernel; no 8-bit alpha stacking)
    const grid = new Float32Array(w * h);
    for (const p of this.points) {
      const c = map.latLngToContainerPoint([p.lat, p.lon]), cx = c.x * RES, cy = c.y * RES;
      if (cx < -r || cy < -r || cx > w + r || cy > h + r) continue;
      const x0 = Math.max(0, Math.floor(cx - r)), x1 = Math.min(w - 1, Math.ceil(cx + r));
      const y0 = Math.max(0, Math.floor(cy - r)), y1 = Math.min(h - 1, Math.ceil(cy + r));
      for (let y = y0; y <= y1; y++) {
        const dy = y - cy, row = y * w;
        for (let x = x0; x <= x1; x++) {
          const dx = x - cx, d2 = dx * dx + dy * dy;
          if (d2 < r2) grid[row + x] += p.w * kernel(Math.sqrt(d2 / r2));
        }
      }
    }
    // 2. relative intensity -> our palette; transparent below the floor so sparse areas stay a normal map
    const img = g.createImageData(w, h), d = img.data, lut = this.lut, max = MAX_ALPHA[s.theme], peak = this.peak;
    for (let i = 0; i < grid.length; i++) {
      if (!grid[i]) continue;
      const t = heatLevel(grid[i] / peak), a = heatAlpha(t, max);
      if (a <= 0) continue;
      const k = Math.round(t * 255) * 4, o = i * 4;
      d[o] = lut[k]; d[o + 1] = lut[k + 1]; d[o + 2] = lut[k + 2]; d[o + 3] = Math.round(a * 255);
    }
    g.putImageData(img, 0, 0);
  }

  /** Pinch / wheel zoom animation: scale the last frame like Leaflet's own overlays, redraw on 'zoom'. */
  private animateZoom(e: Leaflet.ZoomAnimEvent) {
    if (!this.bounds) return;
    const m = this.map as Leaflet.Map & { _latLngBoundsToNewLayerBounds(b: Leaflet.LatLngBounds, z: number, c: Leaflet.LatLng): Leaflet.Bounds };
    const scale = this.map.getZoomScale(e.zoom);
    const offset = m._latLngBoundsToNewLayerBounds(this.bounds, e.zoom, e.center).min!;
    this.L.DomUtil.setTransform(this.canvas, offset, scale);
  }

  // ---- pins -------------------------------------------------------------------------------------------------
  private drawPins() {
    const s = this.state, L = this.L;
    if (!s) return;
    const rel = this.rel();
    const view = this.map.getBounds().pad(PAD);
    const pinned = new Set(s.routeEventIds);
    if (this.selected) pinned.add(this.selected);
    const keep = new Set<string>();
    for (const st of pinStates(s.events, rel, pinned)) {
      const ev = this.byId.get(st.id)!;
      if (!view.contains([ev.lat, ev.lon])) continue;
      keep.add(st.id);
      let m = this.pins.get(st.id);
      if (!m) {
        // Same kind colour + glyph as the legend and the stable map's pins (lib/context.ts eventKind / eventGlyph).
        const kind = eventKind(ev);
        const icon = L.divIcon({ className: 'snap-pin-icon', iconSize: [30, 30], html: `<span class="snap-pin k-${kind}" style="--o:0;--s:1">${eventGlyph(kind)}</span>` });
        m = L.marker([ev.lat, ev.lon], { icon, keyboard: false, title: `${EVENT_KINDS[kind].label}: ${ev.name}`, zIndexOffset: -1000 + Math.round(st.imp.score * 100) })
          .on('click', () => this.select(st.id)).addTo(this.group);
        this.pins.set(st.id, m);
      }
      const el = m.getElement()?.firstElementChild as HTMLElement | null;
      if (!el) continue;
      // Fade in on the next frame when just created, so a new pin transitions from 0 instead of popping.
      const apply = () => {
        el.style.setProperty('--o', st.opacity.toFixed(3));
        el.style.setProperty('--s', st.scale.toFixed(3));
        el.classList.toggle('off', st.opacity < 0.15);
        el.classList.toggle('on', st.id === this.selected);
      };
      if (el.style.getPropertyValue('--o') === '0') requestAnimationFrame(apply); else apply();
    }
    for (const [id, m] of this.pins) if (!keep.has(id)) { m.remove(); this.pins.delete(id); }
  }

  /** Click a pin: keep it selected, glide in, then show its details. Its neighbours appear as the zoom passes
   *  their thresholds on the way in, not all at once. */
  private select(id: string) {
    const ev = this.byId.get(id);
    if (!ev) return;
    this.selected = id;
    const target = this.map.getZoom() + focusRel(this.rel()) - this.rel();
    const open = () => {
      this.drawPins();
      this.pins.get(id)?.bindPopup(() => eventCard(ev), { className: 'event-pop', closeButton: false, offset: [0, -8], autoPan: true }).openPopup();
    };
    if (this.map.getZoom() >= target && this.map.getBounds().pad(-0.2).contains([ev.lat, ev.lon])) return open();
    this.map.once('moveend', open);
    this.map.flyTo([ev.lat, ev.lon], target, { duration: 0.9 });
  }

  /** Closing the selected pin's card deselects it. Another pin's card closing (because a new pin was just picked)
   *  must not clear the new selection. */
  private onPopupClose(e: Leaflet.PopupEvent) {
    const source = (e.popup as unknown as { _source?: unknown })._source;
    if (this.selected && this.pins.get(this.selected) === source) { this.selected = null; this.drawPins(); }
  }
}

/** Only real fields: name, category, venue / street, SF time, closure extent, source. No crowd or delay numbers. */
function eventCard(ev: MapEvent): HTMLElement {
  const box = document.createElement('div');
  const blocks = new Set(ev.road_closure_ids ?? []).size;
  const source = ev.source === 'predicthq' ? 'PredictHQ' : ev.source === 'street_closures' ? 'DataSF street closures' : ev.source;
  const lines: [string, string | null][] = [
    ['cat', fmtCategory(ev.category) || null],
    ['name', ev.name],
    ['sub', ev.venue],
    ['sub', fmtEventTime(ev)],
    ['sub', blocks ? `Closes ${blocks} street block${blocks === 1 ? '' : 's'}` : null],
    ['sub src', source ? `Source: ${source}` : null],
  ];
  for (const [cls, text] of lines) {
    if (!text) continue;
    const line = box.appendChild(document.createElement('div'));
    line.className = cls;
    line.textContent = text;
  }
  return box;
}
