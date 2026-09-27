'use client';
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { fmtDist, fmtWhen, fromPtInput, longerThanItLooks, mins, ptInput, RECENT, REPLAY, routeTag, stepIcon, type Place, type Route, type Step, type When } from '@/lib/route.ts';
import { EVENT_KINDS, eventKind, type EventKind, type MapEvent } from '@/lib/context.ts';
import { eventGlyph } from './map-view.tsx';
import type { Card, useRoutePlanner } from '@/lib/use-route-planner.ts';
import { useVoice } from '@/lib/use-voice.ts';
import { dataPath, planStale, traceLine, type Privacy, type Stop } from '@/lib/privacy.ts';
import { usePrivacy } from '@/lib/use-privacy.ts';

type Planner = ReturnType<typeof useRoutePlanner>;

/** Map key for the event pins: only the kinds on the map right now, biggest draws first. */
export function EventLegend({ events }: { events: MapEvent[] }) {
  const on = new Set(events.map(eventKind));
  const kinds = (Object.keys(EVENT_KINDS) as EventKind[]).filter(k => on.has(k));
  if (!kinds.length) return null;
  return (
    <ul className="legend" aria-label="Event types on the map">
      {kinds.map(k => <li key={k}><i className={`event-pin k-${k}`} dangerouslySetInnerHTML={{ __html: eventGlyph(k) }} />{EVENT_KINDS[k].label}</li>)}
      <li className="area"><i />Est. crowd impact area</li>
    </ul>
  );
}

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
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20.5 14.1A8.5 8.5 0 1 1 9.9 3.5a6.6 6.6 0 0 0 10.6 10.6z',
  shield: 'M12 3l7 3v5.5c0 4.3-2.9 8-7 9.5-4.1-1.5-7-5.2-7-9.5V6l7-3zM9 12l2 2 4-4',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  menu: 'M4 7h16M4 12h16M4 17h16',
  layers: 'M12 3.5l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5',
  layersOff: 'M12 3.5l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5M3 2.5l18 20',
  star: 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z',
  history: 'M3.5 12a8.5 8.5 0 1 0 2.5-6M3.5 4v4h4M12 7.5V12l3 2',
  settings: 'M4 7h9M17 7h3M15 5v4M4 17h3M11 17h9M9 15v4M4 12h14',
  help: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zM9.6 9.4a2.5 2.5 0 1 1 3.6 2.3c-.7.3-1.2 1-1.2 1.7v.4M12 17h.01',
  info: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0zM12 11v6M12 7.5h.01',
  bell: 'M6 16v-5a6 6 0 0 1 12 0v5l2 2H4l2-2zM10 21h4',
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

/** Recent places (empty query), or place results (typed query). */
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
  return (
    <div className="list">
      <div className="label">Suggestions</div>
      {results.map(pl => <PlaceRow key={`${pl.lat},${pl.lon}`} place={pl} onPick={() => p.go(pl)} plain />)}
      {searching && <div className="status">Searching…</div>}
      {!searching && !results.length && <div className="status">No places found in San Francisco.</div>}
    </div>
  );
}

/** Why this route: the note carried over from a transPEAKtation suggestion. */
export function TripNote({ note }: { note: string }) {
  return note ? <div className="trip-note"><Logo size={17} stroke={3} /><span>{note}</span></div> : null;
}

/** Tap to say a trip ("Plan and book my ride to Chase Center at 6:30"); it opens the route screen. Errors show under it. */
export function MicButton({ p }: { p: Planner }) {
  const v = useVoice(p.applyVoice);
  if (!usePrivacy().privacy.voice) return null; // voice switched off: no mic, so no audio can reach ElevenLabs
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
export function RouteList({ p, action, onTrace }: { p: Planner; action?: ReactNode; onTrace(): void }) {
  if (!p.tp || !p.routes.length) return null;
  const { best, tag, note, advice } = p.tp, as = action ? 'div' : 'button';
  const fastest = p.routes[0].dur;
  return (
    <>
      <section className="route-sec" aria-label="transPEAKtation route">
        <div className="smart-head"><Logo size={15} stroke={3} /><span>transPEAKtation</span></div>
        <RouteCard route={p.routes[best]} card={p.card(best, true)} when={p.when} tag={tag} tone="tp"
          note={note} selected={p.choice.tp} onPick={() => p.setChoice({ i: best, tp: true })} as={as}>
          {p.choice.tp && action}
        </RouteCard>
        {p.trace && (
          <button className="trace-strip" aria-label={`AI and privacy for this trip: ${traceLine(p.trace.data)}`} onClick={onTrace}>
            <Icon name="shield" size={16} className="lead" /><span className="grow">{traceLine(p.trace.data)}</span><Icon name="chevron" size={14} rotate={-90} className="lead" />
          </button>
        )}
        {advice && <button className="pill-btn advice" onClick={p.applyAdvice}>{`Leave at ${fmtWhen(Date.parse(advice.depart_at))}`}</button>}
      </section>
      <section className="route-sec" aria-label="Normal routes">
        <div className="label">Normal</div>
        {p.routes.map((rt, i) => {
          if (rt.by === 'ml') return null; // ml/'s own route only appears as the transPEAKtation pick
          const pred = p.tp?.preds[i], longer = longerThanItLooks(pred), on = !p.choice.tp && p.choice.i === i;
          return (
            <RouteCard key={i} route={rt} card={p.card(i, false)} when={p.when} tag={longer ?? routeTag(i, rt.dur, fastest)}
              tone={i === 0 && !longer ? 'fast' : ''} note={pred?.note ?? undefined}
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

export function RouteCard({ route, card, when, tag, tone, note, selected, onPick, as = 'button', children }: {
  route: Route; card: Card; when: When; tag: string; tone: 'fast' | 'tp' | ''; note?: string;
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
      {children}
    </Tag>
  );
}

const SWITCHES: { key: keyof Privacy; label: string; detail: string }[] = [
  { key: 'saveTrips', label: 'Save my trips',
    detail: 'Keeps an area-level record of each trip (no exact start or end, no name or device ID) so we can forecast crowds. Off: nothing is written.' },
  { key: 'aiText', label: 'AI-written explanations',
    detail: 'Google Gemini words why the normal routes are slower, from trip facts, never addresses. Off: a built-in sentence, and nothing is sent to Google.' },
  { key: 'voice', label: 'Voice requests',
    detail: 'Your clip goes to ElevenLabs to become text; we don’t keep the audio. Off: the mic button is hidden.' },
];

/** One switch row (the whole row is the control). `status` = can't be switched on yet: disabled, reads as off, and
 *  says why in words, not just by fading. */
export function Toggle({ label, detail, on, onChange, status }: { label: string; detail: string; on: boolean; onChange(v: boolean): void; status?: string }) {
  const id = useId();
  return (
    <button className="aip-switch" role="switch" aria-checked={status ? false : on} aria-labelledby={`${id}l`} aria-describedby={`${id}d`}
      disabled={!!status} onClick={() => onChange(!on)}>
      <span className="stack grow">
        <span className="switch-head"><span id={`${id}l`} className="name">{label}</span>{status && <span className="tag off">{status}</span>}</span>
        <span id={`${id}d`} className="sub">{detail}</span>
      </span>
      {!status && <span className="switch" aria-hidden="true"><i /></span>}
    </button>
  );
}

/** Where a trip's data went: the same dotted rail as the from/to box, one stop per service or model. */
function DataPath({ stops }: { stops: Stop[] }) {
  return (
    <ol className="trace">
      {stops.map(s => (
        <li key={s.who + s.did} className={`stop${s.off ? ' off' : s.outside ? ' out' : s.ai ? ' ai' : ''}`}>
          <i className="dot" aria-hidden="true" />
          <span className="stack">
            <span className="stop-head">
              <b>{s.who}</b>
              {s.ai && <span className="tag fast">AI</span>}
              {s.outside && <span className="tag">Leaves our servers</span>}
              {s.off && <span className="tag off">Off</span>}
            </span>
            <span className="stop-did">{s.did}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

const shown = (v: unknown) => typeof v === 'string' ? v : JSON.stringify(v);

/** Settings → AI & Privacy: this trip's data path, the switches, and what is and isn't kept. */
export function AiPrivacy({ p }: { p: Planner }) {
  const { privacy, set } = usePrivacy();
  const t = p.trace, record = t?.data.trip_record;
  return (
    <div className="aip">
      <p className="aip-lede">Every service and model that touches your trip, and the switches that control them.</p>

      <section className="aip-sec" aria-labelledby="aip-trip">
        <h3 id="aip-trip" className="aip-h">{t ? `Where your trip to ${p.to?.label ?? 'there'} went` : 'Where your trip goes'}</h3>
        {t ? <DataPath stops={dataPath(t.data, t.source)} /> : p.loading ? <div className="status">Finding routes…</div> : (
          <p className="aip-empty">Plan a route and its path shows up here, stop by stop: the map service, our event and traffic data, whatever picked the route, whoever wrote the explanation, and what was saved.</p>
        )}
        {record && (
          <details className="aip-record">
            <summary>Exactly what was saved <span className="sub">{Object.keys(record).length} fields</span></summary>
            <dl>{Object.entries(record).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{shown(v)}</dd></div>)}</dl>
          </details>
        )}
      </section>

      <section className="aip-sec" aria-labelledby="aip-controls">
        <h3 id="aip-controls" className="aip-h">Your controls</h3>
        <div className="aip-switches">
          {SWITCHES.map(s => <Toggle key={s.key} label={s.label} detail={s.detail} on={privacy[s.key]} onChange={v => set(s.key, v)} />)}
        </div>
        {t && planStale(t.used, privacy) && (
          <div className="aip-stale" role="status">
            <span>This trip was planned with your old settings.</span>
            <button className="pill-btn" onClick={p.retry}>Re-plan it</button>
          </div>
        )}
        <p className="sub aip-foot">Kept on this device only. There are no accounts.</p>
      </section>

      <section className="aip-sec" aria-labelledby="aip-keep">
        <h3 id="aip-keep" className="aip-h">What we keep</h3>
        <ul className="aip-keep">
          <li><Icon name="check" size={16} className="yes" />Trips, if saving is on: start and end rounded to ~100 m, the roads used minus a few blocks at each end, the time, and which route won.</li>
          <li><Icon name="check" size={16} className="yes" />These switches, your theme and map choices, and (on a phone) where you dragged the compass, in this browser.</li>
          <li><Icon name="close" size={16} className="no" />Your name, email, account or device ID.</li>
          <li><Icon name="close" size={16} className="no" />Exact addresses or a location history.</li>
          <li><Icon name="close" size={16} className="no" />Voice recordings.</li>
        </ul>
        <p className="sub aip-foot">Saved trips aren’t linked to you, so nobody can look up or delete “your” trips later. To keep one out, turn saving off before you plan it.</p>
      </section>
    </div>
  );
}
