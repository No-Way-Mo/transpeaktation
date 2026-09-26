'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { fmtDist, mins, routeTag, stepArrow, stepText, type LatLng } from '@/lib/route.ts';
import { useRoutePlanner } from '@/lib/use-route-planner.ts';
import MapView, { type MapHandle } from './map-view.tsx';
import { Endpoints, Logo, RouteCard, SearchResults, TripNote, WhereTo } from './parts.tsx';

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

  useEffect(() => map.current?.fit(), [p.sel]); // desktop re-frames on every route pick
  const closeSteps = () => { setSteps(false); setStep(-1); map.current?.fit(); };
  const newSearch = () => { setSteps(false); setStep(-1); p.goStart(); };

  return (
    <div className="desk">
      <aside className="desk-panel">
        <header className="brand"><Logo /><span>transPEAKtation</span></header>

        {p.screen !== 'route' ? (
          <>
            <div className="desk-search">
              <WhereTo p={p} onFocus={() => p.setScreen('search')}>
                <button className="pill-btn" onClick={() => p.search.results[0] && p.go(p.search.results[0])}>Search</button>
              </WhereTo>
            </div>
            <div className="desk-body roomy"><SearchResults p={p} /></div>
          </>
        ) : (
          <>
            <div className="desk-search">
              <Endpoints p={p} placeholders={['Choose starting point', 'Choose destination']} onPicked={() => { setSteps(false); setStep(-1); }} />
            </div>

            <div className="chips">
              <span className="chip on">Drive</span>
              <span className="chip">{p.leaveText}</span>
            </div>

            <div className="desk-body">
              {p.loading && <div className="status">Finding routes…</div>}

              {p.error && (
                <div className="error">
                  <span>{p.error}</span>
                  <button className="ghost-btn" onClick={p.retry}>Retry</button>
                </div>
              )}

              {hasRoutes && !steps && (
                <>
                  <div className="steps-head">
                    <button className="round-btn" title="New search" aria-label="New search" onClick={newSearch}>←</button>
                    <span className="title">Routes to {p.to?.label}</span>
                  </div>
                  <TripNote note={p.trip.note} />
                  {p.routes.map((rt, i) => (
                    <RouteCard key={i} route={rt} tag={routeTag(i, rt.dur, p.routes[0].dur)} arrive={p.arrival(rt.dur)}
                      selected={i === p.sel} onPick={() => p.setSel(i)} as="div">
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
                    <button className="round-btn" title="Back to routes" aria-label="Back to routes" onClick={closeSteps}>←</button>
                    <span className="title">Directions to {p.to?.label}</span>
                  </div>
                  <div className="summary">
                    <div><b className="good">{mins(r.dur)} min</b><span>drive time</span></div>
                    <div><b>{p.arrival(r.dur)}</b><span>arrival</span></div>
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
          </>
        )}
      </aside>

      <main className="desk-map">
        <MapView ref={map} routes={p.routes} sel={p.sel} from={p.from} to={p.to} marker={marker}
          onSelect={p.setSel} pad={{ topLeft: [60, 60], bottomRight: [60, 60] }} />
        <div className="map-ctrls">
          <button className="ctrl" title="Fit route" aria-label="Fit route" onClick={() => map.current?.fit()}><i className="dot" /></button>
          <div className="zoom">
            <button title="Zoom in" aria-label="Zoom in" onClick={() => map.current?.zoomIn()}>+</button>
            <button title="Zoom out" aria-label="Zoom out" onClick={() => map.current?.zoomOut()}>−</button>
          </div>
        </div>
      </main>
    </div>
  );
}
