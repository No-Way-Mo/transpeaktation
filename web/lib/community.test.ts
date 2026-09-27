import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { ANALYTICS_PREVIEW, CARD_LABELS, cardActions, CATEGORY_OPTIONS, createEvent, deleteEvent, draftFromEvent, emptyDraft, eventPlace, eventSpan,
  eventStatus, fetchMyEvents, fmtAdmission, hostKeys, isHost, isWebLink, lookupable, refreshSaved, REPORT_REASONS, reportedIds, reportEvent,
  PROMOTION, PROMOTION_OPTIONS, savedEvents, sharedEventId, shareLink, shareText, toggleSaved, updateEvent, validateDraft, withEvent, type Draft} from './community.ts';
import { eventKind, type MapEvent } from './context.ts';
import { API } from './route.ts';

// No browser here: a Map-backed localStorage and a recording fetch.
const store = new Map<string, string>();
(globalThis as { localStorage?: unknown }).localStorage = {
  getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k),
};
let calls: { url: string; method: string; body: unknown }[] = [];
let reply: (url: string) => unknown = () => ({});
globalThis.fetch = (async (url: string, init?: RequestInit) => {
  calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
  return new Response(JSON.stringify(reply(url)), { status: 200, headers: { 'Content-Type': 'application/json' } });
}) as typeof fetch;
beforeEach(() => { store.clear(); calls = []; });

const NOW = Date.parse('2026-09-27T19:00:00Z'); // noon in SF
const PARK = { label: 'Dolores Park', sub: 'Mission', lat: 37.7596, lon: -122.4269 };
const filled = (d: Partial<Draft> = {}): Draft => ({
  ...emptyDraft(NOW), title: 'Jazz Picnic', place: PARK, date: '2026-10-03', start: '18:00', end: '21:00', category: 'concert', ...d,
});
const EVENT: MapEvent = {
  id: 'evt_0123456789abcdef', name: 'Jazz Picnic', category: 'concert', venue: 'Dolores Park', lat: 37.7596, lon: -122.4269,
  start_time: '2026-10-04T01:00:00Z', end_time: '2026-10-04T04:00:00Z', source: 'community', status: 'active', road_closure_ids: [],
  community: { admission: 'ticketed', ticket_url: 'https://t.example/j', ticket_price: 15, description: 'Bring a blanket', image_url: null, promotion: { status: 'none' } },
};

test('categories are the map’s own event kinds, stored as the category that gives that pin', () => {
  assert.deepEqual(CATEGORY_OPTIONS.map(o => o.label), ['Music', 'Sports', 'Festival', 'Parade', 'Conference', 'Market', 'Community', 'Other']);
  for (const o of CATEGORY_OPTIONS.filter(o => o.kind !== 'other')) assert.equal(eventKind({ name: 'Untitled', category: o.value }), o.kind, o.value);
});

test('required fields: an empty form sends nothing and says what’s missing', () => {
  const { errors, body } = validateDraft({ ...emptyDraft(NOW), date: '', start: '', end: '' }, NOW);
  assert.equal(body, null);
  assert.deepEqual(Object.keys(errors).sort(), ['category', 'date', 'end', 'place', 'start', 'title']);
  assert.match(validateDraft(filled({ title: 'ab' }), NOW).errors.title!, /At least 3/);
});

test('a complete free event: SF wall-clock times to UTC, venue from the picked place, no ticket fields', () => {
  const { errors, body } = validateDraft(filled({ ticketUrl: 'https://leftover.example', ticketPrice: '9', description: '  ' }), NOW);
  assert.deepEqual(errors, {});
  assert.deepEqual(body, {
    title: 'Jazz Picnic', venue: 'Dolores Park', lat: 37.7596, lon: -122.4269,
    start_time: '2026-10-04T01:00:00.000Z', end_time: '2026-10-04T04:00:00.000Z', // 6-9 PM PDT
    category: 'concert', admission: 'free', ticket_url: null, ticket_price: null, description: null, image_url: null,
  });
});

test('ticketed: needs an http(s) ticket link; the price is optional', () => {
  assert.match(validateDraft(filled({ admission: 'ticketed' }), NOW).errors.ticketUrl!, /link/);
  assert.ok(validateDraft(filled({ admission: 'ticketed', ticketUrl: 'javascript:alert(1)' }), NOW).errors.ticketUrl);
  assert.ok(validateDraft(filled({ admission: 'ticketed', ticketUrl: 'https://t.example/j', ticketPrice: 'free-ish' }), NOW).errors.ticketPrice);
  const { body } = validateDraft(filled({ admission: 'ticketed', ticketUrl: ' https://t.example/j ', ticketPrice: '$15' }), NOW);
  assert.deepEqual([body?.admission, body?.ticket_url, body?.ticket_price], ['ticketed', 'https://t.example/j', 15]);
  assert.equal(validateDraft(filled({ admission: 'ticketed', ticketUrl: 'https://t.example/j' }), NOW).body?.ticket_price, null);
  assert.ok(!isWebLink('ftp://x.example/a') && !isWebLink('https://localhost') && isWebLink('http://a.example'));
});

test('an end time at or before the start is the next day; a time already over is refused', () => {
  const s = eventSpan('2026-10-03', '22:00', '01:00')!;
  assert.equal(s.overnight, true);
  assert.equal((s.to - s.from) / 36e5, 3);
  assert.match(validateDraft(filled({ date: '2026-09-26' }), NOW).errors.end!, /already passed/);
});

test('a spot chosen on the map needs a name, which becomes the venue', () => {
  const pinned = filled({ place: { label: 'Pinned location', sub: '37.76, -122.43', lat: 37.76, lon: -122.43 }, pinned: true });
  assert.ok(validateDraft(pinned, NOW).errors.placeName);
  assert.equal(validateDraft({ ...pinned, placeName: 'North lawn' }, NOW).body?.venue, 'North lawn');
});

test('editing starts from the event as saved and sends the same times back', () => {
  const d = draftFromEvent(EVENT);
  assert.deepEqual([d.date, d.start, d.end, d.admission, d.ticketUrl, d.ticketPrice], ['2026-10-03', '18:00', '21:00', 'ticketed', 'https://t.example/j', '15']);
  const { body } = validateDraft(d, NOW);
  assert.deepEqual([body?.start_time, body?.end_time, body?.venue], ['2026-10-04T01:00:00.000Z', '2026-10-04T04:00:00.000Z', 'Dolores Park']);
});

test('creating posts the event once and keeps its host key in this browser only', async () => {
  reply = () => ({ event: EVENT, host_key: 'secret-key-secret-key' });
  const ev = await createEvent(validateDraft(filled(), NOW).body!);
  assert.equal(ev.id, EVENT.id);
  assert.deepEqual(calls.map(c => [c.method, c.url]), [['POST', `${API}/community/events`]]);
  assert.deepEqual(hostKeys(), { [EVENT.id]: 'secret-key-secret-key' });
});

test('My Events asks only for the events this browser holds keys for; no keys, no request', async () => {
  assert.deepEqual(await fetchMyEvents(), []);
  assert.equal(calls.length, 0);
  store.set('tp-hosted-events', JSON.stringify({ [EVENT.id]: 'k1', junk: 5 }));
  reply = () => ({ events: [EVENT] });
  assert.deepEqual((await fetchMyEvents()).map(e => e.id), [EVENT.id]);
  assert.deepEqual(calls[0], { url: `${API}/community/events/mine`, method: 'POST', body: { keys: { [EVENT.id]: 'k1' } } });
});

test('editing sends the host key; without one it never calls the api', async () => {
  const body = validateDraft(filled(), NOW).body!;
  await assert.rejects(updateEvent(EVENT.id, body), /isn’t the host/);
  assert.equal(calls.length, 0);
  store.set('tp-hosted-events', JSON.stringify({ [EVENT.id]: 'k1' }));
  reply = () => ({ event: EVENT });
  await updateEvent(EVENT.id, body);
  assert.deepEqual([calls[0].method, calls[0].url, (calls[0].body as { host_key: string }).host_key], ['PUT', `${API}/community/events/${EVENT.id}`, 'k1']);
});

test('the host’s event joins the map’s events (fresh copy wins); status and admission wording', () => {
  const other = { ...EVENT, id: 'evt_other', community: null };
  assert.deepEqual(withEvent([other], null), [other]);
  assert.deepEqual(withEvent([other, { ...EVENT, name: 'old' }], EVENT).map(e => e.name), ['Jazz Picnic', 'Jazz Picnic']);
  assert.equal(withEvent([other, { ...EVENT, name: 'old' }], EVENT).length, 2);
  assert.equal(eventStatus(EVENT, Date.parse('2026-10-04T02:00:00Z')), 'Happening now');
  assert.equal(eventStatus(EVENT, Date.parse('2026-10-05T00:00:00Z')), 'Ended');
  assert.equal(fmtAdmission(EVENT.community), 'Ticketed · $15');
  assert.equal(fmtAdmission(null), 'Free');
});

test('boost is a placeholder: not available, nothing to pay', () => {
  assert.equal(PROMOTION.available, false);
  assert.equal(PROMOTION.payment, 'Solana');
  assert.deepEqual(PROMOTION_OPTIONS.map(o => o.title), ['Boost on map', 'Featured event', 'Route-aware promotion', 'Local sponsorship']);
  // previews only: no prices, reach or impression numbers anywhere in the options or analytics
  assert.doesNotMatch(JSON.stringify([PROMOTION_OPTIONS, ANALYTICS_PREVIEW]), /\d|\$|◎\s*\d|price|impression|reach \d/i);
  assert.deepEqual([...ANALYTICS_PREVIEW], ['Views', 'Saves', 'Directions', 'Ticket clicks']);
});

const EXTERNAL: MapEvent = { ...EVENT, id: 'evt_fedcba9876543210', name: 'Giants vs. Dodgers', source: 'predicthq', community: null };
const DATASF: MapEvent = { ...EVENT, id: 'street_closures:260001@2026-10-04T01:00:00Z', source: 'street_closures', community: null };

test('Save event / Unsave event: kept in this browser only, no request, survives junk in storage', () => {
  assert.deepEqual(savedEvents(), []);
  assert.deepEqual(toggleSaved(EVENT).map(e => e.id), [EVENT.id]);
  assert.deepEqual(toggleSaved(EXTERNAL).map(e => e.id), [EVENT.id, EXTERNAL.id]); // any event, not just community
  assert.deepEqual(toggleSaved(EVENT).map(e => e.id), [EXTERNAL.id]);
  store.set('tp-saved-events', '{"not":"a list"}');
  assert.deepEqual(savedEvents(), []);
  assert.equal(calls.length, 0);
});

test('Saved Events refresh: the api’s current copy wins, events it no longer lists drop off, closure events stay', () => {
  toggleSaved({ ...EVENT, name: 'old name' }); toggleSaved(EXTERNAL); toggleSaved(DATASF);
  const next = refreshSaved([{ ...EVENT, name: 'new name' }], new Set([EXTERNAL.id]));
  assert.deepEqual(next.map(e => e.name), ['new name', 'Jazz Picnic']);
  assert.deepEqual(savedEvents().map(e => e.id), [EVENT.id, DATASF.id]);
  assert.ok(lookupable(EVENT.id) && !lookupable(DATASF.id));
});

test('host controls need a community event AND this browser’s key for it; never the source alone', () => {
  assert.equal(isHost(EVENT, {}), false);                               // community, no key: not mine
  assert.equal(isHost(EVENT, { [EVENT.id]: 'k' }), true);
  assert.equal(isHost(EXTERNAL, { [EXTERNAL.id]: 'forged' }), false);   // a key under an ingested id changes nothing
  assert.equal(isHost(EVENT, new Set([EVENT.id])), true);
});

test('⋯ menu: my event = Edit, Advertise, Save, Share, Delete (no Report); anyone else’s = Save, Share, Advertise, Report', () => {
  const now = Date.parse('2026-10-01T00:00:00Z');
  assert.deepEqual(cardActions(EVENT, { hosted: true, saved: false, reported: false, now }), ['edit', 'advertise', 'save', 'share', 'delete']);
  assert.deepEqual(cardActions(EVENT, { hosted: false, saved: true, reported: false, now }), ['unsave', 'share', 'advertise', 'report']);
  assert.deepEqual(cardActions(EVENT, { hosted: false, saved: false, reported: true, now }), ['save', 'share', 'advertise', 'reported']);
  // anyone can advertise an external event, but it never gets Edit / Delete, even if the caller wrongly says "hosted"
  assert.deepEqual(cardActions(EXTERNAL, { hosted: true, saved: false, reported: false, now }), ['save', 'share', 'advertise', 'report']);
  // once it's over: nobody can advertise it, and its host can't edit it, but can still delete it
  const later = Date.parse('2026-10-05T00:00:00Z');
  assert.deepEqual(cardActions(EVENT, { hosted: true, saved: false, reported: false, now: later }), ['save', 'share', 'delete']);
  assert.deepEqual(cardActions(EXTERNAL, { hosted: false, saved: false, reported: false, now: later }), ['save', 'share', 'report']);
  assert.deepEqual([CARD_LABELS.save, CARD_LABELS.unsave, CARD_LABELS.report, CARD_LABELS.advertise], ['Save event', 'Unsave event', 'Report event', 'Advertise event']);
});

test('lifecycle from the event’s own times: upcoming, happening now, ended (no end time: the 3 h point-event rule)', () => {
  assert.equal(eventStatus(EVENT, Date.parse('2026-10-03T00:00:00Z')), 'Upcoming');
  assert.equal(eventStatus(EVENT, Date.parse('2026-10-04T02:00:00Z')), 'Happening now');
  assert.equal(eventStatus(EVENT, Date.parse('2026-10-04T04:00:00Z')), 'Ended');
  const open = { ...EVENT, end_time: null };
  assert.equal(eventStatus(open, Date.parse('2026-10-04T03:59:00Z')), 'Happening now');
  assert.equal(eventStatus(open, Date.parse('2026-10-04T04:01:00Z')), 'Ended');
});

test('Report: reason + details only (no id of any kind), remembered here just to show "Reported"', async () => {
  reply = () => ({ status: 'received' });
  await reportEvent(EXTERNAL.id, 'doesnt_exist', '  not happening ');
  await reportEvent(DATASF.id, 'other', '');
  assert.deepEqual(calls.map(c => [c.method, c.url, c.body]), [
    ['POST', `${API}/events/${EXTERNAL.id}/report`, { reason: 'doesnt_exist', details: 'not happening' }],
    ['POST', `${API}/events/${encodeURIComponent(DATASF.id)}/report`, { reason: 'other', details: null }],
  ]);
  assert.deepEqual(reportedIds(), [EXTERNAL.id, DATASF.id]);
  assert.deepEqual(REPORT_REASONS.map(r => r.label), ['Event doesn’t exist', 'Incorrect information', 'Spam', 'Inappropriate', 'Other']);
});

test('Delete sends the host key in the body (never the URL) and forgets it; without a key nothing is sent', async () => {
  await assert.rejects(deleteEvent(EVENT.id), /isn’t the host/);
  assert.equal(calls.length, 0);
  store.set('tp-hosted-events', JSON.stringify({ [EVENT.id]: 'secret-key-secret-key' }));
  reply = () => ({ status: 'deleted' });
  await deleteEvent(EVENT.id);
  assert.deepEqual([calls[0].url, calls[0].body], [`${API}/community/events/${EVENT.id}/delete`, { host_key: 'secret-key-secret-key' }]);
  assert.ok(!calls[0].url.includes('secret'));
  assert.deepEqual(hostKeys(), {});
});

test('share links open the app on the event and never carry a host key', () => {
  store.set('tp-hosted-events', JSON.stringify({ [EVENT.id]: 'secret-key-secret-key' }));
  const link = shareLink(EVENT, 'https://app.example');
  assert.equal(link, `https://app.example/?event=${EVENT.id}`);
  assert.ok(!link.includes('secret'));
  assert.equal(shareLink(DATASF, 'https://app.example'), 'https://app.example/'); // not look-up-able: just the app
  assert.equal(sharedEventId(`?event=${EVENT.id}`), EVENT.id);
  assert.equal(sharedEventId('?event=javascript:alert(1)'), null);
  assert.match(shareText(EVENT), /^Jazz Picnic · .+ · Dolores Park$/);
});

test('Directions hands the event’s own spot to the route planner', () => {
  assert.deepEqual(eventPlace(EVENT), { label: 'Dolores Park', sub: 'Jazz Picnic', lat: 37.7596, lon: -122.4269 });
});

test('an ended event stays in Saved Events (and a refresh keeps it: ended isn’t deleted)', () => {
  const past = { ...EVENT, start_time: '2026-09-01T01:00:00Z', end_time: '2026-09-01T04:00:00Z' };
  toggleSaved(past);
  const next = refreshSaved([past], new Set());
  assert.deepEqual(next.map(e => e.id), [EVENT.id]);
  assert.equal(eventStatus(next[0], NOW), 'Ended');
  // …and its ⋯ offers no Advertise, for anyone
  assert.ok(!cardActions(past, { hosted: false, saved: true, reported: false, now: NOW }).includes('advertise'));
  assert.ok(!cardActions(past, { hosted: true, saved: true, reported: false, now: NOW }).includes('advertise'));
});
