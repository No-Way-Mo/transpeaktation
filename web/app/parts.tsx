'use client';
import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { fmtDist, fmtWhen, fromPtInput, mins, ptInput, RECENT, REPLAY, routeTag, stepIcon, type Place, type Route, type Step, type When } from '@/lib/route.ts';
import { smartSuggestions } from '@/lib/suggest.ts';
import type { Card, useRoutePlanner } from '@/lib/use-route-planner.ts';
import { useVoice } from '@/lib/use-voice.ts';

type Planner = ReturnType<typeof useRoutePlanner>;

/** The fork mark: one road splitting into the normal route (blue) and transPEAKtation's (green). */
export function Logo({ size = 26, stroke = 2.6, className }: { size?: number; stroke?: number; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" width={size} height={size} fill="none" strokeLinecap="round" strokeWidth={stroke} aria-hidden="true">
      <path d="M16 29v-9M16 20V5" style={{ stroke: 'var(--ink)' }} />
      <path d="M16 20c0-7-9-7-9-15" style={{ stroke: 'var(--brand-strong)' }} />
      <path d="M16 20c0-7 9-7 9-15" style={{ stroke: 'var(--route)' }} />
    </svg>
  );
}

// One stroke icon set (24-unit grid, 2px round strokes) instead of text glyphs.
const ICONS = {
  close: 'M6 6l12 12M18 6L6 18',
  back: 'M15 5l-7 7 7 7',
  swap: 'M7 20V4M3 8l4-4 4 4M17 4v16M13 16l4 4 4-4',
  clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zM12 7v5l3 2',
  chevron: 'M6 9l6 6 6-6',
  plus: 'M12 5v14M5 12h14',
  minus: 'M5 12h14',
  arrow: 'M12 20V5M6 11l6-6 6 6',
  uturn: 'M8 20V10a4 4 0 0 1 8 0v8M12 14l4 4 4-4',
  flag: 'M5 21V4M5 4h11l-2 4 2 4H5',
  pin: 'M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4',
  car: 'M5 16V11l2-5h10l2 5v5M5 16h14M5 16v2M19 16v2M3 11h18M8 13.5h.01M16 13.5h.01',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
} as const;
export type IconName = keyof typeof ICONS;

export function Icon({ name, size = 20, rotate, className }: { name: IconName; size?: number; rotate?: number; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={rotate ? { transform: `rotate(${rotate}deg)` } : undefined}>
      <path d={ICONS[name]} />
    </svg>
  );
}

export function TurnIcon({ step, size = 18 }: { step: Step; size?: number }) {
  const { name, rotate } = stepIcon(step);
  return <Icon name={name} rotate={rotate} size={size} />;
}

const COMPASS_KEY = 'transpeaktation.compass';
type Pt = { x: number; y: number };
const clampTo = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Compass dial: north is always up on this map, so it doubles as the "recenter" button. `movable` lets a finger
 *  drag it anywhere on screen (a tap still recenters); the spot is remembered per device. */
export function Compass({ onPress, movable, className = '' }: { onPress(): void; movable?: boolean; className?: string }) {
  const [pos, setPos] = useState<Pt | null>(() => {
    if (!movable) return null;
    try { return JSON.parse(localStorage.getItem(COMPASS_KEY) ?? 'null'); } catch { return null; }
  });
  const drag = useRef<{ off: Pt; start: Pt; moved: boolean; at: Pt | null } | null>(null);
  const dragged = useRef(false);
  // A saved spot from a bigger screen/orientation must still land on-screen.
  const place = (p: Pt, size: number): Pt => ({ x: clampTo(p.x, 8, innerWidth - size - 8), y: clampTo(p.y, 8, innerHeight - size - 8) });
  const handlers = movable ? {
    onPointerDown(e: React.PointerEvent<HTMLButtonElement>) {
      const r = e.currentTarget.getBoundingClientRect();
      drag.current = { off: { x: e.clientX - r.left, y: e.clientY - r.top }, start: { x: e.clientX, y: e.clientY }, moved: false, at: null };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    onPointerMove(e: React.PointerEvent<HTMLButtonElement>) {
      const d = drag.current;
      if (!d || (!d.moved && Math.hypot(e.clientX - d.start.x, e.clientY - d.start.y) < 6)) return;
      d.moved = true;
      d.at = place({ x: e.clientX - d.off.x, y: e.clientY - d.off.y }, e.currentTarget.offsetWidth);
      setPos(d.at);
    },
    onPointerUp() {
      const d = drag.current;
      drag.current = null;
      dragged.current = !!d?.moved;
      if (d?.at) try { localStorage.setItem(COMPASS_KEY, JSON.stringify(d.at)); } catch { /* private mode: position just isn't kept */ }
    },
  } : {};
  const at = pos && typeof window !== 'undefined' ? place(pos, 48) : null;
  return (
    <button className={`compass${movable ? ' movable' : ''} ${className}`} aria-label="Recenter map. North is up." title="Recenter map"
      style={at ? { left: at.x, top: at.y, right: 'auto', bottom: 'auto' } : undefined}
      onClick={() => { if (dragged.current) { dragged.current = false; return; } onPress(); }} {...handlers}>
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <circle className="dial" cx="24" cy="24" r="21" />
        {[90, 180, 270].map(a => <path key={a} className="tick" d="M24 5.5v3.5" transform={`rotate(${a} 24 24)`} />)}
        {[45, 135, 225, 315].map(a => <path key={a} className="tick minor" d="M24 6v2" transform={`rotate(${a} 24 24)`} />)}
        <text className="north" x="24" y="14.5" textAnchor="middle">N</text>
        <path className="needle-n" d="M24 17l4.5 7h-9z" />
        <path className="needle-s" d="M24 36l-4.5-12h9z" />
        <circle className="hub" cx="24" cy="24" r="1.8" />
      </svg>
    </button>
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
  const smart = smartSuggestions(q, results, p.events);
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
              <span className="glyph"><Icon name={s.glyph} size={18} /></span>
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

/** Tap to say a trip ("Plan and book my ride to Chase Center at 6:30"); it opens the route screen. Errors show under it. */
export function MicButton({ p }: { p: Planner }) {
  const v = useVoice(p.applyVoice);
  return (
    <span className="mic-wrap">
      <button className={`mic ${v.state}`} title="Say where to go" aria-label={v.state === 'listening' ? 'Stop and send' : 'Say where to go'}
        aria-pressed={v.state === 'listening'} disabled={v.state === 'thinking'} onClick={v.toggle}>
        {v.state === 'thinking' ? <span className="mic-dots" aria-hidden="true">…</span> : <Icon name="mic" size={18} />}
      </button>
      {v.note && <span className="voice-note" role="status">{v.note}</span>}
    </span>
  );
}

/** "Where to?" input shared by the desktop sidebar and the mobile search sheet. Enter picks the top result. */
export function WhereTo({ p, autoFocus, onFocus, children }: { p: Planner; autoFocus?: boolean; onFocus?(): void; children?: ReactNode }) {
  const top = p.search.results[0];
  return (
    <div className="where-to">
      <Icon name="search" size={18} className="lead" />
      <input aria-label="Where to?" placeholder="Where to?" value={p.search.q} autoFocus={autoFocus} enterKeyHint="go"
        onChange={e => { p.search.run(e.target.value); p.setScreen('search'); }} onFocus={onFocus}
        onKeyDown={e => { if (e.key === 'Enter' && top) p.go(top); }} />
      {p.search.q && <button className="clear-btn" aria-label="Clear" title="Clear" onClick={() => p.search.run('')}><Icon name="close" size={12} /></button>}
      <MicButton p={p} />
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
        <button className="swap" title="Swap start and destination" aria-label="Swap start and destination" onClick={p.swap}><Icon name="swap" /></button>
        <MicButton p={p} />
      </div>

      {p.showSuggest && (
        <div className="suggest" role="listbox">
          {p.suggestions.map(s => (
            // mousedown would blur the input (closing this list) before the click lands
            <button key={`${s.lat},${s.lon}`} role="option" aria-selected="false" onMouseDown={e => e.preventDefault()}
              onClick={() => { p.pick(p.active!, s); onPicked?.(); }}>
              <Icon name="pin" size={16} className="lead" />
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
      <span className={`badge${plain ? ' plain' : ''}`}><Icon name={plain ? 'pin' : 'clock'} size={17} /></span>
      <span className="stack"><span className="name ellipsis">{place.label}</span><span className="sub ellipsis">{place.sub}</span></span>
    </button>
  );
}

/** The two route sections: transPEAKtation's event-aware pick, then the normal alternatives. `action` (e.g. a
 *  Directions button) goes inside the selected card. */
export function RouteList({ p, action }: { p: Planner; action?: ReactNode }) {
  if (!p.tp || !p.routes.length) return null;
  const { best, tag, note, advice } = p.tp, as = action ? 'div' : 'button';
  const fastest = p.routes[0].dur;
  return (
    <>
      <section className="route-sec" aria-label="transPEAKtation route">
        <div className="smart-head"><Logo size={15} stroke={3} /><span>transPEAKtation</span></div>
        <RouteCard route={p.routes[best]} card={p.card(best, true)} when={p.when} tag={tag} tone="tp"
          note={note} context={p.tpContext ?? undefined} selected={p.choice.tp} onPick={() => p.setChoice({ i: best, tp: true })} as={as}>
          {p.choice.tp && action}
        </RouteCard>
        {advice && <button className="pill-btn advice" onClick={p.applyAdvice}>{`Leave at ${fmtWhen(Date.parse(advice.depart_at))}`}</button>}
      </section>
      <section className="route-sec" aria-label="Normal routes">
        <div className="label">Normal</div>
        {p.routes.map((rt, i) => {
          const t = routeTag(i, rt.dur, fastest), on = !p.choice.tp && p.choice.i === i;
          return (
            <RouteCard key={i} route={rt} card={p.card(i, false)} when={p.when} tag={t} tone={i === 0 ? 'fast' : ''}
              selected={on} onPick={() => p.setChoice({ i, tp: false })} as={as}>
              {on && action}
            </RouteCard>
          );
        })}
      </section>
    </>
  );
}

const MODES: [When['mode'], string][] = [['now', 'Leave now'], ['depart', 'Leave at'], ['arrive', 'Arrive by']];

/** "Leave now ▾" chip that opens Leave now / Leave at / Arrive by + a date-time. Applies on Done (one re-route). */
export function WhenPicker({ p }: { p: Planner }) {
  const [draft, setDraft] = useState<When | null>(null);
  const soon = () => Math.ceil((Date.now() + 60000) / 9e5) * 9e5; // next quarter hour
  const setMode = (mode: When['mode']) => setDraft(d => ({ mode, at: d && d.at > Date.now() ? d.at : soon() }));
  return (
    <div className="when">
      <button className={`chip${p.when.mode !== 'now' ? ' on' : ''}`} aria-expanded={!!draft}
        onClick={() => setDraft(draft ? null : p.when)}>
        <Icon name="clock" size={15} /> {p.whenText} <Icon name="chevron" size={14} />
      </button>
      {draft && (
        <div className="when-pop">
          <div className="seg" role="radiogroup" aria-label="Departure">
            {MODES.map(([m, label]) => (
              <button key={m} role="radio" aria-checked={draft.mode === m} className={draft.mode === m ? 'on' : ''}
                onClick={() => setMode(m)}>{label}</button>
            ))}
          </div>
          {draft.mode !== 'now' && (
            <input type="datetime-local" aria-label={draft.mode === 'depart' ? 'Leave at' : 'Arrive by'} step={300}
              value={ptInput(draft.at)} min={REPLAY ? undefined : ptInput(Date.now())} max={ptInput(Date.now() + 30 * 864e5)}
              onChange={e => { const at = fromPtInput(e.target.value); if (at) setDraft({ ...draft, at }); }} />
          )}
          <div className="when-foot">
            {draft.mode !== 'now' && <span className="sub">San Francisco time. {draft.at < Date.now() ? 'Replay: uses the traffic and closures recorded then.' : 'Estimates use typical traffic for that time.'}</span>}
            <button className="pill-btn" onClick={() => { p.setWhen(draft); setDraft(null); }}>Done</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function RouteCard({ route, card, when, tag, tone, note, context, selected, onPick, as = 'button', children }: {
  route: Route; card: Card; when: When; tag: string; tone: 'fast' | 'tp' | ''; note?: string;
  context?: string;  // ingested events near / closures on this route (context.ts), when there are any
  selected: boolean; onPick(): void; as?: 'button' | 'div'; children?: ReactNode;
}) {
  const Tag = as;
  const [label, time] = when.mode === 'arrive' ? ['Leave by', card.leave] : ['Arrive', card.arrive];
  return (
    <Tag className={`route${selected ? ' on' : ''}${card.tp ? ' tp' : ''}`} onClick={onPick} aria-pressed={selected}
      {...(as === 'div' ? { role: 'button', tabIndex: 0, onKeyDown: (e: KeyboardEvent) => e.key === 'Enter' && onPick() } : {})}>
      <span className="route-row">
        <span className="stack grow">
          <span className="eta">
            <b>{mins(card.dur)}</b><span className="unit">min</span>
            <span className={`tag ${tone}`}>{tag}</span>
          </span>
          <span className="sub ellipsis">{route.summary ? `via ${route.summary}` : 'Direct route'} · {fmtDist(route.dist)}</span>
        </span>
        <span className="arrive"><span className="sub">{label}</span><b>{fmtWhen(time)}</b></span>
      </span>
      {note && <span className="route-note">{note}</span>}
      {context && <span className="route-note">{context}</span>}
      {children}
    </Tag>
  );
}
