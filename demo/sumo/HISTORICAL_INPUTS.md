# Historical July 4 inputs

The target window is **July 4, 2026 20:00–22:00 America/Los_Angeles**, or
**July 5, 2026 03:00–05:00 UTC**. These commands fetch or inspect inputs only. They do not
run SUMO and do not write MongoDB or Tiger.

## DataSF planned closures and permits

From the repository root, run the existing historical worker in dry-run mode:

```sh
PYTHONPATH=ingest python3 -m worker backfill --date 2026-07-04 --dry-run
```

It keeps raw snapshots under `ingest/data/backfill/2026-07-04/` and reports what the
incident worker would write. The snapshot is a plan/permit history, not observed speeds.
The command is safe to repeat; the source files are ignored by git.

The run used while preparing this kit returned 4,628 street-closure rows, 9,536 street-use
permit rows, and 2,594 excavation rows. Eight closure rows overlapped 20:00–22:00 PDT:
seven `some-lanes-closed` special traffic permits and one `all-lanes-closed` Claude Lane
shared-space record. There was no DataSF `Special Event` row in that interval, so this
snapshot alone cannot describe the fireworks crowd controls.

## PredictHQ event history

The normal `predicthq_events` pull remains yesterday through 30 days ahead. For a deliberate
historical query, put `PREDICTHQ_TOKEN` in the local `ingest/.env` and use the explicit
window arguments added to the existing fetcher. The output directory is timestamped so a
new pull never overwrites an earlier snapshot:

```sh
PYTHONPATH=ingest python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

from datasf.client import load_dotenv
from pull import ENV_FILE
from pull.feeds import predicthq_events

load_dotenv(ENV_FILE)
out = Path("ingest/data/historical/2026-07-04") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out.mkdir(parents=True, exist_ok=False)
records, meta = predicthq_events(
    active_gte="2026-07-04",
    active_lte="2026-07-05",
)
(out / "predicthq_events.json").write_text(json.dumps({
    "source": "predicthq_events",
    "pulled_at": datetime.now(timezone.utc).isoformat(),
    "count": len(records),
    "meta": meta,
    "records": records,
}, indent=2, default=str), encoding="utf-8")
for row in sorted(records, key=lambda r: (r.get("phq_attendance") or -1, r.get("rank") or -1), reverse=True)[:20]:
    print(json.dumps({k: row.get(k) for k in (
        "title", "category", "start", "end", "location", "phq_attendance", "rank", "local_rank"
    )}, default=str))
print(f"saved {len(records)} records to {out}")
PY
```

PredictHQ returns expected attendance/rank and event metadata, not a measured footfall
count. A response can also be empty when the subscription does not include that historical
window or location; retain the response metadata with the snapshot.

The credentialed pull used here returned 146 records in three pages with no truncation. Thirty
events overlap the target window; the largest is **Fourth of July fireworks on Golden Gate
Bridge**, with PredictHQ expected attendance 300,000, rank 100, starting at 21:30 PDT. The
full response and the overlap-only selection are retained under the timestamped pull directory
in `ingest/data/historical/2026-07-04/`.

## 511 archived traffic events

With `SF511_API_KEY` in `ingest/.env`, retrieve the provider's archived traffic-event
records with its `in_effect_on` UTC window filter, then inspect the returned schedules
locally. This is an incident/closure feed, not a continuous speed history:

```sh
PYTHONPATH=ingest python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

from datasf.client import load_dotenv
from pull import ENV_FILE
from pull.feeds import sf511_traffic_events

load_dotenv(ENV_FILE)
out = Path("ingest/data/historical/2026-07-04") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out.mkdir(parents=True, exist_ok=False)
window = "2026-07-05T03:00:00Z,2026-07-05T05:00:00Z"
records, meta = sf511_traffic_events(
    status="archived", in_effect_on=window, max_pages=5,
)
(out / "sf511_traffic_events.json").write_text(json.dumps({
    "source": "sf511_traffic_events",
    "pulled_at": datetime.now(timezone.utc).isoformat(),
    "window_utc": window,
    "count": len(records),
    "meta": meta,
    "records": records,
}, indent=2, default=str), encoding="utf-8")
print(f"saved {len(records)} archived records to {out}")
PY
```

The unfiltered archived request returned 499 recent records from August 26–27, not July 4.
The date-filtered request returned zero records. This means the provider archive currently
does not expose a matching July 4 incident in this token's result set; it does not prove that
the roads were incident-free. Keep the raw response and the filter window in the run
provenance. 511's separate WZDx endpoint returned 552 current features when requested with
`historic=2026-07`; 133 feature schedules overlap the target window, including seven SFMTA
(`SF-2`) work-zone records. Its feed update timestamp was September 26, 2026, so those are
planned-closure evidence, not a historical traffic snapshot.

To save that WZDx response for later inspection without writing a database, use the existing
HTTP helper:

```sh
PYTHONPATH=ingest python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

from datasf.client import load_dotenv
from pull import ENV_FILE
from pull.feeds import _511

load_dotenv(ENV_FILE)
now = datetime.now(timezone.utc)
out = Path("ingest/data/historical/2026-07-04") / (now.strftime("%Y%m%dT%H%M%SZ") + "-sf511-wzdx")
out.mkdir(parents=True, exist_ok=False)
data = _511("/traffic/wzdx", operator_id="RG", historic="2026-07")
(out / "wzdx.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
print(f"saved {len(data.get('features', []))} features to {out}")
PY
```

## Existing stores

To prove whether measured traffic exists for the target window, use the Tiger CLI in
read-only mode:

```sh
tiger db query dp0coukufh --read-only -o json -c \
  "SELECT source, count(*) AS rows, min(time) AS first_time, max(time) AS last_time
   FROM traffic_metrics
   WHERE time >= TIMESTAMPTZ '2026-07-05 03:00:00+00'
     AND time <  TIMESTAMPTZ '2026-07-05 05:00:00+00'
   GROUP BY source ORDER BY source"
```

If PredictHQ was already ingested into Mongo, this read-only query ranks stored event
attendance for the window:

```sh
mongosh "$MONGODB_URI" --quiet --eval '
db.events.find({start_time: {$lt: ISODate("2026-07-05T05:00:00Z")},
                end_time: {$gte: ISODate("2026-07-05T03:00:00Z")}},
               {title:1, venue_name:1, start_time:1, end_time:1, attendance:1, rank:1, location:1})
         .sort({attendance:-1, rank:-1}).limit(20).forEach(printjson)'
```

## 21:00-23:00 PDT re-pull (September 26, 2026)

All sources above were pulled again for July 5 04:00-06:00 UTC into
`ingest/data/historical/2026-07-04/20260926T212007Z-21to23/`: PredictHQ 146 records, 33 overlapping (fireworks
300,000 at 21:30; Fillmore Jazz Festival 100,000); 511 archived traffic events 0; 511 WZDx 133 of 550
features scheduled across the window; DataSF 8 lane closures (Van Ness, Fell, Sutter, Hemlock, Claude Ln),
none at the waterfront; Tiger `traffic_metrics` 0 rows. No measured speeds or vehicle counts exist for it.

## What can be called the busiest point

For the 2026 event, the official SFMTA advisory identifies Crissy Field, Marina Green, and
Pier 39/Northern Embarcadero as viewing areas, schedules the show for about 21:30–21:45
PDT, closes the Golden Gate Bridge around 21:00–22:00, and warns of crowd-based street
restrictions from about 20:00. Treat the waterfront/Golden Gate viewing corridor as a
**planning hotspot** and 21:30 as a **proxy peak**. It is not a measured ranking of people
or vehicle speeds.

The live Mapbox, TomTom, Muni, and 511 pollers in this repository do not reconstruct past
surface-street speeds. A real July 4 traffic replay needs an archived provider feed or
observed counts/speeds captured on that date, plus calibrated demand and closure inputs.
Do not label a SUMO run as measured July 4 traffic when those inputs are absent.
