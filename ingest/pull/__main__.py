"""Pull raw snapshots from every source into ingest/data/raw/.

    python -m pull                 # everything
    python -m pull live            # one layer: static | planned | live
    python -m pull streets chp_incidents
    python -m pull.check           # data-quality report on what was pulled

Run with ingest/.venv's python to include the OSMnx road graph.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timezone

from datasf.client import load_dotenv

from . import DATA_DIR, ENV_FILE, MANIFEST
from .feeds import Skip
from .sources import SOURCES


def main(args: list[str]) -> int:
    load_dotenv(ENV_FILE)
    layers = {s.layer for s in SOURCES.values()}
    unknown = [a for a in args if a not in SOURCES and a not in layers]
    if unknown:
        print(f"unknown: {unknown}. layers: {sorted(layers)}; sources: {list(SOURCES)}")
        return 2
    chosen = [s for s in SOURCES.values() if not args or s.name in args or s.layer in args]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    failed = 0
    print(f"{'source':<24} {'layer':<8} {'status':<6} {'rows':>8} {'secs':>6}  note")
    for src in chosen:
        started = time.monotonic()
        pulled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = {"layer": src.layer, "pulled_at": pulled_at}
        try:
            records, meta = src.fetch(DATA_DIR)
            snapshot = {"source": src.name, "layer": src.layer, "pulled_at": pulled_at,
                        "count": len(records), "meta": meta, "records": records}
            (DATA_DIR / f"{src.name}.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, default=str), encoding="utf-8")
            entry.update(status="ok", count=len(records))
            note = ""
        except Skip as e:
            entry.update(status="skip", reason=str(e))
            note = str(e)
        except Exception as e:  # keep going; one broken feed shouldn't stop the rest
            failed += 1
            entry.update(status="fail", error=f"{type(e).__name__}: {e}")
            note = entry["error"][:90]
            traceback.print_exc(file=sys.stderr)
        secs = time.monotonic() - started
        manifest[src.name] = {**entry, "seconds": round(secs, 1)}
        print(f"{src.name:<24} {src.layer:<8} {entry['status']:<6} {entry.get('count', ''):>8} {secs:>6.1f}  {note}")
        MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
