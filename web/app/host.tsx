'use client';
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { ANALYTICS_PREVIEW, CARD_LABELS, cardActions, CATEGORY_OPTIONS, DESCRIPTION_MAX, eventSpan, eventStatus, fmtAdmission, fmtPromotion, isWebLink,
  PROMOTION, PROMOTION_OPTIONS, REPORT_REASONS, TITLE_MAX, type CardAction, type Field, type ReportReason } from '@/lib/community.ts';
import { EVENT_KINDS, eventGlyph, eventKind, fmtEventTime, type MapEvent } from '@/lib/context.ts';
import type { LatLng } from '@/lib/route.ts';
import type { Hosting } from '@/lib/use-hosting.ts';
import { usePlaceSearch } from '@/lib/use-route-planner.ts';
import { Icon, type IconName } from './parts.tsx';

// Community events: ☰ → Add Event (form → "Event added" → Advertise placeholder), ☰ → My Events (created on this
// browser), ☰ → Saved Events (saved on this browser), and an event's details / Report / Delete. The same
// views sit in the bottom sheet on a phone and in the left panel on desktop, over a map that stays visible.
// Advertise only previews what's coming: nothing here pays, signs or changes an event's promotion (PROMOTION_OPTIONS).

/** Header + scrolling body (+ pinned footer) for every hosting view. Focus moves in when a view opens. */
function Frame({ title, sub, back, onClose, foot, children }: {
  title: string; sub?: string; back?: () => void; onClose(): void; foot?: ReactNode; children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null), id = useId();
  useEffect(() => box.current?.focus({ preventScroll: true }), [title]);
  return (
    <section className="host" ref={box} tabIndex={-1} aria-labelledby={id}>
      <header className="host-head">
        {back && <button className="close-btn" aria-label="Back" title="Back" onClick={back}><Icon name="back" size={16} /></button>}
        <span className="stack grow">
          <h2 id={id} className="host-title">{title}</h2>
          {sub && <span className="host-sub">{sub}</span>}
        </span>
        <button className="close-btn" aria-label="Close" title="Close" onClick={onClose}><Icon name="close" size={16} /></button>
      </header>
      <div className="host-body">{children}</div>
      {foot && <div className="host-foot">{foot}</div>}
    </section>
  );
}

/** Whichever hosting view is open. `onDirections`: plan a trip to the event (the route screen). `center`: the map
 *  centre, for Choose on map (desktop shows it here; a phone hides the sheet and shows PickBar instead). */
export function HostViews({ h, onDirections, center }: { h: Hosting; onDirections(ev: MapEvent): void; center(): LatLng | null }) {
  const v = h.view;
  if (!v) return null;
  if (v.kind === 'form') return <EventForm h={h} />;
  if (v.kind === 'pick') {
    return (
      <Frame title="Choose on map" back={h.backToForm} onClose={h.close} foot={<PickBar h={h} center={center} />}>
        <p className="host-lede">Drag or zoom the map until the pin in the middle is on your event’s spot.</p>
      </Frame>
    );
  }
  if (v.kind === 'created') return <Created h={h} ev={v.ev} edited={v.edited} />;
  if (v.kind === 'detail') return <EventDetail h={h} ev={v.ev} onDirections={onDirections} />;
  if (v.kind === 'boost') return <Boost h={h} ev={v.ev} />;
  if (v.kind === 'report') return <Report h={h} ev={v.ev} />;
  if (v.kind === 'delete') return <DeleteEvent h={h} ev={v.ev} />;
  if (v.kind === 'saved') return <SavedEvents h={h} onDirections={onDirections} />;
  return <MyEvents h={h} open={v.open} onDirections={onDirections} />;
}

// ---------- Add / edit ----------

function Err({ id, text }: { id: string; text?: string }) {
  return text ? <span id={id} className="field-error" role="alert">{text}</span> : null;
}

function EventForm({ h }: { h: Hosting }) {
  const { draft: d, errors: e, set } = h;
  const id = useId(), f = (k: Field | 'admission') => `${id}-${k}`;
  const err = (k: Field) => e[k] ? { 'aria-invalid': true, 'aria-describedby': f(k) } as const : {};
  const span = eventSpan(d.date, d.start, d.end);
  // A problem can sit above the fold while "Add to map" is pinned at the bottom: bring the first one into view.
  const form = useRef<HTMLFormElement>(null);
  const submit = async () => {
    await h.submit();
    requestAnimationFrame(() => {
      const bad = form.current?.querySelector<HTMLElement>('[aria-invalid="true"]') ?? form.current?.querySelector<HTMLElement>('.field-error');
      bad?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      if (bad?.matches('input, textarea')) bad.focus({ preventScroll: true });
    });
  };
  return (
    <Frame title={h.editing ? 'Edit event' : 'Add an event'} sub={h.editing ? undefined : 'Share what’s happening with people traveling nearby.'}
      onClose={h.close}
      foot={<>
        {h.saveError && <span className="field-error" role="alert">{h.saveError}</span>}
        <button className="start" disabled={h.saving} onClick={submit}>{h.saving ? 'Saving…' : h.editing ? 'Save changes' : 'Add to map'}</button>
      </>}>
      <form className="host-form" ref={form} noValidate onSubmit={ev => { ev.preventDefault(); submit(); }}>
        <label className="field">
          <span className="field-label">Event name</span>
          <input value={d.title} maxLength={TITLE_MAX} placeholder="e.g. Mission Night Market" enterKeyHint="next"
            onChange={ev => set({ title: ev.target.value })} {...err('title')} />
          <Err id={f('title')} text={e.title} />
        </label>

        <PlaceField h={h} errId={f('place')} />
        {d.pinned && (
          <label className="field">
            <span className="field-label">Place name</span>
            <input value={d.placeName} maxLength={160} placeholder="e.g. Dolores Park, north lawn" onChange={ev => set({ placeName: ev.target.value })} {...err('placeName')} />
            <Err id={f('placeName')} text={e.placeName} />
          </label>
        )}

        <div className="field-row">
          <label className="field date">
            <span className="field-label">Date</span>
            <input type="date" value={d.date} onChange={ev => set({ date: ev.target.value })} {...err('date')} />
          </label>
          <label className="field">
            <span className="field-label">Start time</span>
            <input type="time" step={300} value={d.start} onChange={ev => set({ start: ev.target.value })} {...err('start')} />
          </label>
          <label className="field">
            <span className="field-label">End time</span>
            <input type="time" step={300} value={d.end} onChange={ev => set({ end: ev.target.value })} {...err('end')} />
          </label>
        </div>
        <Err id={f('date')} text={e.date} /><Err id={f('start')} text={e.start} /><Err id={f('end')} text={e.end} />
        {!e.end && <span className="field-hint">San Francisco time.{span?.overnight ? ' Ends the next day.' : ''}</span>}

        <fieldset className="choice field" aria-describedby={e.category ? f('category') : undefined}>
          <legend className="field-label">Category</legend>
          <div className="cat-opts">
            {CATEGORY_OPTIONS.map(o => (
              <label key={o.value} className="cat-opt">
                <input type="radio" name={f('category')} value={o.value} checked={d.category === o.value} onChange={() => set({ category: o.value })} />
                <i className={`event-pin k-${o.kind}`} dangerouslySetInnerHTML={{ __html: eventGlyph(o.kind) }} />
                <span>{o.label}</span>
              </label>
            ))}
          </div>
          <Err id={f('category')} text={e.category} />
        </fieldset>

        <div className="field">
          <span className="field-label" id={f('admission')}>Admission</span>
          <div className="seg two" role="radiogroup" aria-labelledby={f('admission')}>
            {(['free', 'ticketed'] as const).map(a => (
              <button key={a} type="button" role="radio" aria-checked={d.admission === a} className={d.admission === a ? 'on' : ''}
                onClick={() => set({ admission: a })}>{a === 'free' ? 'Free' : 'Ticketed'}</button>
            ))}
          </div>
        </div>
        {d.admission === 'ticketed' && (
          <div className="field-row ticket">
            <label className="field grow">
              <span className="field-label">Ticket link</span>
              <input type="url" inputMode="url" value={d.ticketUrl} placeholder="https://" autoCapitalize="off" spellCheck={false}
                onChange={ev => set({ ticketUrl: ev.target.value })} {...err('ticketUrl')} />
            </label>
            <label className="field price">
              <span className="field-label">Price <i>(optional)</i></span>
              <input inputMode="decimal" value={d.ticketPrice} placeholder="$" onChange={ev => set({ ticketPrice: ev.target.value })} {...err('ticketPrice')} />
            </label>
          </div>
        )}
        <Err id={f('ticketUrl')} text={e.ticketUrl} /><Err id={f('ticketPrice')} text={e.ticketPrice} />
        {d.admission === 'ticketed' && !e.ticketUrl && <span className="field-hint">People buy tickets there; we don’t sell them.</span>}

        <label className="field">
          <span className="field-label">Description <i>(optional)</i></span>
          <textarea rows={3} maxLength={DESCRIPTION_MAX} value={d.description} placeholder="What should people know?"
            onChange={ev => set({ description: ev.target.value })} />
        </label>
        <label className="field">
          <span className="field-label">Image link <i>(optional)</i></span>
          <input type="url" inputMode="url" value={d.imageUrl} placeholder="https://" autoCapitalize="off" spellCheck={false}
            onChange={ev => set({ imageUrl: ev.target.value })} {...err('imageUrl')} />
          <Err id={f('imageUrl')} text={e.imageUrl} />
        </label>
        <button type="submit" hidden />
      </form>
    </Frame>
  );
}

/** Venue / address search (the app's own /places search), or a spot picked on the map. */
function PlaceField({ h, errId }: { h: Hosting; errId: string }) {
  const s = usePlaceSearch();
  const place = h.draft.place, error = h.errors.place;
  if (place) {
    return (
      <div className="field">
        <span className="field-label">Location</span>
        <div className="place-picked">
          <Icon name="pin" size={18} className="lead" />
          <span className="stack grow"><span className="name ellipsis">{place.label}</span>{place.sub && <span className="sub ellipsis">{place.sub}</span>}</span>
          <button type="button" className="link-btn" onClick={() => h.set({ place: null, pinned: false, placeName: '' })}>Change</button>
        </div>
      </div>
    );
  }
  return (
    <div className="field">
      <label className="field-label" htmlFor={`${errId}-q`}>Location</label>
      <div className="where-to">
        <Icon name="search" size={18} className="lead" />
        <input id={`${errId}-q`} value={s.q} placeholder="Search a venue or address" enterKeyHint="search"
          onChange={ev => s.run(ev.target.value)} aria-invalid={!!error} aria-describedby={error ? errId : undefined} />
        {s.q && <button type="button" className="clear-btn" aria-label="Clear" onClick={() => s.run('')}><Icon name="close" size={12} /></button>}
      </div>
      {s.q.trim() && (
        <div className="suggest" role="listbox" aria-label="Places">
          {s.results.map((pl, i) => (
            <button type="button" key={`${i}:${pl.lat},${pl.lon}`} role="option" aria-selected="false"
              onClick={() => { h.set({ place: pl, pinned: false, placeName: '' }); s.run(''); }}>
              <Icon name="pin" size={16} className="lead" />
              <span className="stack"><span className="name">{pl.label}</span><span className="sub">{pl.sub}</span></span>
            </button>
          ))}
          {s.searching && <div className="status">Searching…</div>}
          {!s.searching && !s.results.length && <div className="status">No places found in San Francisco.</div>}
        </div>
      )}
      <button type="button" className="map-pick-btn" onClick={h.pickOnMap}><Icon name="pin" size={16} />Choose on map</button>
      <Err id={errId} text={error} />
    </div>
  );
}

// ---------- after creating ----------

function Summary({ ev }: { ev: MapEvent }) {
  const kind = eventKind(ev);
  return (
    <div className="host-summary">
      <i className={`event-pin k-${kind}`} dangerouslySetInnerHTML={{ __html: eventGlyph(kind) }} />
      <span className="stack grow">
        <span className="name">{ev.name}</span>
        <span className="sub">{fmtEventTime(ev)}</span>
        {ev.venue && <span className="sub">{ev.venue}</span>}
      </span>
    </div>
  );
}

function Created({ h, ev, edited }: { h: Hosting; ev: MapEvent; edited: boolean }) {
  return (
    <Frame title={edited ? 'Changes saved' : 'Event added'} onClose={h.close}>
      <div className="host-done">
        <span className="done-check" aria-hidden="true"><Icon name="check" size={30} /></span>
        <p className="done-text">{edited ? 'Your event is updated on the map.' : 'Your event has been added to the map.'}</p>
        <Summary ev={ev} />
        <div className="done-actions">
          <button className="start" onClick={() => h.viewOnMap(ev)}>View on map</button>
          <button className="foot-alt" onClick={() => h.boost(ev)}><Icon name="bolt" size={18} />Advertise event</button>
          <button className="link-btn" onClick={h.close}>Maybe later</button>
        </div>
      </div>
    </Frame>
  );
}

const SOON = <span className="soon-pill">Coming soon</span>;
const PROMO_ICONS: Record<typeof PROMOTION_OPTIONS[number]['id'], IconName> = { boost: 'bolt', featured: 'star', route: 'car', local: 'pin' };

/** A preview of promotion to come: the options, each "Coming soon", and how it'll be paid. Nothing to pick, no prices,
 *  no reach numbers, no payment. Anyone can open it for any active event; it doesn't make them the event's host. */
function Boost({ h, ev }: { h: Hosting; ev: MapEvent }) {
  const note = useId(), own = h.isHost(ev);
  return (
    <Frame title={own ? 'Advertise your event' : 'Advertise this event'} sub="Reach more people traveling nearby." back={h.back} onClose={h.close}
      foot={<button className="start" disabled aria-describedby={note}>Coming soon</button>}>
      <div className="boost">
        <Summary ev={ev} />
        <ul className="promo-opts" aria-label="Promotion options">
          {PROMOTION_OPTIONS.map(o => (
            <li key={o.id} className="promo-opt" aria-disabled="true">
              <Icon name={PROMO_ICONS[o.id]} size={20} className="lead" />
              <span className="stack grow"><span className="promo-title">{o.title}</span><span className="sub">{o.detail}</span></span>
              {SOON}
            </li>
          ))}
        </ul>
        <div className="boost-pay">
          <span className="eyebrow">Payment</span>
          <span className="sol-chip"><b aria-hidden="true">◎</b> {PROMOTION.payment}</span>
        </div>
        <p id={note} className="field-hint center">Promotion payments will be available with Solana.</p>
      </div>
    </Frame>
  );
}

/** Host analytics to come: which numbers, locked. Never a value until there's real data behind it. */
function AnalyticsPreview() {
  return (
    <section className="analytics" aria-label="Event analytics, coming soon">
      <div className="analytics-head"><span className="eyebrow">Event analytics</span>{SOON}</div>
      <ul className="analytics-grid">
        {ANALYTICS_PREVIEW.map(m => <li key={m}><span className="sub">{m}</span><Icon name="lock" size={14} className="lead" /></li>)}
      </ul>
    </section>
  );
}

// ---------- event cards: View event + Directions, and a ⋯ menu ----------

const ACTION_ICONS: Record<CardAction, IconName> = {
  edit: 'edit', advertise: 'bolt', save: 'bookmark', unsave: 'bookmark', share: 'share', delete: 'trash', report: 'flag', reported: 'check',
};

/** ⋯ button + its menu (top right of a card) from lib/community.ts cardActions. Escape or a tap outside closes it;
 *  arrow keys move between items. */
function MoreMenu({ h, ev }: { h: Hosting; ev: MapEvent }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null), id = useId();
  const items = cardActions(ev, { hosted: h.isHost(ev), saved: h.savedIds.has(ev.id), reported: h.isReported(ev) });
  useEffect(() => {
    if (!open) return;
    wrap.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus();
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    addEventListener('pointerdown', close); addEventListener('keydown', close);
    return () => { removeEventListener('pointerdown', close); removeEventListener('keydown', close); };
  }, [open]);
  const arrows = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    e.preventDefault();
    const all = [...(wrap.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])], i = all.indexOf(document.activeElement as HTMLElement);
    all[(i + (e.key === 'ArrowDown' ? 1 : all.length - 1)) % all.length]?.focus();
  };
  return (
    <div className="more" ref={wrap}>
      <button className="more-btn" aria-label={`More for ${ev.name}`} title="More" aria-haspopup="menu" aria-expanded={open} aria-controls={id} onClick={() => setOpen(o => !o)}>
        <Icon name="more" size={18} />
      </button>
      {open && (
        <div className="more-pop" role="menu" id={id} onKeyDown={arrows}>
          {items.map(a => (
            <button key={a} role="menuitem" disabled={a === 'reported'} className={`more-item${a === 'delete' || a === 'report' ? ' danger' : ''}`}
              onClick={() => { setOpen(false); h.act(a, ev); }}>
              <Icon name={ACTION_ICONS[a]} size={17} className="lead" /><span>{CARD_LABELS[a]}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusTags({ h, ev }: { h: Hosting; ev: MapEvent }) {
  const status = eventStatus(ev);
  return (
    <div className="my-tags">
      <span className={`tag ${status === 'Happening now' ? 'tp' : status === 'Ended' ? 'off' : 'fast'}`}>{status}</span>
      {ev.community && <span className="tag off">{fmtAdmission(ev.community)}</span>}
      {h.isHost(ev) && <span className="tag off">{fmtPromotion(ev.community)}</span>}
    </div>
  );
}

/** One event in My Events / Saved Events: what it is, View event + Directions, everything else under ⋯. */
function EventCard({ h, ev, current, onDirections }: { h: Hosting; ev: MapEvent; current?: boolean; onDirections(ev: MapEvent): void }) {
  return (
    <li className="my-event" aria-current={current ? 'true' : undefined}>
      <div className="my-event-top"><Summary ev={ev} /><MoreMenu h={h} ev={ev} /></div>
      <StatusTags h={h} ev={ev} />
      <div className="my-actions">
        <button className="ghost-btn" onClick={() => h.viewEvent(ev)}>View event</button>
        <button className="ghost-btn" onClick={() => onDirections(ev)}>Directions</button>
      </div>
    </li>
  );
}

/** View event: everything we know about it, Directions into the app's own planner, and Show on map. */
function EventDetail({ h, ev, onDirections }: { h: Hosting; ev: MapEvent; onDirections(ev: MapEvent): void }) {
  const c = ev.community, source = ev.source === 'community' ? (h.isHost(ev) ? 'Added by you' : 'Added by its host')
    : ev.source === 'predicthq' ? 'PredictHQ' : ev.source === 'street_closures' ? 'DataSF street closures' : ev.source;
  return (
    <Frame title={ev.name} back={h.back} onClose={h.close}
      foot={<div className="detail-actions">
        <button className="start" onClick={() => onDirections(ev)}>Directions</button>
        {eventStatus(ev) !== 'Ended' && <button className="foot-alt" onClick={() => h.viewOnMap(ev)}>Show on map</button>}
      </div>}>
      <div className="detail-top"><StatusTags h={h} ev={ev} /><MoreMenu h={h} ev={ev} /></div>
      <dl className="detail-list">
        <div><dt>When</dt><dd>{fmtEventTime(ev)}</dd></div>
        {ev.venue && <div><dt>Where</dt><dd>{ev.venue}</dd></div>}
        <div><dt>Type</dt><dd>{EVENT_KINDS[eventKind(ev)].label}</dd></div>
        {c && <div><dt>Admission</dt><dd>{fmtAdmission(c)}{c.admission === 'ticketed' && c.ticket_url && isWebLink(c.ticket_url) &&
          <> · <a href={c.ticket_url} target="_blank" rel="noopener noreferrer">Tickets ↗</a></>}</dd></div>}
        {c?.description && <div><dt>About</dt><dd>{c.description}</dd></div>}
        <div><dt>Source</dt><dd>{source}</dd></div>
      </dl>
      {h.isHost(ev) && <AnalyticsPreview />}
    </Frame>
  );
}

function MyEvents({ h, open, onDirections }: { h: Hosting; open?: string; onDirections(ev: MapEvent): void }) {
  const { events, loading, error } = h.mine;
  return (
    <Frame title="My Events" sub="Events created on this browser appear here." onClose={h.close}>
      {loading && !events && <div className="status">Loading your events…</div>}
      {error && (
        <div className="error"><span>{error}</span><button className="ghost-btn" onClick={h.loadMine}>Retry</button></div>
      )}
      {events && !events.length && (
        <div className="empty">
          <Icon name="calendar" size={28} className="lead" />
          <b>No events yet.</b>
          <p>Add an event and put it on the map. Events you create on this browser show up here.</p>
          <button className="pill-btn" onClick={() => h.start('addEvent')}><Icon name="plus" size={16} />Add Event</button>
        </div>
      )}
      {!!events?.length && (
        <ul className="my-events">
          {events.map(ev => <EventCard key={ev.id} h={h} ev={ev} current={ev.id === open} onDirections={onDirections} />)}
        </ul>
      )}
    </Frame>
  );
}

function SavedEvents({ h, onDirections }: { h: Hosting; onDirections(ev: MapEvent): void }) {
  return (
    <Frame title="Saved Events" sub="Events you saved on this browser." onClose={h.close}>
      {!h.saved.length ? (
        <div className="empty">
          <Icon name="bookmark" size={28} className="lead" />
          <b>No saved events.</b>
          <p>Open any event’s ⋯ menu and choose Save event to keep it here.</p>
        </div>
      ) : (
        <ul className="my-events">
          {h.saved.map(ev => <EventCard key={ev.id} h={h} ev={ev} onDirections={onDirections} />)}
        </ul>
      )}
    </Frame>
  );
}

/** Report for review: a reason, optional details. It never hides or deletes the event. Not offered to its host. */
function Report({ h, ev }: { h: Hosting; ev: MapEvent }) {
  const [reason, setReason] = useState<ReportReason | ''>('');
  const [details, setDetails] = useState('');
  const name = useId(), sent = h.isReported(ev);
  return (
    <Frame title={sent ? 'Report sent' : 'Report event'} back={h.back} onClose={h.close}
      foot={sent ? <button className="start" onClick={h.back}>Done</button> : <>
        {h.actionError && <span className="field-error" role="alert">{h.actionError}</span>}
        <button className="start" disabled={!reason || h.busy} onClick={() => reason && h.sendReport(ev, reason, details)}>
          {h.busy ? 'Sending…' : 'Send report'}
        </button>
      </>}>
      <Summary ev={ev} />
      {sent ? (
        <p className="host-lede">Thanks. We’ll take a look. The event stays up while it’s checked.</p>
      ) : (
        <>
          <fieldset className="choice">
            <legend className="field-label">What’s wrong?</legend>
            <div className="choice-list">
              {REPORT_REASONS.map(r => (
                <label key={r.id} className="choice-row">
                  <input type="radio" name={name} value={r.id} checked={reason === r.id} onChange={() => setReason(r.id)} />
                  <span className="name grow">{r.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="field">
            <span className="field-label">Details <i>(optional)</i></span>
            <textarea rows={3} maxLength={500} value={details} onChange={e => setDetails(e.target.value)} placeholder="Anything that helps us check it" />
          </label>
          <p className="sub">Reports don’t include your name, device or location.</p>
        </>
      )}
    </Frame>
  );
}

function DeleteEvent({ h, ev }: { h: Hosting; ev: MapEvent }) {
  return (
    <Frame title="Delete event?" back={h.back} onClose={h.close}
      foot={<>
        {h.actionError && <span className="field-error" role="alert">{h.actionError}</span>}
        <button className="start danger" disabled={h.busy} onClick={() => h.confirmDelete(ev)}>{h.busy ? 'Deleting…' : 'Delete event'}</button>
        <button className="link-btn center" onClick={h.back}>Keep it</button>
      </>}>
      <Summary ev={ev} />
      <p className="host-lede">It comes off the map and out of My Events. This can’t be undone.</p>
    </Frame>
  );
}


// ---------- Choose on map ----------

/** The pin in the middle of the map while choosing a spot: its tip is the map centre. */
export function PickCross() {
  return (
    <div className="pick-cross" aria-hidden="true">
      <svg viewBox="0 0 28 36"><path className="body" d="M14 34.5C14 34.5 26.5 21.8 26.5 13.5a12.5 12.5 0 0 0-25 0C1.5 21.8 14 34.5 14 34.5Z" /><circle className="hole" cx="14" cy="13.5" r="4.75" /></svg>
    </div>
  );
}

/** Choose-on-map controls: phone bottom bar, or the desktop panel's footer. */
export function PickBar({ h, center, className = '' }: { h: Hosting; center(): LatLng | null; className?: string }) {
  return (
    <div className={`pick-bar ${className}`} role="group" aria-label="Choose on map">
      <span className="sub grow">Move the map until the pin is on the spot.</span>
      <button className="ghost-btn" onClick={h.backToForm}>Cancel</button>
      <button className="pill-btn" onClick={() => h.pickedAt(center())}>Use this spot</button>
    </div>
  );
}
