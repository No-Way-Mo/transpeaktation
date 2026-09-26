'use client';
import { useEffect, useRef, useState } from 'react';
import { fetchRoutes, fmtTime, ORIGIN, searchPlaces, type Place, type Route } from './route.ts';

type Field = 'from' | 'to';
export type Screen = 'start' | 'search' | 'route';
type Trip = { note: string; leaveMin: number }; // set when the trip came from a transPEAKtation suggestion

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

/** Screens (start → search → route), searches, and route alternatives. Shared by desktop and mobile. */
export function useRoutePlanner() {
  const [screen, setScreen] = useState<Screen>('start');
  const [from, setFrom] = useState<Place | null>(ORIGIN);
  const [to, setTo] = useState<Place | null>(null);
  const [query, setQuery] = useState({ from: ORIGIN.label, to: '' });
  const [active, setActive] = useState<Field | null>(null);
  const search = usePlaceSearch();       // "Where to?" on the start/search screens
  const fieldSearch = usePlaceSearch();  // from/to boxes on the route screen
  const [trip, setTrip] = useState<Trip>({ note: '', leaveMin: 0 });
  const [routes, setRoutes] = useState<Route[]>([]);
  const [sel, setSel] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const inflight = useRef<AbortController>(undefined);
  useEffect(() => () => inflight.current?.abort(), []);

  // Abort the previous request so a slow response can't overwrite a newer trip.
  const route = async (a = from, b = to) => {
    inflight.current?.abort();
    setRoutes([]); setError('');
    if (!a || !b) return setLoading(false);
    const ctl = (inflight.current = new AbortController());
    setLoading(true);
    try {
      const rs = await fetchRoutes(a, b, ctl.signal);
      setRoutes(rs); setSel(0);
    } catch {
      if (!ctl.signal.aborted) setError("Couldn't load routes.");
    } finally {
      if (!ctl.signal.aborted) setLoading(false);
    }
  };

  /** Start/search screen → route screen for `dest`, from the current start point. */
  const go = (dest: Place, opts: Partial<Trip> = {}) => {
    const f = from ?? ORIGIN;
    setFrom(f); setTo(dest);
    setQuery({ from: f.label, to: dest.label });
    setActive(null); search.run('');
    setTrip({ note: opts.note ?? '', leaveMin: opts.leaveMin ?? 0 });
    setScreen('route');
    route(f, dest);
  };

  const goStart = () => {
    inflight.current?.abort();
    search.run(''); fieldSearch.run('');
    setTo(null); setQuery(q => ({ ...q, to: '' }));
    setRoutes([]); setError(''); setLoading(false); setActive(null);
    setTrip({ note: '', leaveMin: 0 });
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
    setTrip({ note: '', leaveMin: 0 }); // hand-picked endpoint: the suggestion's advice no longer applies
    route(nf, nt);
  };
  const swap = () => {
    setFrom(to); setTo(from);
    setQuery(q => ({ from: q.to, to: q.from }));
    route(to, from);
  };

  // Empty "from" box offers "Current location" back.
  const suggestions = active === 'from' && !query.from.trim() ? [ORIGIN] : fieldSearch.results;
  const leaveAt = trip.leaveMin ? fmtTime(trip.leaveMin * 60) : '';

  return {
    screen, setScreen, go, goStart,
    search, trip,
    from, to, query, active, setActive, focusField, onQuery, pick, swap,
    suggestions, searching: fieldSearch.searching,
    showSuggest: !!active && (suggestions.length > 0 || fieldSearch.searching),
    routes, sel, setSel, loading, error, retry: () => route(),
    selected: routes[sel] as Route | undefined,
    leaveText: leaveAt ? `Leave at ${leaveAt}` : 'Leave now',
    /** Clock time `sec` after departure (which is later than now for "leave at" suggestions). */
    arrival: (sec: number) => fmtTime(trip.leaveMin * 60 + sec),
  };
}
