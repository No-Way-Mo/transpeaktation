'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { fmtDist, fmtTime, mins, RECENT, routeTag, stepArrow, stepText, type LatLng } from '@/lib/route.ts';
import { useRoutePlanner } from '@/lib/use-route-planner.ts';
import MapView, { type MapHandle } from './map-view.tsx';
import { Endpoints, PlaceRow, RouteCard } from './parts.tsx';

export default function Desktop() {
  const p = useRoutePlanner();
  const map = useRef<MapHandle>(null);
  const [steps, setSteps] = useState(false);
  const [step, setStep] = useState(-1);
  const r = p.selected;
  const hasRoutes = p.routes.length > 0 && !p.loading;
  const marker = useMemo<LatLng | null>(() => {
    const loc = steps ? r?.steps[step]?.maneuver.location : undefined;
    return loc ? [loc[1], loc[0]] : null;
  }, [steps, step, r]);

  const select = p.setSel;
  useEffect(() => map.current?.fit(), [p.sel]); // desktop re-frames on every route pick
  const closeSteps = () => { setSteps(false); setStep(-1); map.current?.fit(); };

  return (
    <div className="desk">
      <aside className="desk-panel">
        <header className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" fill="none" strokeLinecap="round" strokeWidth="2.6" aria-hidden="true">
            <path d="M16 29v-9" stroke="#E7EDF6" />
            <path d="M16 20c0-7-9-7-9-15" stroke="#9D8CFF" />
            <path d="M16 20V5" stroke="#E7EDF6" />
            <path d="M16 20c0-7 9-7 9-15" stroke="#6FD3FF" />
          </svg>
          <span>transPEAKtation</span>
        </header>

        <div className="desk-search">
          <Endpoints p={p} placeholders={['Choose starting point', 'Choose destination']} onPicked={() => { setSteps(false); setStep(-1); }} />
        </div>

        <div className="chips">
          <span className="chip on">Drive</span>
          <span className="chip">Leave now</span>
        </div>

        <div className="desk-body">
          {!p.to && !p.loading && (
            <>
              <div className="label">Recent</div>
              <div className="list">
                {RECENT.map(pl => <PlaceRow key={pl.label} place={pl} onPick={() => p.pick('to', pl)} />)}
              </div>
            </>
          )}

          {p.loading && <div className="status">Finding routes…</div>}

          {p.error && (
            <div className="error">
              <span>{p.error}</span>
              <button className="ghost-btn" onClick={p.retry}>Retry</button>
            </div>
          )}

          {hasRoutes && !steps && (
            <>
              <div className="title">Routes to {p.to?.label}</div>
              {p.routes.map((rt, i) => (
                <RouteCard key={i} route={rt} tag={routeTag(i, rt.dur, p.routes[0].dur)} selected={i === p.sel} onPick={() => select(i)} as="div">
                  {i === p.sel && (
                    <button className="pill-btn" onClick={e => { e.stopPropagation(); setSteps(true); setStep(-1); }}>Directions</button>
                  )}
                </RouteCard>
              ))}
            </>
          )}

          {hasRoutes && steps && r && (
            <>
              <div className="steps-head">
                <button className="round-btn" title="Back to routes" onClick={closeSteps}>←</button>
                <span className="title">Directions to {p.to?.label}</span>
              </div>
              <div className="summary">
                <div><b className="good">{mins(r.dur)} min</b><span>drive time</span></div>
                <div><b>{fmtTime(r.dur)}</b><span>arrival</span></div>
                <div><b>{fmtDist(r.dist)}</b><span>distance</span></div>
              </div>
              <div className="steps">
                {r.steps.map((st, i) => (
                  <button key={i} className={`step${i === step ? ' on' : ''}`} onClick={() => {
                    setStep(i);
                    map.current?.focus([st.maneuver.location[1], st.maneuver.location[0]]);
                  }}>
                    <span className="arrow">{stepArrow(st)}</span>
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
      </aside>

      <main className="desk-map">
        <MapView ref={map} routes={p.routes} sel={p.sel} from={p.from} to={p.to} marker={marker}
          onSelect={select} pad={{ topLeft: [60, 60], bottomRight: [60, 60] }} />
        <div className="map-ctrls">
          <button className="ctrl" title="Fit route" onClick={() => map.current?.fit()}><i className="dot" /></button>
          <div className="zoom">
            <button title="Zoom in" onClick={() => map.current?.zoomIn()}>+</button>
            <button title="Zoom out" onClick={() => map.current?.zoomOut()}>−</button>
          </div>
        </div>
      </main>
    </div>
  );
}
