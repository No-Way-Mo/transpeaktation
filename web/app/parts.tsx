'use client';
import type { KeyboardEvent, ReactNode } from 'react';
import { fmtDist, fmtTime, mins, type Place, type Route } from '@/lib/route.ts';
import type { useRoutePlanner } from '@/lib/use-route-planner.ts';

type Planner = ReturnType<typeof useRoutePlanner>;

/** From/to inputs, swap button, and the suggestion list. Layout comes from the parent's CSS. */
export function Endpoints({ p, placeholders, onPicked }: { p: Planner; placeholders: [string, string]; onPicked?(): void }) {
  return (
    <>
      <div className="endpoints">
        <div className="rail" aria-hidden="true"><i className="o" /><i className="line" /><i className="d" /></div>
        <div className="inputs">
          <input aria-label="Starting point" value={p.query.from} placeholder={placeholders[0]}
            onChange={e => p.onQuery('from', e.target.value)} onFocus={() => p.setActive('from')} onBlur={() => p.setActive(null)} />
          <div className="sep" />
          <input aria-label="Destination" value={p.query.to} placeholder={placeholders[1]}
            onChange={e => p.onQuery('to', e.target.value)} onFocus={() => p.setActive('to')} onBlur={() => p.setActive(null)} />
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

export function PlaceRow({ place, onPick }: { place: Place; onPick(): void }) {
  return (
    <button className="place" onClick={onPick}>
      <span className="badge"><i /></span>
      <span className="stack"><span className="name">{place.label}</span><span className="sub">{place.sub}</span></span>
    </button>
  );
}

export function RouteCard({ route, tag, selected, onPick, as = 'button', children }: {
  route: Route; tag: string; selected: boolean; onPick(): void; as?: 'button' | 'div'; children?: ReactNode;
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
        <span className="arrive"><span className="sub">Arrive</span><b>{fmtTime(route.dur)}</b></span>
      </span>
      {children}
    </Tag>
  );
}
