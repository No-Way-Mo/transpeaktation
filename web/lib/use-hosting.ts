'use client';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createEvent, deleteEvent, draftFromEvent, emptyDraft, fetchMyEvents, hostKeys, isHost, lookupable, lookupEvents, refreshSaved,
  reportedIds, reportEvent, savedEvents, sharedEventId, shareLink, shareText, toggleSaved, updateEvent, validateDraft,
  type CardAction, type Draft, type ReportReason } from './community.ts';
import type { MapEvent } from './context.ts';
import type { HostAction } from './nav.ts';
import type { LatLng } from './route.ts';

/** What the hosting sheet (mobile) / panel (desktop) shows; null = closed. `pick`: choosing the spot on the map, with
 *  the form kept. `back`: where that view's Back button returns. */
export type HostView =
  | { kind: 'form' }
  | { kind: 'pick' }
  | { kind: 'created'; ev: MapEvent; edited: boolean }
  | { kind: 'detail'; ev: MapEvent; back: HostView | null }
  | { kind: 'boost'; ev: MapEvent; back: HostView | null }
  | { kind: 'report'; ev: MapEvent; back: HostView | null }
  | { kind: 'delete'; ev: MapEvent; back: HostView | null }
  | { kind: 'mine'; open?: string }
  | { kind: 'saved' };
type Stacked = Extract<HostView, { back: HostView | null }>['kind'];

/** Community events state, shared by both layouts: Add Event / edit, success, event details, Advertise placeholder,
 *  Report, Delete, My Events (hosted here), Saved Events (saved here), and the event to bring into view on the map. */
export function useHosting() {
  const [view, setView] = useState<HostView | null>(null);
  const [draft, setDraft] = useState<Draft>(() => emptyDraft());
  const [editing, setEditing] = useState<MapEvent | null>(null);
  const [tried, setTried] = useState(false);          // show field errors only after the first submit
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [keys, setKeys] = useState<Record<string, string>>(hostKeys);
  const [mine, setMine] = useState<{ events: MapEvent[] | null; loading: boolean; error: string }>({ events: null, loading: false, error: '' });
  const [saved, setSaved] = useState<MapEvent[]>(savedEvents);
  const [reported, setReported] = useState<ReadonlySet<string>>(() => new Set(reportedIds()));
  const [busy, setBusy] = useState(false);            // report / delete in flight
  const [actionError, setActionError] = useState('');
  const [spotlight, setSpotlight] = useState<MapEvent | null>(null); // kept on the map even outside the trip window
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const [notice, setNotice] = useState('');           // short confirmation ("Link copied"), then gone
  const noticeTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const say = (text: string) => { clearTimeout(noticeTimer.current); setNotice(text); noticeTimer.current = setTimeout(() => setNotice(''), 2600); };

  const check = validateDraft(draft);
  const hostIds = useMemo(() => new Set(Object.keys(keys)), [keys]);
  const savedIds = useMemo(() => new Set(saved.map(e => e.id)), [saved]);
  const openForm = (d: Draft, ev: MapEvent | null) => {
    setDraft(d); setEditing(ev); setTried(false); setSaveError(''); setView({ kind: 'form' });
  };
  const loadMine = async () => {
    setMine(m => ({ ...m, loading: true, error: '' }));
    try { setMine({ events: await fetchMyEvents(hostKeys()), loading: false, error: '' }); }
    catch { setMine(m => ({ ...m, loading: false, error: 'Couldn’t load your events.' })); }
  };
  const openMine = (open?: string) => { setView({ kind: 'mine', open }); loadMine(); };
  /** Saved Events: show the saved copies at once, then swap in what the api lists now (drops deleted ones). */
  const openSaved = async () => {
    setView({ kind: 'saved' });
    const ids = savedEvents().map(e => e.id).filter(lookupable);
    if (!ids.length) return;
    try {
      const fresh = await lookupEvents(ids);
      setSaved(refreshSaved(fresh, new Set(ids.filter(id => !fresh.some(e => e.id === id)))));
    } catch { /* offline: the saved copies stay */ }
  };
  const push = (kind: Stacked, ev: MapEvent) => { setActionError(''); setView(v => ({ kind, ev, back: v }) as HostView); };
  const viewOnMap = (ev: MapEvent) => { setView(null); setSpotlight(ev); setFocus(f => ({ id: ev.id, n: (f?.n ?? 0) + 1 })); };
  const share = async (ev: MapEvent) => {
    const url = shareLink(ev, location.origin), text = shareText(ev);
    try {
      if (navigator.share) { await navigator.share({ title: ev.name, text, url }); return; }
      await navigator.clipboard.writeText(`${text}\n${url}`);
      say('Link copied');
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') say(`Couldn’t share. Link: ${url}`);
    }
  };

  // A shared link (?event=evt_…) opens the app on that event.
  useEffect(() => {
    const id = sharedEventId(location.search);
    if (!id) return;
    lookupEvents([id]).then(([ev]) => ev ? viewOnMap(ev) : say('That event isn’t listed any more.')).catch(() => {});
  }, []);

  return {
    view, draft, editing, saving, saveError, mine, saved, spotlight, focus, notice, busy, actionError,
    errors: tried ? check.errors : {},
    /** Ids of events this browser holds host keys for. Host controls also need source "community" (isHost). */
    hostIds, savedIds,
    isHost: (ev: MapEvent) => isHost(ev, hostIds),
    isReported: (ev: MapEvent) => reported.has(ev.id),
    /** ☰ → Add Event / My Events / Saved Events. */
    start: (a: HostAction) => a === 'addEvent' ? openForm(emptyDraft(), null) : a === 'myEvents' ? openMine() : openSaved(),
    edit: (ev: MapEvent) => openForm(draftFromEvent(ev), ev),
    set: (patch: Partial<Draft>) => { setDraft(d => ({ ...d, ...patch })); setSaveError(''); },
    /** Create (or save the edit). Field errors stop it; the api's answer or failure shows on the form. */
    submit: async () => {
      setTried(true);
      if (!check.body || saving) return;
      setSaving(true); setSaveError('');
      try {
        const ev = editing ? await updateEvent(editing.id, check.body) : await createEvent(check.body);
        setKeys(hostKeys()); setSpotlight(ev); setMine(m => ({ ...m, events: null }));
        setView({ kind: 'created', ev, edited: !!editing });
      } catch (e) {
        setSaveError(e instanceof Error && e.message && !/^HTTP \d/.test(e.message) ? `Couldn’t save: ${e.message}` : 'Couldn’t save your event. Try again.');
      } finally { setSaving(false); }
    },
    pickOnMap: () => setView({ kind: 'pick' }),
    /** The map centre becomes the event's spot; back to the form to name it. */
    pickedAt: (at: LatLng | null) => {
      if (at) setDraft(d => ({ ...d, place: { label: 'Pinned location', sub: `${at[0].toFixed(5)}, ${at[1].toFixed(5)}`, lat: at[0], lon: at[1] }, pinned: true }));
      setView({ kind: 'form' });
    },
    backToForm: () => setView({ kind: 'form' }),
    /** View event: the details sheet (from a map card, My Events or Saved Events). */
    viewEvent: (ev: MapEvent) => push('detail', ev),
    /** Close the sheet and bring `ev` into view on the map, card open. */
    viewOnMap,
    /** An item of an event's ⋯ menu. Host-only items are also re-checked here, not just hidden in the menu. */
    act: (a: CardAction, ev: MapEvent) => {
      const host = isHost(ev, hostIds);
      if (a === 'save' || a === 'unsave') { setSaved(toggleSaved(ev)); say(a === 'save' ? 'Saved to Saved Events' : 'Removed from Saved Events'); }
      else if (a === 'share') share(ev);
      else if (a === 'report' && !host) push('report', ev);
      else if (a === 'edit' && host) openForm(draftFromEvent(ev), ev);
      else if (a === 'advertise') push('boost', ev); // anyone, any event: visibility only, not ownership
      else if (a === 'delete' && host) push('delete', ev);
    },
    boost: (ev: MapEvent) => push('boost', ev),
    sendReport: async (ev: MapEvent, reason: ReportReason, details: string) => {
      if (busy || isHost(ev, hostIds)) return;
      setBusy(true); setActionError('');
      try { await reportEvent(ev.id, reason, details); setReported(new Set(reportedIds())); }
      catch { setActionError('Couldn’t send your report. Try again.'); }
      finally { setBusy(false); }
    },
    confirmDelete: async (ev: MapEvent) => {
      if (busy || !isHost(ev, hostIds)) return;
      setBusy(true); setActionError('');
      try {
        await deleteEvent(ev.id);
        setKeys(hostKeys());
        if (spotlight?.id === ev.id) setSpotlight(null);
        say('Event deleted'); openMine();
      } catch { setActionError('Couldn’t delete your event. Try again.'); }
      finally { setBusy(false); }
    },
    back: () => setView(v => v && 'back' in v ? v.back : null),
    openMine, openSaved, loadMine,
    close: () => setView(null),
  };
}
export type Hosting = ReturnType<typeof useHosting>;
