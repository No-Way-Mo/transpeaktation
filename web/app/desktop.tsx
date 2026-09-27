'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { fmtDist, fmtWhen, mins, stepText, type LatLng } from '@/lib/route.ts';
import { useRoutePlanner } from '@/lib/use-route-planner.ts';
import { MAP_EXPERIMENT } from '@/lib/experiment.ts';
import { useMapPrefs } from '@/lib/use-map-prefs.ts';
import MapView, { type MapHandle } from './map-view.tsx';
import { AppBar, MapLayers, NavDialogs, useNav } from './menu.tsx';
import { Compass, Endpoints, EventLegend, Icon, RouteList, SearchResults, TripNote, TurnIcon, WhenPicker, WhereTo } from './parts.tsx';
import { RewardPanel } from './reward.tsx';

export default function Desktop() {
  const p = useRoutePlanner();
  const n = useNav(true);
  const { prefs } = useMapPrefs();
  const map = useRef<MapHandle>(null);
  const [steps, setSteps] = useState(false);
  const [step, setStep] = useState(-1);
  const r = p.selected, c = p.selectedCard;
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
      <AppBar n={n} />
      <div className="desk-main">
        <aside className="desk-panel">

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
                <span className="chip on"><Icon name="car" size={15} />Drive</span>
                <WhenPicker p={p} />
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
                      <button className="round-btn" title="New search" aria-label="New search" onClick={newSearch}><Icon name="back" size={18} /></button>
                      <span className="title">Routes to {p.to?.label}</span>
                    </div>
                    <TripNote note={p.trip.note} />
                    <RouteList p={p} onTrace={() => n.open('settings', 'privacy')} action={
                      <button className="pill-btn" onClick={e => { e.stopPropagation(); setSteps(true); setStep(-1); }}>Directions</button>
                    } />
                  </>
                )}

                {hasRoutes && steps && r && c && (
                  <>
                    <div className="steps-head">
                      <button className="round-btn" title="Back to routes" aria-label="Back to routes" onClick={closeSteps}><Icon name="back" size={18} /></button>
                      <span className="title grow">Directions to {p.to?.label}</span>
                      {p.tripId && (
                        <button className="pill-btn arrived-btn" disabled={p.hasArrived} onClick={p.arrived}>{p.hasArrived ? 'Arrived ✓' : 'Arrived'}</button>
                      )}
                    </div>
                    <div className="summary">
                      <div><b className="good">{mins(c.dur)} min</b><span>{c.tp ? 'transPEAKtation' : 'drive time'}</span></div>
                      <div><b>{fmtWhen(p.when.mode === 'arrive' ? c.leave : c.arrive)}</b><span>{p.when.mode === 'arrive' ? 'leave by' : 'arrival'}</span></div>
                      <div><b>{fmtDist(r.dist)}</b><span>distance</span></div>
                    </div>
                    {(p.earned || p.reward) && <RewardPanel p={p} />}
                    <div className="steps">
                      {r.steps.map((st, i) => (
                        <button key={i} className={`step${i === step ? ' on' : ''}`} onClick={() => {
                          setStep(i);
                          map.current?.focus([st.maneuver.location[1], st.maneuver.location[0]]);
                        }}>
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
            </>
          )}
        </aside>

        <main className="desk-map">
          <MapView ref={map} routes={p.routes} sel={p.sel} tp={p.choice.tp} labels={p.mapLabels} from={p.from} to={p.to} events={p.mapEvents} marker={marker}
            span={p.mapSpan} routeEvents={p.selectedContext?.events} onSelect={p.setSel} pad={{ topLeft: [60, 60], bottomRight: [60, 60] }} />
          {prefs.eventPins && MAP_EXPERIMENT !== 'snapmap' && <EventLegend events={p.mapEvents} />}
          <MapLayers className="desk-layers" />
          <div className="map-ctrls">
            <Compass onPress={() => map.current?.fit()} />
            <div className="zoom">
              <button title="Zoom in" aria-label="Zoom in" onClick={() => map.current?.zoomIn()}><Icon name="plus" /></button>
              <button title="Zoom out" aria-label="Zoom out" onClick={() => map.current?.zoomOut()}><Icon name="minus" /></button>
            </div>
          </div>
        </main>
      </div>
      <NavDialogs n={n} p={p} wide />
    </div>
  );
}
