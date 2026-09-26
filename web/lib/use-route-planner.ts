'use client';
import { useEffect, useRef, useState } from 'react';
import { fetchRoutes, fmtWhen, mins, ORIGIN, searchPlaces, spokenTime, voiceNote, type Place, type Route, type VoiceIntent, type When } from './route.ts';
import { conditionWindow, eventWindow, fetchEvents, fetchRoadConditions, routeContext, tripSpan, type ContextData, type Span } from './context.ts';
import { transPeakPick } from './suggest.ts';

type Field = 'from' | 'to';
export type Screen = 'start' | 'search' | 'route';
type Trip = { note: string; leaveMin?: number }; // set when the trip came from a transPEAKtation suggestion
/** One route card: route `i` with the normal estimate or the transPEAKtation (event-aware) one. Times in epoch ms. */
export type Card = { i: number; tp: boolean; dur: number; leave: number; arrive: number };
const NOW: When = { mode: 'now', at: 0 };

/** Debounced place search. The latest text wins; slower, older responses are dropped. */
function usePlaceSearch() {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Place[]>([]);
  const [searching, setSearching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const latest = useRef('');
  useEffect(() => () => clearTimeout(timer.current), []);

  const run = (v: string) => {
    setQ(v); latest.current = v; setResults([]); setSearching(!!v.trim());
    clearTimeout(timer.current);
    if (!v.trim()) return;
    // 350 ms debounce: each lookup is a (quota-limited) Mapbox request.
    timer.current = setTimeout(async () => {
      const res = await searchPlaces(v).catch(() => []);
      if (latest.current !== v) return;
      setResults(res); setSearching(false);
    }, 350);
  };
  return { q, results, searching, run };
}

/** Ingested events + road conditions for a trip span. Refetches only when the (5-min snapped) windows change; a
 *  failed feed comes back as null so routing carries on without it. */
function useTripContext(span: Span): ContextData {
  const ev = eventWindow(span), cond = conditionWindow(span);
  const key = `${ev.from}-${ev.to}|${cond.from}-${cond.to}`;
  const [data, setData] = useState<ContextData>({ events: [], conditions: [], loading: true });
  useEffect(() => {
    const ctl = new AbortController();
    setData(d => ({ ...d, loading: true }));
    Promise.allSettled([fetchEvents(ev, ctl.signal), fetchRoadConditions(cond, ctl.signal)]).then(([e, c]) => {
      if (ctl.signal.aborted) return;
      setData({ events: e.status === 'fulfilled' ? e.value : null, conditions: c.status === 'fulfilled' ? c.value : null, loading: false });
    });
    return () => ctl.abort();
  }, [key]); // key encodes both windows
  return data;
}

/** Screens (start → search → route), searches, departure time, and route cards. Shared by desktop and mobile. */
export function useRoutePlanner() {
  const [screen, setScreen] = useState<Screen>('start');
  const [from, setFrom] = useState<Place | null>(ORIGIN);
  const [to, setTo] = useState<Place | null>(null);
  const [query, setQuery] = useState({ from: ORIGIN.label, to: '' });
  const [active, setActive] = useState<Field | null>(null);
  const search = usePlaceSearch();       // "Where to?" on the start/search screens
  const fieldSearch = usePlaceSearch();  // from/to boxes on the route screen
  const [trip, setTrip] = useState<Trip>({ note: '' });
  const [when, setWhenState] = useState<When>(NOW);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [choice, setChoice] = useState({ i: 0, tp: true }); // selected card; transPEAKtation's by default
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const inflight = useRef<AbortController>(undefined);
  useEffect(() => () => inflight.current?.abort(), []);

  // Abort the previous request so a slow response can't overwrite a newer trip.
  const route = async (a = from, b = to, w = when) => {
    inflight.current?.abort();
    setRoutes([]); setError('');
    if (!a || !b) return setLoading(false);
    const ctl = (inflight.current = new AbortController());
    setLoading(true);
    try {
      const rs = await fetchRoutes(a, b, w, ctl.signal);
      setRoutes(rs); setChoice({ i: 0, tp: true });
    } catch {
      if (!ctl.signal.aborted) setError("Couldn't load routes.");
    } finally {
      if (!ctl.signal.aborted) setLoading(false);
    }
  };

  /** Start/search screen → route screen for `dest`, from the current start point. */
  const go = (dest: Place, opts: Trip = { note: '' }) => {
    const f = from ?? ORIGIN;
    setFrom(f); setTo(dest);
    setQuery({ from: f.label, to: dest.label });
    setActive(null); search.run('');
    setTrip(opts);
    const w: When = opts.leaveMin ? { mode: 'depart', at: Date.now() + opts.leaveMin * 60000 } : NOW;
    setWhenState(w);
    setScreen('route');
    route(f, dest, w);
  };

  /** Voice request → route screen, with whatever it recognized (start, time). False if no destination was found. */
  const applyVoice = (v: VoiceIntent) => {
    const dest = v.destination?.place;
    if (!dest) return false;
    const f = v.origin?.place ?? from ?? ORIGIN, at = v.time && spokenTime(v.time);
    const w: When = at ? { mode: v.time_mode === 'arrive' ? 'arrive' : 'depart', at } : NOW;
    setFrom(f); setTo(dest);
    setQuery({ from: f.label, to: dest.label });
    setActive(null); search.run(''); fieldSearch.run('');
    setTrip({ note: voiceNote(v) });
    setWhenState(w);
    setScreen('route');
    route(f, dest, w);
    return true;
  };

  const goStart = () => {
    inflight.current?.abort();
    search.run(''); fieldSearch.run('');
    setTo(null); setQuery(q => ({ ...q, to: '' }));
    setRoutes([]); setError(''); setLoading(false); setActive(null);
    setTrip({ note: '' }); setWhenState(NOW);
    setScreen('start');
  };

  const focusField = (field: Field) => { setActive(field); fieldSearch.run(''); };
  const onQuery = (field: Field, v: string) => {
    setQuery(q => ({ ...q, [field]: v }));
    setActive(field); fieldSearch.run(v);
  };
  const pick = (field: Field, p: Place) => {
    const nf = field === 'from' ? p : from, nt = field === 'to' ? p : to;
    setFrom(nf); setTo(nt);
    setQuery(q => ({ ...q, [field]: p.label }));
    setActive(null); fieldSearch.run('');
    setTrip({ note: '' }); // hand-picked endpoint: the suggestion's advice no longer applies
    route(nf, nt);
  };
  const swap = () => {
    setFrom(to); setTo(from);
    setQuery(q => ({ from: q.to, to: q.from }));
    route(to, from);
  };
  const setWhen = (w: When) => { setWhenState(w); route(from, to, w); };

  // Departure per estimate: now, the chosen time, or (arrive-by) the chosen time minus that estimate.
  const now = Date.now();
  const leaveFor = (dur: number) => tripSpan(when, dur, now).from;
  // Trip span for event / road context: every route's leave → arrive, or just the departure before routes load.
  const spans = routes.map(r => tripSpan(when, r.dur, now));
  const fetchSpan: Span = spans.length
    ? { from: Math.min(...spans.map(s => s.from)), to: Math.max(...spans.map(s => s.to)) }
    : tripSpan(when, 0, now);
  const context = useTripContext(fetchSpan);
  // Each route is judged over its own leave → arrive, not the union used for fetching.
  const ctxFor = (r: Route | undefined) => r ? routeContext(r, context.events ?? [], context.conditions ?? [], tripSpan(when, r.dur, now)) : null;
  const tp = routes.length ? transPeakPick(routes, ctxFor(routes[0]), context) : null;
  const card = (i: number, isTp: boolean): Card => {
    const dur = isTp && tp ? tp.preds[i].dur : routes[i].dur, leave = leaveFor(dur);
    return { i, tp: isTp, dur, leave, arrive: leave + dur * 1000 };
  };
  const sel = choice.tp && tp ? tp.best : choice.i;
  /** Map taps pick that route's normal card, unless it's the route the selected transPEAKtation card shows. */
  const setSel = (i: number) => { if (!(choice.tp && i === sel)) setChoice({ i, tp: false }); };

  // Empty "from" box offers "Current location" back.
  const suggestions = active === 'from' && !query.from.trim() ? [ORIGIN] : fieldSearch.results;

  return {
    screen, setScreen, go, goStart, applyVoice,
    search, trip,
    from, to, query, active, setActive, focusField, onQuery, pick, swap,
    suggestions, searching: fieldSearch.searching,
    showSuggest: !!active && (suggestions.length > 0 || fieldSearch.searching),
    routes, sel, setSel, choice, setChoice, tp, card, loading, error, retry: () => route(),
    selected: routes[sel] as Route | undefined,
    selectedCard: routes.length ? card(sel, choice.tp) : undefined,
    when, setWhen,
    /** Ingested events in the trip's time window, for the map. Empty while loading or if the feed failed. */
    mapEvents: context.events ?? [],
    /** Events near / conditions on the selected route (null = no route yet). */
    selectedContext: ctxFor(routes[sel]),
    whenText: when.mode === 'now' ? 'Leave now' : `${when.mode === 'depart' ? 'Leave' : 'Arrive by'} ${fmtWhen(when.at)}`,
    /** "12 min" per route on the map, in whichever estimate (normal / transPEAKtation) is selected. */
    mapLabels: routes.map((_, i) => `${mins(card(i, choice.tp).dur)} min`),
  };
}
