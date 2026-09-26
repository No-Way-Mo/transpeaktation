'use client';
import { useRef, useState } from 'react';
import { fmtDist, fmtTime, mins, RECENT, routeTag, stepArrow, stepText } from '@/lib/route.ts';
import { useRoutePlanner } from '@/lib/use-route-planner.ts';
import MapView, { type MapHandle } from './map-view.tsx';
import { Endpoints, PlaceRow, RouteCard } from './parts.tsx';

export default function Mobile() {
  const p = useRoutePlanner();
  const map = useRef<MapHandle>(null);
  const [nav, setNav] = useState(false);
  const [step, setStep] = useState(0);
  const r = p.selected;
  const steps = r?.steps ?? [];
  const next = steps[Math.min(step + 1, steps.length - 1)];
  const rest = steps.slice(step);
  const remDur = rest.reduce((a, x) => a + x.duration, 0), remDist = rest.reduce((a, x) => a + x.distance, 0);

  const goTo = (i: number) => {
    setStep(i);
    const loc = steps[i]?.maneuver.location;
    if (loc) map.current?.focus([loc[1], loc[0]]);
  };

  return (
    <div className="mob">
      <MapView ref={map} routes={p.routes} sel={p.sel} from={p.from} to={p.to} onSelect={p.setSel}
        pad={{ topLeft: [24, 190], bottomRight: [24, 380] }} />

      {!nav && (
        <>
          <div className="mob-top">
            <Endpoints p={p} placeholders={['Starting point', 'Where to?']} />
          </div>

          <button className="recenter" aria-label="Recenter map" onClick={() => map.current?.fit()}><i className="dot" /></button>

          <div className="sheet">
            <div className="grabber" />

            {!p.to && !p.loading && (
              <div className="list">
                <div className="label">Recent</div>
                {RECENT.map(pl => <PlaceRow key={pl.label} place={pl} onPick={() => p.pick('to', pl)} />)}
              </div>
            )}

            {p.loading && <div className="status">Finding routes…</div>}

            {p.error && (
              <div className="error">
                <span>{p.error}</span>
                <button className="ghost-btn" onClick={p.retry}>Retry</button>
              </div>
            )}

            {p.routes.length > 0 && !p.loading && (
              <>
                <div className="sheet-head">
                  <span className="title">Routes to {p.to?.label}</span>
                  <span className="sub">Drive · Leave now</span>
                </div>
                <div className="list">
                  {p.routes.map((rt, i) => (
                    <RouteCard key={i} route={rt} tag={routeTag(i, rt.dur, p.routes[0].dur)} selected={i === p.sel} onPick={() => p.setSel(i)} />
                  ))}
                </div>
                <button className="start" onClick={() => { setNav(true); setStep(0); if (r) map.current?.focus(r.coords[0]); }}>Start</button>
              </>
            )}
          </div>
        </>
      )}

      {nav && r && (
        <>
          <button className="turn" onClick={() => goTo(Math.min(step + 1, steps.length - 1))}>
            <span className="turn-arrow">{next ? stepArrow(next) : '↑'}</span>
            <span className="stack grow">
              <span className="sub">In {steps[step] ? fmtDist(steps[step].distance) : ''}</span>
              <span className="turn-text">{next ? stepText(next, p.to?.label ?? '') : ''}</span>
            </span>
            <span className="hint">Tap for next</span>
          </button>
          <div className="nav-bar">
            <div className="nav-stats">
              <div><b className="good">{mins(remDur)}</b><span>min left</span></div>
              <div><b>{fmtTime(remDur)}</b><span>arrival</span></div>
              <div><b>{fmtDist(remDist)}</b><span>remaining</span></div>
            </div>
            <button className="end" onClick={() => { setNav(false); setStep(0); map.current?.fit(); }}>End</button>
          </div>
        </>
      )}
    </div>
  );
}
