'use client';
import { useEffect, useRef, useState } from 'react';
import { fetchRoutes, ORIGIN, searchPlaces, type Place, type Route } from './route.ts';

type Field = 'from' | 'to';

/** From/to search, suggestions, and route alternatives. Layout-agnostic: desktop and mobile both use it. */
export function useRoutePlanner() {
  const [from, setFrom] = useState<Place | null>(ORIGIN);
  const [to, setTo] = useState<Place | null>(null);
  const [query, setQuery] = useState({ from: ORIGIN.label, to: '' });
  const [active, setActive] = useState<Field | null>(null);
  const [suggestions, setSuggestions] = useState<Place[]>([]);
  const [searching, setSearching] = useState(false);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [sel, setSel] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const searchTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const inflight = useRef<AbortController>(undefined);
  const latestQuery = useRef(query);
  latestQuery.current = query;

  // Re-route whenever both ends are set; abort the previous request so a slow response can't win.
  const route = async (a = from, b = to) => {
    inflight.current?.abort();
    setRoutes([]); setError('');
    if (!a || !b) return setLoading(false);
    const ctl = (inflight.current = new AbortController());
    setLoading(true);
    try {
      const rs = await fetchRoutes(a, b, ctl.signal);
      setRoutes(rs); setSel(0);
    } catch (e) {
      if (!ctl.signal.aborted) setError("Couldn't load routes.");
    } finally {
      if (!ctl.signal.aborted) setLoading(false);
    }
  };
  useEffect(() => () => { clearTimeout(searchTimer.current); inflight.current?.abort(); }, []);

  const onQuery = (field: Field, v: string) => {
    setQuery(q => ({ ...q, [field]: v }));
    setActive(field); setSuggestions([]); setSearching(!!v.trim());
    clearTimeout(searchTimer.current);
    if (!v.trim()) return;
    // Debounced: Nominatim's usage policy allows ~1 request/second.
    searchTimer.current = setTimeout(async () => {
      const res = await searchPlaces(v).catch(() => []);
      if (latestQuery.current[field] !== v) return; // user kept typing; a newer search owns the list
      setSuggestions(res); setSearching(false);
    }, 350);
  };

  const pick = (field: Field, p: Place) => {
    const nf = field === 'from' ? p : from, nt = field === 'to' ? p : to;
    setFrom(nf); setTo(nt);
    setQuery(q => ({ ...q, [field]: p.label }));
    setActive(null); setSuggestions([]); setSearching(false);
    route(nf, nt);
  };

  const swap = () => {
    setFrom(to); setTo(from);
    setQuery(q => ({ from: q.to, to: q.from }));
    route(to, from);
  };

  // Empty "from" box offers "Current location" back.
  const suggestList = active === 'from' && !query.from.trim() ? [ORIGIN] : suggestions;

  return {
    from, to, query, active, setActive, searching, routes, sel, setSel, loading, error,
    suggestions: suggestList,
    showSuggest: !!active && (suggestList.length > 0 || searching),
    onQuery, pick, swap, retry: () => route(),
    selected: routes[sel] as Route | undefined,
  };
}
