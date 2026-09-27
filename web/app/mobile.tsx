'use client';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import { fmtDist, fmtTime, fmtWhen, iosArrival, mins, RECENT, stepText, type LatLng } from '@/lib/route.ts';
import { useRoutePlanner } from '@/lib/use-route-planner.ts';
import MapView, { type MapHandle } from './map-view.tsx';
import { AppBar, MapLayers, NavDialogs, useNav } from './menu.tsx';
import { Compass, Endpoints, Icon, MicButton, PlaceRow, RouteList, SearchResults, TripNote, TurnIcon, WhenPicker, WhereTo } from './parts.tsx';
import { RewardPanel } from './reward.tsx';

// Sheet heights as a share of the screen: peek, half, full (Apple Maps' three detents).
const DETENTS = [0.22, 0.5, 0.9];

/** Bottom sheet you can drag or flick between detents. Spread `handle` on the grab area (grabber + header);
 *  the list below keeps normal scrolling. `ceiling` = the element the sheet must stop under (the from/to card). */
function useSheet(ceiling: { current: HTMLElement | null }, initial = 1) {
  const [idx, setIdx] = useState(initial);
  const [dragH, setDragH] = useState<number | null>(null);
  const g = useRef<{ y0: number; h0: number; y: number; t: number; v: number } | null>(null);
  const TOP = DETENTS.length - 1;
  // Room left under the from/to card (if it's on screen), with an 8px gap.
  const room = () => {
    const card = ceiling.current?.querySelector('.endpoints'); // the card itself, not its open search dropdown
    return innerHeight - (card ? card.getBoundingClientRect().bottom + 8 : 0);
  };
  const px = (i: number) => i === TOP ? Math.min(DETENTS[i] * innerHeight, room()) : DETENTS[i] * innerHeight;

  const end = (e: PointerEvent) => {
    const d = g.current;
    g.current = null;
    if (!d || dragH === null) return;
    // Snap to the detent nearest where a flick would carry the sheet (v in px/ms, up = positive).
    const target = d.h0 + (d.y0 - e.clientY) + d.v * 250;
    const near = DETENTS.map((_, i) => Math.abs(px(i) - target));
    setIdx(near.indexOf(Math.min(...near)));
    setDragH(null);
  };
  const handle = {
    onPointerDown(e: PointerEvent) {
      if (e.button) return;
      g.current = { y0: e.clientY, h0: dragH ?? px(idx), y: e.clientY, t: e.timeStamp, v: 0 };
    },
    onPointerMove(e: PointerEvent<HTMLElement>) {
      const d = g.current;
      if (!d) return;
      const dy = d.y0 - e.clientY;
      if (dragH === null) {
        if (Math.abs(dy) < 6) return; // still a tap: let buttons in the header get their click
        e.currentTarget.setPointerCapture(e.pointerId); // now it's a drag; keep it even off the handle
      }
      d.v = (d.y - e.clientY) / Math.max(1, e.timeStamp - d.t);
      d.y = e.clientY; d.t = e.timeStamp;
      setDragH(Math.min(px(TOP), Math.max(px(0) * 0.8, d.h0 + dy)));
    },
    onPointerUp: end,
    onPointerCancel: end,
  };
  return {
    idx, setIdx, handle, dragging: dragH !== null,
    style: { '--sheet-h': dragH !== null ? `${dragH}px` : idx === TOP ? `${px(TOP)}px` : `${DETENTS[idx] * 100}dvh` } as CSSProperties,
    /** Grabber button: tap / Enter / Space steps up a detent, wrapping from full back to peek. */
    cycle: () => setIdx(i => (i + 1) % DETENTS.length),
  };
}

export default function Mobile() {
  const p = useRoutePlanner();
  const n = useNav(false);
  const map = useRef<MapHandle>(null);
  const [nav, setNav] = useState(false);
  const [step, setStep] = useState(0);
  const [dirs, setDirs] = useState(false);    // route screen: the full turn list (desktop's "Directions")
  const [dirStep, setDirStep] = useState(-1); // highlighted turn in that list
  const top = useRef<HTMLDivElement>(null);
  const sheet = useSheet(top);
  const r = p.selected, c = p.selectedCard;
  const hasRoutes = p.routes.length > 0 && !p.loading;
  const steps = r?.steps ?? [];
  const nextIdx = Math.min(step + 1, steps.length - 1), next = steps[nextIdx];
  const rest = steps.slice(step);
  // Step timings are the provider's; scale them to the picked card so navigation starts at the minutes it showed.
  const scale = r?.dur && c ? c.dur / r.dur : 1;
  const remDur = rest.reduce((a, x) => a + x.duration, 0) * scale, remDist = rest.reduce((a, x) => a + x.distance, 0);
  // Highlighted turn on the map: the upcoming one while navigating, the tapped one in the directions list.
  const markIdx = nav ? nextIdx : dirs ? dirStep : -1;
  const marker = useMemo<LatLng | null>(() => {
    const loc = r?.steps[markIdx]?.maneuver.location;
    return loc ? [loc[1], loc[0]] : null;
  }, [r, markIdx]);
  useEffect(() => { sheet.setIdx(1); setDirs(false); }, [p.screen]); // each screen opens at half height, on its first view
  useEffect(() => setDirStep(-1), [p.sel, p.routes]);
  // iOS app: while navigating a saved trip, native GPS marks it arrived near the destination. Browser: the button.
  const ios = iosArrival();
  const arrivedRef = useRef(p.arrived);
  arrivedRef.current = p.arrived;
  useEffect(() => {
    if (!ios || !nav || !p.to || !p.tripId || p.hasArrived) return;
    ios.postMessage({ lat: p.to.lat, lon: p.to.lon });
    const on = () => arrivedRef.current();
    addEventListener('tp-arrived', on);
    return () => { removeEventListener('tp-arrived', on); ios.postMessage(null); };
  }, [nav, p.to, p.tripId, p.hasArrived]);

  const goTo = (i: number) => {
    setStep(i);
    const loc = steps[i]?.maneuver.location;
    if (loc) map.current?.focus([loc[1], loc[0]]);
  };
  /** Directions list: highlight a turn and bring it into the map left between the from/to card and the sheet. */
  const pickTurn = (i: number) => {
    setDirStep(i);
    const loc = steps[i]?.maneuver.location;
    if (!loc) return;
    const idx = Math.min(sheet.idx, 1); // a full-height sheet would hide the map
    sheet.setIdx(idx);
    const cardBottom = top.current?.querySelector('.endpoints')?.getBoundingClientRect().bottom ?? 0;
    map.current?.focus([loc[1], loc[0]], 16, (DETENTS[idx] * innerHeight - cardBottom) / 2);
  };
  const closeDirs = () => { setDirs(false); setDirStep(-1); map.current?.fit(); };
  const close = () => { setNav(false); setStep(0); setDirs(false); p.goStart(); };
  const grabber = (
    <button className="grabber" aria-label={['Expand panel', 'Expand panel', 'Collapse panel'][sheet.idx]} onClick={sheet.cycle} />
  );

  return (
    <div className="mob" style={sheet.style}>
      <MapView ref={map} routes={p.routes} sel={p.sel} tp={p.choice.tp} labels={p.mapLabels} from={p.from} to={p.to} events={p.mapEvents} onSelect={p.setSel}
        marker={marker} span={p.mapSpan} routeEvents={p.selectedContext?.events} pad={{ topLeft: [24, 242], bottomRight: [24, 420] }} />
      <AppBar n={n} className="mob-bar" />

      {p.screen !== 'search' && !nav && (
        <>
          <Compass onPress={() => map.current?.fit()} className={p.screen === 'start' ? 'high' : ''} /> {/* fixed: stays centred over the layers button */}
          <MapLayers className={`mob-layers${p.screen === 'start' ? ' high' : ''}`} />
        </>
      )}

      {p.screen === 'start' && (
        <div className={`sheet${sheet.dragging ? ' dragging' : ''}`}>
          <div className="sheet-handle" {...sheet.handle}>
            {grabber}
            <div className="where-row">
              <div className="where-to fake">
                <button className="where-open" onClick={() => p.setScreen('search')}>
                  <Icon name="search" size={18} className="lead" /><span>Where to?</span>
                </button>
                <MicButton p={p} />
              </div>
            </div>
          </div>
          <div className="sheet-body">
            <div className="list">
              <div className="label">Recent</div>
              {RECENT.map(pl => <PlaceRow key={pl.label} place={pl} onPick={() => p.go(pl)} />)}
            </div>
          </div>
        </div>
      )}

      {p.screen === 'search' && (
        <div className="search-sheet" role="dialog" aria-label="Search">
          <div className="grabber static" />
          <div className="search-bar">
            <WhereTo p={p} autoFocus />
            <button className="link-btn" onClick={p.goStart}>Cancel</button>
          </div>
          <div className="search-body"><SearchResults p={p} /></div>
        </div>
      )}

      {p.screen === 'route' && !nav && (
        <>
          <div className="mob-top" ref={top}>
            <Endpoints p={p} placeholders={['Starting point', 'Where to?']} onPicked={() => { setDirs(false); setDirStep(-1); }} />
          </div>

          <div className={`sheet${sheet.dragging ? ' dragging' : ''}`}>
            <div className="sheet-handle" {...sheet.handle}>
              {grabber}
              <div className="sheet-head">
                {dirs && <button className="close-btn" aria-label="Back to routes" onClick={closeDirs}><Icon name="back" size={16} /></button>}
                <span className="title ellipsis grow">{dirs ? 'Directions to' : 'Routes to'} {p.to?.label}</span>
                <button className="close-btn" aria-label="Close" onClick={close}><Icon name="close" size={16} /></button>
              </div>
            </div>
            <div className="sheet-body">
              <div className="chips"><span className="chip on"><Icon name="car" size={16} />Drive</span><WhenPicker p={p} /></div>

              {p.loading && <div className="status">Finding routes…</div>}

              {p.error && (
                <div className="error">
                  <span>{p.error}</span>
                  <button className="ghost-btn" onClick={p.retry}>Retry</button>
                </div>
              )}

              {hasRoutes && !dirs && (
                <>
                  <TripNote note={p.trip.note} />
                  <RouteList p={p} />
                </>
              )}

              {hasRoutes && dirs && r && c && (
                <>
                  <div className="summary">
                    <div><b className="good">{mins(c.dur)} min</b><span>{c.tp ? 'transPEAKtation' : 'drive time'}</span></div>
                    <div><b>{fmtWhen(p.when.mode === 'arrive' ? c.leave : c.arrive)}</b><span>{p.when.mode === 'arrive' ? 'leave by' : 'arrival'}</span></div>
                    <div><b>{fmtDist(r.dist)}</b><span>distance</span></div>
                  </div>
                  <div className="steps">
                    {steps.map((st, i) => (
                      <button key={i} className={`step${i === dirStep ? ' on' : ''}`} aria-pressed={i === dirStep} onClick={() => pickTurn(i)}>
                        <span className="arrow"><TurnIcon step={st} /></span>
                        <span className="stack">
                          <span className="step-text">{stepText(st, p.to?.label ?? '')}</span>
                          <span className="sub">{st.distance > 0 ? fmtDist(st.distance) : ''}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
            {hasRoutes && (
              <div className="sheet-foot">
                {!dirs && <button className="foot-alt" onClick={() => { setDirs(true); setDirStep(-1); }}>Directions</button>}
                <button className="start" onClick={() => { setNav(true); setStep(0); if (r) map.current?.focus(r.coords[0]); }}>Start</button>
              </div>
            )}
          </div>
        </>
      )}

      <NavDialogs n={n} p={p} wide={false} />

      {p.screen === 'route' && nav && r && (
        <>
          <button className="turn" onClick={() => goTo(Math.min(step + 1, steps.length - 1))}>
            <span className="turn-arrow">{next ? <TurnIcon step={next} size={28} /> : <Icon name="arrow" size={28} />}</span>
            <span className="stack grow">
              <span className="sub">In {steps[step] ? fmtDist(steps[step].distance) : ''}</span>
              <span className="turn-text">{next ? stepText(next, p.to?.label ?? '') : ''}</span>
            </span>
            <span className="hint">Tap for next</span>
          </button>
          <div className={`nav-bar${p.earned || p.reward || (p.tripId && (!ios || p.hasArrived)) ? ' two-row' : ''}`}>
            <div className="nav-stats">
              <div><b className="good">{mins(remDur)}</b><span>min left</span></div>
              <div><b>{fmtTime(remDur)}</b><span>arrival</span></div>
              <div><b>{fmtDist(remDist)}</b><span>remaining</span></div>
            </div>
            {(p.earned || p.reward) && <RewardPanel p={p} />}
            {p.tripId && (!ios || p.hasArrived) && (
              <button className="end arrived-btn" disabled={p.hasArrived} onClick={p.arrived}>{p.hasArrived ? 'Arrived ✓' : 'Arrived'}</button>
            )}
            <button className="end" onClick={() => { setNav(false); setStep(0); map.current?.fit(); }}>End</button>
          </div>
        </>
      )}
    </div>
  );
}
