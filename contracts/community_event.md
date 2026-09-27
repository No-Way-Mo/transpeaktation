# Community events (hosted by riders)

Anyone can put an event on the map from the web app (☰ → Add Event). They live in the same Mongo `events`
collection as ingested ones and come back through the same `/events` → map pin path, as `MapEvent`s with
`source: "community"` and a `community` block (`map_context.schema.json`).

## Mongo `events` doc (api/ writes; DESIGN.md §4 shape)
```js
{ _id: "evt_<sha1('community:<uuid>')[:16]>",
  title, category,                 // concert | sports | festival | parade | conference | market | community | other
  start_time, end_time,            // UTC; end required, after start, at most 7 days later
  end_is_predicted: false, all_day: false,
  location: Point, venue_id: null, venue_name,   // the place the host picked (search result or "Pinned location")
  capacity: null, attendance: null, status: "active", road_closure_ids: [],
  source_names: ["community"],
  sources: { community: {
    id,                            // uuid
    host_key_hash,                 // sha256 of the host key; never leaves the api
    admission: "free" | "ticketed", ticket_url, ticket_price, description, image_url,
    promotion: { status: "none" },
    created_at, updated_at } },
  schema_version: 1, first_seen_at, last_ingested_at }
```

## Ownership: per-event host key (no accounts, no device id)
There are no user accounts and no device id. `POST /community/events` returns a random `host_key` once; the browser
keeps `{event_id: host_key}` (web `lib/community.ts`) and the api stores only its SHA-256, compared in constant time
(`hmac.compare_digest`). Host controls (Edit, Advertise, Delete) need **both** `source: "community"` and this browser
holding that event's key: never the source alone, and an ingested event (PredictHQ, DataSF) can never be claimed.
Anything that changes an event or lists "My Events" sends the key **in the request body**:
`PUT /community/events/{id}`, `POST /community/events/{id}/delete`, `POST /community/events/mine`. Keys never go in a URL,
a share link, a log line or the map's event data, and `host_key_hash` never leaves the api. Lose the browser storage,
lose host access.

## Lifecycle
Upcoming / happening now / ended come from `start_time` / `end_time` (no end: the 3 h point-event rule). Ended events
drop off the map on their own (the `/events` time window) but stay in My Events. `DELETE` is soft: status `"deleted"`,
kept for reports, gone from the map, My Events and lookups.

## Saved Events, sharing, reports
- **Saved Events** is browser-only (web `lib/community.ts`: saved ids plus the event as it was saved). Opening it
  refreshes them through `POST /events/lookup {ids}` (events still listed, any source; DataSF-closure events aren't in
  `events`, so they keep their saved copy).
- **Share event**: `<app>/?event=<evt_id>` opens the app on that event (same lookup). No host key, ever.
- **Report event**: `POST /events/{id}/report {reason: doesnt_exist | incorrect_info | spam | inappropriate | other,
  details?}` on any event except your own (the UI never offers it on your own; the api can't tell, by design). Mongo
  `event_reports` stores `event_id`, `reason`, `details`, `created_at` only: no reporter identity or device id. A report
  never hides or deletes an event; they're for review.

## Scope
- Map, discovery and route-context notes only. The event-aware planner (`/plan`, api `Store.events_between`) ignores
  `source_names: community` whatever its promotion status.
- ml/ (`forecast/live.py`) reads `events` without a source filter; ml/ decides whether to skip `community`.
- ingest/ never touches these docs (its archive step only matches `sources.predicthq`).

## Promotion (next step; not built)
`promotion.status` is `"none"` for every event, and no endpoint can change it. Promotion is visibility only and is
kept separate from routing trust: paying to promote an event must never make it count for `/plan`.
Anyone can advertise any event that hasn't ended (the web ⋯ menu offers it on every event); paying for promotion never
grants host controls (Edit / Delete stay with the host key). Promotion of an ingested (non-community) event needs its
own record when built, since only community events carry a `sources.community.promotion` block.
Paid promotion (advertiser → transPEAKtation, in SOL) may set it `"active"` only after the api verifies on chain that the
transaction succeeded, paid the expected recipient the expected amount, and that its signature hasn't been used before
(store consumed signatures). Never on the client's word. This is a separate flow from route rewards
(transPEAKtation → rider, `rewards`).
