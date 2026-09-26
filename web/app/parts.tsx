'use client';
import type { KeyboardEvent, ReactNode } from 'react';
import { fmtDist, mins, RECENT, type Place, type Route } from '@/lib/route.ts';
import { smartSuggestions } from '@/lib/suggest.ts';
import type { useRoutePlanner } from '@/lib/use-route-planner.ts';

type Planner = ReturnType<typeof useRoutePlanner>;

export function Logo({ size = 26, stroke = 2.6, className }: { size?: number; stroke?: number; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" width={size} height={size} fill="none" strokeLinecap="round" strokeWidth={stroke} aria-hidden="true">
      <path d="M16 29v-9" stroke="#E7EDF6" />
      <path d="M16 20c0-7-9-7-9-15" stroke="#9D8CFF" />
      <path d="M16 20V5" stroke="#E7EDF6" />
      <path d="M16 20c0-7 9-7 9-15" stroke="#6FD3FF" />
    </svg>
  );
}

/** Recent places (empty query), or place results + transPEAKtation suggestions (typed query). */
export function SearchResults({ p }: { p: Planner }) {
  const { q, results, searching } = p.search;
  if (!q.trim()) {
    return (
      <div className="list">
        <div className="label">Recent</div>
        {RECENT.map(pl => <PlaceRow key={pl.label} place={pl} onPick={() => p.go(pl)} />)}
      </div>
    );
  }
  const smart = smartSuggestions(q, results);
  return (
    <>
      <div className="list">
        <div className="label">Suggestions</div>
        {results.map(pl => <PlaceRow key={`${pl.lat},${pl.lon}`} place={pl} onPick={() => p.go(pl)} plain />)}
        {searching && <div className="status">Searching…</div>}
        {!searching && !results.length && <div className="status">No places found in San Francisco.</div>}
      </div>
      {smart.length > 0 && (
        <div className="smart">
          <div className="smart-head"><Logo size={15} stroke={3} /><span>transPEAKtation suggestions</span></div>
          {smart.map(s => (
            <button key={s.title} className="smart-card" onClick={() => p.go(s.dest, { note: s.note, leaveMin: s.leaveMin })}>
              <span className="glyph">{s.glyph}</span>
              <span className="stack grow">
                <span className="smart-title">{s.title}</span>
                <span className="smart-sub">{s.sub}</span>
                <span className={`badge-pill${s.clear ? ' clear' : ''}`}>{s.badge}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}

/** Why this route: the note carried over from a transPEAKtation suggestion. */
export function TripNote({ note }: { note: string }) {
  return note ? <div className="trip-note"><Logo size={17} stroke={3} /><span>{note}</span></div> : null;
}

/** "Where to?" input shared by the desktop sidebar and the mobile search sheet. Enter picks the top result. */
export function WhereTo({ p, autoFocus, onFocus, children }: { p: Planner; autoFocus?: boolean; onFocus?(): void; children?: ReactNode }) {
  const top = p.search.results[0];
  return (
    <div className="where-to">
      <i className="ring" />
      <input aria-label="Where to?" placeholder="Where to?" value={p.search.q} autoFocus={autoFocus} enterKeyHint="go"
        onChange={e => { p.search.run(e.target.value); p.setScreen('search'); }} onFocus={onFocus}
        onKeyDown={e => { if (e.key === 'Enter' && top) p.go(top); }} />
      {p.search.q && <button className="clear-btn" aria-label="Clear" title="Clear" onClick={() => p.search.run('')}>×</button>}
      {children}
    </div>
  );
}

/** From/to inputs, swap button, and the suggestion list. Layout comes from the parent's CSS. */
export function Endpoints({ p, placeholders, onPicked }: { p: Planner; placeholders: [string, string]; onPicked?(): void }) {
  return (
    <>
      <div className="endpoints">
        <div className="rail" aria-hidden="true"><i className="o" /><i className="line" /><i className="d" /></div>
        <div className="inputs">
          <input aria-label="Starting point" value={p.query.from} placeholder={placeholders[0]}
            onChange={e => p.onQuery('from', e.target.value)} onFocus={() => p.focusField('from')} onBlur={() => p.setActive(null)} />
          <div className="sep" />
          <input aria-label="Destination" value={p.query.to} placeholder={placeholders[1]}
            onChange={e => p.onQuery('to', e.target.value)} onFocus={() => p.focusField('to')} onBlur={() => p.setActive(null)} />
        </div>
        <button className="swap" title="Swap start and destination" aria-label="Swap start and destination" onClick={p.swap}>⇅</button>
      </div>

      {p.showSuggest && (
        <div className="suggest" role="listbox">
          {p.suggestions.map(s => (
            // mousedown would blur the input (closing this list) before the click lands
            <button key={`${s.lat},${s.lon}`} role="option" aria-selected="false" onMouseDown={e => e.preventDefault()}
              onClick={() => { p.pick(p.active!, s); onPicked?.(); }}>
              <i className="dot-sm" />
              <span className="stack"><span className="name">{s.label}</span><span className="sub">{s.sub}</span></span>
            </button>
          ))}
          {p.searching && <div className="status">Searching…</div>}
        </div>
      )}
    </>
  );
}

export function PlaceRow({ place, onPick, plain }: { place: Place; onPick(): void; plain?: boolean }) {
  return (
    <button className="place" onClick={onPick}>
      <span className={`badge${plain ? ' plain' : ''}`}><i /></span>
      <span className="stack"><span className="name ellipsis">{place.label}</span><span className="sub ellipsis">{place.sub}</span></span>
    </button>
  );
}

export function RouteCard({ route, tag, arrive, selected, onPick, as = 'button', children }: {
  route: Route; tag: string; arrive: string; selected: boolean; onPick(): void; as?: 'button' | 'div'; children?: ReactNode;
}) {
  const Tag = as;
  return (
    <Tag className={`route${selected ? ' on' : ''}`} onClick={onPick} aria-pressed={selected}
      {...(as === 'div' ? { role: 'button', tabIndex: 0, onKeyDown: (e: KeyboardEvent) => e.key === 'Enter' && onPick() } : {})}>
      <span className="route-row">
        <span className="stack grow">
          <span className="eta">
            <b>{mins(route.dur)}</b><span className="unit">min</span>
            <span className={`tag${tag === 'Fastest' ? ' fast' : ''}`}>{tag}</span>
          </span>
          <span className="sub ellipsis">{route.summary ? `via ${route.summary}` : 'Direct route'} · {fmtDist(route.dist)}</span>
        </span>
        <span className="arrive"><span className="sub">Arrive</span><b>{arrive}</b></span>
      </span>
      {children}
    </Tag>
  );
}
