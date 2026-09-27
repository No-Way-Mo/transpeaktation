'use client';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { fmtDist, fmtTime, fmtWhen, iosArrival, mins, RECENT, stepText, type LatLng } from '@/lib/route.ts';
import { ARRIVED_EXIT_MS, isArrived, navFix, navProgress, type NavProgress } from '@/lib/nav-progress.ts';
import { cardActions, eventPlace, withEvent } from '@/lib/community.ts';
import type { MapEvent } from '@/lib/context.ts';
import { useHosting } from '@/lib/use-hosting.ts';
import { useMapPrefs } from '@/lib/use-map-prefs.ts';
import { usePosition } from '@/lib/use-position.ts';
import { useRoutePlanner } from '@/lib/use-route-planner.ts';
import { HostViews, PickBar, PickCross } from './host.tsx';
import MapView, { type CardControls, type MapHandle } from './map-view.tsx';
import { AppBar, MapLayers, NavDialogs, useNav } from './menu.tsx';
import { Compass, Endpoints, Icon, MicButton, PlaceRow, RouteList, SearchResults, TripNote, TurnIcon, WhenPicker, WhereTo } from './parts.tsx';
import { RewardPanel } from './reward.tsx';

// Sheet heights as a share of the screen: peek, half, full (Apple Maps' three detents).
const DETENTS = [0.22, 0.5, 0.9];
const FLICK = 0.35; // px/ms: a release faster than this moves one detent that way

/** Past a limit the sheet follows the finger less and less (iOS rubber band): at most 15% of the screen past it. */
const rubber = (over: number) => { const max = innerHeight * 0.15; return (1 - 1 / (over * 0.55 / max + 1)) * max; };

/** Bottom sheet you can drag or flick between detents. Spread `handle` on the grab area (grabber + header);
 *  the list below keeps normal scrolling. `ceiling` = the element the sheet must stop under (the from/to card).
 *  Put `root` on the element that carries --sheet-h: drags write it straight to the DOM, no React render per frame. */
function useSheet(ceiling: { current: HTMLElement | null }, initial = 1) {
  const [idx, setIdx] = useState(initial);
  const [dragging, setDragging] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const g = useRef<{ y0: number; h0: number; i0: number; y: number; t: number; v: number; on: boolean } | null>(null);
  const TOP = DETENTS.length - 1;
  // Room left under the from/to card if it's on screen (the card itself, not its open search dropdown), else under
  // the menu bar, with an 8px gap.
  const room = () => {
    const over = ceiling.current?.querySelector('.endpoints') ?? root.current?.querySelector('.mob-bar');
    return innerHeight - (over ? over.getBoundingClientRect().bottom + 8 : 0);
  };
  const px = (i: number) => i === TOP ? Math.min(DETENTS[i] * innerHeight, room()) : DETENTS[i] * innerHeight;
  const setH = (h: string) => root.current?.style.setProperty('--sheet-h', h);
  const rest = (i: number) => setH(i === TOP ? `${px(i)}px` : `${DETENTS[i] * 100}dvh`);

  // Resting height after every render (the from/to card may have moved) and on resize; never mid-drag.
  useLayoutEffect(() => { if (!g.current?.on) rest(idx); });
  useEffect(() => {
    const on = () => { if (!g.current?.on) rest(idx); };
    addEventListener('resize', on);
    return () => removeEventListener('resize', on);
  }, [idx]);

  const end = (e: PointerEvent) => {
    const d = g.current;
    g.current = null;
    if (!d?.on) return;
    const h = d.h0 + (d.y0 - e.clientY);
    const v = e.timeStamp - d.t > 80 ? 0 : d.v; // finger stopped before lifting: no flick
    let to: number;
    if (Math.abs(v) > FLICK) {
      // A flick moves one detent from where the drag started, never skips past the next one.
      to = Math.max(0, Math.min(TOP, d.i0 + Math.sign(v)));
    } else {
      const near = DETENTS.map((_, i) => Math.abs(px(i) - h));
      to = near.indexOf(Math.min(...near));
    }
    setDragging(false);
    setIdx(to);
    rest(to); // idx may not change (snap back); set it here rather than wait for a render
  };
  const handle = {
    onPointerDown(e: PointerEvent) {
      if (e.button) return;
      const h0 = root.current?.querySelector('.sheet')?.getBoundingClientRect().height ?? px(idx);
      g.current = { y0: e.clientY, h0, i0: idx, y: e.clientY, t: e.timeStamp, v: 0, on: false };
    },
    onPointerMove(e: PointerEvent<HTMLElement>) {
      const d = g.current;
      if (!d) return;
      const dy = d.y0 - e.clientY;
      if (!d.on) {
        if (Math.abs(dy) < 6) return; // still a tap: let buttons in the header get their click
        e.currentTarget.setPointerCapture(e.pointerId); // now it's a drag; keep it even off the handle
        d.on = true;
        setDragging(true);
      }
      // Smoothed velocity (px/ms, up = positive): one jittery last sample can't fling the sheet.
      const v = (d.y - e.clientY) / Math.max(1, e.timeStamp - d.t);
      d.v = d.v * 0.3 + v * 0.7;
      d.y = e.clientY; d.t = e.timeStamp;
      const h = d.h0 + dy, lo = px(0), hi = px(TOP);
      setH(`${h > hi ? hi + rubber(h - hi) : h < lo ? lo - rubber(lo - h) : h}px`);
    },
    onPointerUp: end,
    onPointerCancel: end,
  };
  return {
    idx, setIdx, handle, dragging, root, full: idx === TOP && !dragging,
    /** Grabber button: tap / Enter / Space steps up a detent, wrapping from full back to peek. */
    cycle: () => setIdx(i => (i + 1) % DETENTS.length),
  };
}

/** "10:55 PM" / "0.8 mi": the unit after the last space in smaller type, so the numbers carry the nav bar. */
const withUnit = (s: string) => {
  const i = s.lastIndexOf(' ');
  return i < 0 ? s : <>{s.slice(0, i)}<small>{s.slice(i)}</small></>;
};

export default function Mobile() {
  const p = useRoutePlanner();
  const h = useHosting();
  const n = useNav(false, h.start);
  const map = useRef<MapHandle>(null);
  const [nav, setNav] = useState(false);
  const [step, setStep] = useState(0);
  const [prog, setProg] = useState<NavProgress | null>(null); // from the last trusted GPS fix (null: none yet)
  const [navArrived, setNavArrived] = useState(false);        // GPS put the rider at the route's end
  const demo = useMapPrefs().prefs.location === 'demo';        // Settings → Map & Routing → Location mode
  const [demoStep, setDemoStep] = useState(0);                 // demo mode: the turn the simulated rider is at
  const gps = usePosition(nav && !navArrived && !demo);        // device mode: live GPS only while navigating
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
  // What's left: from GPS progress once there is a trusted fix, else from the turn shown (no GPS / denied).
  const remDur = prog ? prog.remDur : rest.reduce((a, x) => a + x.duration, 0) * scale;
  const remDist = prog ? prog.remDist : rest.reduce((a, x) => a + x.distance, 0);
  // Highlighted turn on the map: the upcoming one while navigating, the tapped one in the directions list.
  const markIdx = nav ? nextIdx : dirs ? dirStep : -1;
  // Where the rider is, from either source; both go through the same progress / arrival check below.
  const TurnBox = demo ? 'button' : 'div'; // the maneuver banner
  const fix = useMemo(() => nav && r ? navFix(demo ? 'demo' : 'device', r, demoStep, gps) : null, [nav, demo, r, demoStep, gps]);
  const marker = useMemo<LatLng | null>(() => {
    const loc = r?.steps[markIdx]?.maneuver.location;
    return loc ? [loc[1], loc[0]] : null;
  }, [r, markIdx]);
  useEffect(() => { sheet.setIdx(1); setDirs(false); }, [p.screen]); // each screen opens at half height, on its first view
  useEffect(() => setDirStep(-1), [p.sel, p.routes]);
  // iOS app: while navigating a saved trip, native GPS also logs its arrival (ios/, its own radius). UI arrival is
  // the position check below, on every platform.
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

  // Each fix (GPS, or demo taps): arrived only within ARRIVAL_THRESHOLD_METERS of the route's end (lib/nav-progress.ts); otherwise
  // move the turn and what's left along the route. Vague or off-route fixes change nothing.
  useEffect(() => {
    if (!fix || !r || navArrived) return;
    if (isArrived(fix, r)) {
      setNavArrived(true); setProg(null); setStep(Math.max(0, steps.length - 1));
      arrivedRef.current(); // logs the saved trip's arrival (no-op if it wasn't saved or already arrived)
      return;
    }
    const g = navProgress(fix, r, scale);
    if (g) { setProg(g); setStep(g.step); }
  }, [fix]);
  useEffect(() => { if (nav && fix) map.current?.pan(fix.pos); }, [fix]); // the map follows the rider

  /** Leave navigation. Arrived: back to the start screen to search again. Cancelled (End): back to the route list. */
  const finishNavigation = (why: 'arrived' | 'cancelled') => {
    setNav(false); setStep(0); setDemoStep(0); setProg(null); setNavArrived(false);
    if (why === 'arrived') { setDirs(false); p.goStart(); }
    else map.current?.fit();
  };
  // Arrived: show "Arrived ✓" briefly, then close. A reward to claim keeps it open until End.
  const holdOpen = p.earned || !!p.reward;
  const finishRef = useRef(finishNavigation);
  finishRef.current = finishNavigation;
  useEffect(() => {
    if (!navArrived || holdOpen) return;
    const t = setTimeout(() => finishRef.current('arrived'), ARRIVED_EXIT_MS);
    return () => clearTimeout(t);
  }, [navArrived, holdOpen]);

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
  // Community events (app/host.tsx): the host's sheet covers the others; "View on map" drops the main sheet to its
  // lowest detent so the event shows. A host's own event stays on the map even outside the trip window.
  const events = useMemo(() => withEvent(p.mapEvents, h.spotlight), [p.mapEvents, h.spotlight]);
  useEffect(() => { if (h.focus) sheet.setIdx(0); }, [h.focus?.n]);
  const directions = (ev: MapEvent) => { h.close(); setNav(false); setDirs(false); p.go(eventPlace(ev)); };
  useEffect(() => { if (h.view) map.current?.closePopup(); }, [h.view?.kind]); // an open map card would sit behind the sheet
  // Every event card on the map: View event (details), Directions (this app's planner) and the ⋯ menu.
  const card: CardControls = {
    isHost: h.isHost,
    actions: ev => cardActions(ev, { hosted: h.isHost(ev), saved: h.savedIds.has(ev.id), reported: h.isReported(ev) }),
    on: (a, ev) => a === 'view' ? h.viewEvent(ev) : a === 'directions' ? directions(ev) : h.act(a, ev),
  };
  const center = () => map.current?.center() ?? null;
  const grabber = (
    <button className="grabber" aria-label={['Expand panel', 'Expand panel', 'Collapse panel'][sheet.idx]} onClick={sheet.cycle} />
  );

  return (
    <div className={`mob${sheet.full ? ' sheet-full' : ''}${h.view ? ' hosting' : ''}`} ref={sheet.root}>
      <MapView ref={map} routes={p.routes} sel={p.sel} tp={p.choice.tp} labels={p.mapLabels} from={p.from} to={p.to} events={events} onSelect={p.setSel}
        marker={marker} me={fix?.pos ?? null} span={p.mapSpan} routeEvents={p.selectedContext?.events} pad={{ topLeft: [24, 242], bottomRight: [24, 420] }}
        focusEvent={h.focus} card={card}
        eventsAt={p.when.mode === 'now' ? null : p.mapSpan.from} />
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
                <button className="start" onClick={() => { setNav(true); setStep(0); setDemoStep(0); setProg(null); setNavArrived(false); p.start(); if (r) map.current?.focus(r.coords[0]); }}>Start</button>
              </div>
            )}
          </div>
        </>
      )}

      {h.view && h.view.kind !== 'pick' && (
        <div className="sheet host-sheet">
          <div className="grabber static" />
          <HostViews h={h} onDirections={directions} center={center} />
        </div>
      )}
      {h.view?.kind === 'pick' && <><PickCross /><PickBar h={h} center={center} className="mob-pick" /></>}

      <NavDialogs n={n} p={p} wide={false} />
      {h.notice && <div className="toast" role="status">{h.notice}</div>}

      {p.screen === 'route' && nav && r && (
        <>
          {/* Demo: tapping moves the simulated rider to the next turn. Device: GPS alone drives it, so not a button. */}
          <TurnBox className="turn" onClick={demo ? () => setDemoStep(i => Math.min(i + 1, steps.length - 1)) : undefined}>
            <span className="turn-arrow">{next ? <TurnIcon step={next} size={28} /> : <Icon name="arrow" size={28} />}</span>
            <span className="stack grow">
              <span className="sub">{navArrived || !steps[step] ? '' : `In ${fmtDist(prog ? prog.toNext : steps[step].distance)}`}</span>
              <span className="turn-text">{next ? stepText(next, p.to?.label ?? '') : ''}</span>
            </span>
            {demo && <span className="hint">Next</span>}
          </TurnBox>
          <div className={`nav-bar${p.earned || p.reward ? ' two-row' : ''}`}>
            {!navArrived && (
              <div className="nav-stats">
                <div><b className="good">{mins(remDur)}</b><span>min left</span></div>
                <div><b>{withUnit(fmtTime(remDur))}</b><span>arrival</span></div>
                <div><b>{withUnit(fmtDist(remDist))}</b><span>remaining</span></div>
              </div>
            )}
            {(p.earned || p.reward) && <RewardPanel p={p} />}
            {navArrived && <button className="end arrived-btn" disabled>Arrived ✓</button>}
            <button className="end" onClick={() => finishNavigation(navArrived ? 'arrived' : 'cancelled')}>End</button>
          </div>
        </>
      )}
    </div>
  );
}
