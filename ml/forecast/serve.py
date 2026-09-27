"""Forecast HTTP service (stdlib): one loaded forecaster, CPU or GPU.

    python -m forecast serve [--checkpoint <ckpt>] [--host 0.0.0.0] [--port 8200]
        default checkpoint = the promoted one (forecast/serving.py); FORECAST_API_TOKEN (env) = required bearer token

GET  /v1/health      model/network/dataset identity, promotion record, latest cached forecast (issue time, age)
GET  /v1/forecast/latest   the stored forecast of the newest snapshot, instantly (?roads= ?horizons= ?format=parquet|bundle)
POST /v1/live/forecast   the congestion map of the newest complete Tiger bucket (forecast/live.py): reads Tiger +
                     Mongo, runs the model, writes Tiger prediction_metrics + Mongo forecast_runs; reused, not
                     recomputed, when it already exists. Answer = the run summary (run_id, issued_at, coverage).
                     Needs TIGER_DATABASE_URL and MONGODB_URI in the environment.
POST /v1/snapshot    compute-and-store: the ingest side posts each new 10-min snapshot (same body as below); the
                     answer is the forecast's metadata. App requests then read /v1/forecast/latest, so no user ever
                     waits for model compute (one citywide forecast per 10-min bucket).
POST /v1/forecast    body = snapshot JSON (computes on demand and also stores it as the latest if newer):
                       {"context": {"issued_at", "network_version", "cases": [...], "provenance": {...}},
                        "history": {"time": [...], "road_segment_id": [...], "speed_mph": [...],
                                    "observed": [...], "closed": [...]}}          (columnar; = history.parquet)
                     or Content-Type application/vnd.apache.parquet with ?context=<url-encoded JSON> for the history
                     Response: JSON {"meta", "forecast": {columns...}} or parquet with ?format=parquet.
                     ?roads=a,b,c limits the rows; ?horizons=10,30 limits horizons.
                     ?format=bundle = zip of forecast.parquet + closures.parquet (the exact closure intervals the
                     forecast used, possibly empty) + meta.json: what routing loads. ?store=0 = compute only, never
                     replace the stored latest (replay sessions whose issue times go backwards).
Same semantics and columns as `python -m forecast predict` (see predict.py / CONTRACT_PROPOSAL.md): synthetic-trained,
no uncertainty column, closures from the snapshot's scheduled restrictions.
"""
from __future__ import annotations

import io
import json
import zipfile
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd

from .config import sha256_file
from .predict import Predictor
from . import serving

MAX_BODY = 200 * 2**20
HISTORY_COLUMNS = ("time", "road_segment_id", "speed_mph", "observed", "closed")


class Service:
    def __init__(self, checkpoint: str | None = None, device: str | None = None):
        path, rec = serving.resolve(checkpoint)
        self.path, self.record = path, rec
        self.predictor = Predictor(str(path), device or "cpu")
        self.sha = sha256_file(path)
        self.lock = threading.Lock()
        self.started = time.time()
        self.served = 0
        self.cache_dir = serving.SERVING_DIR / "latest"
        self.latest = self._load_latest()
        self._live = None
        self.last_live: dict | None = None

    def live(self):
        if self._live is None:
            from .live import LiveForecaster, Stores
            self._live = LiveForecaster(self.predictor, Stores(), self.sha)
        return self._live

    def live_forecast(self) -> dict:
        with self.lock:                          # one model, one forward at a time (shared with /v1/forecast)
            r = self.live().ensure()
        self.last_live = {**{k: r.get(k) for k in ("run_id", "issued_at", "reused", "seconds")}, "at": time.time()}
        return r

    def _load_latest(self):
        f, c, m = (self.cache_dir / x for x in ("forecast.parquet", "closures.parquet", "meta.json"))
        if f.exists() and m.exists():
            meta = json.loads(m.read_text())
            if meta.get("model_version") == self.predictor.ck["model_version"]:
                # closures unknown for a forecast stored before they were kept: None, never "no closures"
                return pd.read_parquet(f), meta, (pd.read_parquet(c) if c.exists() else None)
        return None

    def _store(self, df: pd.DataFrame, meta: dict, closures: pd.DataFrame) -> None:
        """Keep the newest issue time (memory + disk, so a restart keeps serving it)."""
        if self.latest is not None and pd.Timestamp(self.latest[1]["issued_at"]) > pd.Timestamp(meta["issued_at"]):
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "meta.json").unlink(missing_ok=True)      # no meta = no stored forecast while swapping
        for name, t in (("forecast", df), ("closures", closures)):
            t.to_parquet(self.cache_dir / f"{name}.tmp.parquet", index=False)
            (self.cache_dir / f"{name}.tmp.parquet").replace(self.cache_dir / f"{name}.parquet")
        (self.cache_dir / "meta.json").write_text(json.dumps(meta, default=str))
        self.latest = (df, meta, closures)

    def latest_info(self) -> dict | None:
        if self.latest is None:
            return None
        meta = self.latest[1]
        age = time.time() - pd.Timestamp(meta["issued_at"]).timestamp()
        return {**{k: meta[k] for k in ("issued_at", "computed_at", "seconds", "rows")}, "age_s": round(age),
                "stale": age > 20 * 60}

    def health(self) -> dict:
        ck = self.predictor.ck
        return {"status": "ok", "model_version": ck["model_version"], "network_version": ck["network_version"],
                "dataset_id": ck["dataset_id"], "checkpoint": self.path.name, "sha256": self.sha,
                "promotion": self.record, "roads": len(ck["model_ids"]), "horizons_min": self.horizons_min(),
                "history_steps": self.predictor.cfg.data.history_steps,
                "synthetic_training": True, "uncertainty": "not available",
                "uptime_s": round(time.time() - self.started), "forecasts_computed": self.served,
                "latest": self.latest_info(), "last_live_forecast": self.last_live}

    def horizons_min(self) -> list[int]:
        d = self.predictor.cfg.data                # from the loaded checkpoint, never a fixed list
        return [d.bucket_min * (k + 1) for k in range(d.horizon_steps)]

    def forecast(self, hist: pd.DataFrame, ctx: dict, store: bool = True) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
        with self.lock:                          # one model, one forward at a time
            t0 = time.time()
            df, closures = self.predictor.frame(hist, ctx)
            self.served += 1
            meta = {"issued_at": pd.Timestamp(ctx["issued_at"]).isoformat(),
                    "model_version": self.predictor.ck["model_version"], "rows": len(df), "closures": len(closures),
                    "network_version": self.predictor.ck["network_version"], "checkpoint_sha256": self.sha,
                    "horizons_min": self.horizons_min(),
                    "seconds": round(time.time() - t0, 3), "computed_at": pd.Timestamp.now(tz="UTC").isoformat(),
                    "availability_counts": df.availability.value_counts().to_dict(),
                    "input_source": (ctx.get("provenance") or {}).get("source", "unknown")}
            if store:
                self._store(df, meta, closures)
        return df, meta, closures


def bundle_bytes(df: pd.DataFrame, closures: pd.DataFrame | None, meta: dict) -> bytes:
    """zip: forecast.parquet, closures.parquet (always present; empty = no known closures), meta.json."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, t in (("forecast.parquet", df), ("closures.parquet", closures)):
            b = io.BytesIO()
            t.to_parquet(b, index=False)
            z.writestr(name, b.getvalue())
        z.writestr("meta.json", json.dumps(meta, default=str))
    return buf.getvalue()


def make_handler(svc: Service, token: str | None):
    class H(BaseHTTPRequestHandler):
        server_version = "transpeaktation-forecast/1"

        def _send(self, code: int, body: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, default=str).encode())

        def _authorized(self) -> bool:
            if not token:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {token}"

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/v1/health":
                return self._json(200, svc.health())
            if u.path == "/v1/forecast/latest":
                if not self._authorized():
                    return self._json(401, {"error": "missing or wrong bearer token"})
                if svc.latest is None:
                    return self._json(404, {"error": "no snapshot has been posted yet (POST /v1/snapshot)"})
                df, meta, closures = svc.latest
                return self._answer(df, {**meta, **svc.latest_info()}, parse_qs(u.query), closures)
            self._json(404, {"error": "not found"})

        def _answer(self, df, meta, q, closures=None):
            if q.get("format", ["json"])[0] == "bundle":          # whole forecast: routing needs every road
                if closures is None:
                    return self._json(409, {"error": "closures not kept for this stored forecast; post it again"})
                return self._send(200, bundle_bytes(df, closures, meta), "application/zip")
            if "roads" in q:
                df = df[df.road_segment_id.isin(q["roads"][0].split(","))]
            if "horizons" in q:
                df = df[df.horizon_min.isin([int(h) for h in q["horizons"][0].split(",")])]
            if q.get("format", ["json"])[0] == "parquet":
                buf = io.BytesIO()
                df.to_parquet(buf, index=False)
                return self._send(200, buf.getvalue(), "application/vnd.apache.parquet")
            out = df.copy()
            for c in ("issued_at", "valid_from", "valid_to"):
                out[c] = out[c].astype(str)
            self._json(200, {"meta": meta, "forecast": {c: out[c].tolist() for c in out.columns}})

        def do_POST(self):
            u = urlparse(self.path)
            if u.path == "/v1/live/forecast":
                if not self._authorized():
                    return self._json(401, {"error": "missing or wrong bearer token"})
                try:
                    return self._json(200, svc.live_forecast())
                except SystemExit as e:
                    return self._json(503, {"error": str(e)})
                except Exception as e:           # inputs unavailable (DB down, ingest stalled): say so
                    return self._json(503, {"error": f"{type(e).__name__}: {e}"})
            if u.path not in ("/v1/forecast", "/v1/snapshot"):
                return self._json(404, {"error": "not found"})
            if not self._authorized():
                return self._json(401, {"error": "missing or wrong bearer token"})
            n = int(self.headers.get("Content-Length", "0"))
            if n <= 0 or n > MAX_BODY:
                return self._json(413 if n > MAX_BODY else 400, {"error": "empty or too large body"})
            q = parse_qs(u.query)
            body = self.rfile.read(n)
            try:
                if "parquet" in self.headers.get("Content-Type", ""):
                    hist = pd.read_parquet(io.BytesIO(body))
                    ctx = json.loads(unquote(q["context"][0]))
                else:
                    req = json.loads(body)
                    hist, ctx = pd.DataFrame(req["history"]), req["context"]
                missing = [c for c in HISTORY_COLUMNS if c not in hist.columns]
                if missing or "issued_at" not in ctx or not len(hist):
                    return self._json(400, {"error": "history needs columns " + ", ".join(HISTORY_COLUMNS)
                                            + " and at least one row; context needs issued_at",
                                            "missing_columns": missing})
                hist["time"] = pd.to_datetime(hist["time"], utc=True)
                ctx.setdefault("cases", [])
                df, meta, closures = svc.forecast(hist, ctx, store=q.get("store", ["1"])[0] != "0")
            except SystemExit as e:              # the predictor's validation errors
                return self._json(422, {"error": str(e)})
            except (KeyError, ValueError, TypeError) as e:
                return self._json(400, {"error": f"{type(e).__name__}: {e}"})
            except Exception as e:               # never drop the connection without an answer
                return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            if u.path == "/v1/snapshot":
                return self._json(200, {"stored": True, **meta, "latest": svc.latest_info()})
            return self._answer(df, meta, q, closures)

        def log_message(self, fmt, *args):
            print(f"{self.address_string()} {fmt % args}", flush=True)

    return H


def serve(checkpoint: str | None, host: str, port: int, device: str | None = None) -> None:
    token = os.environ.get("FORECAST_API_TOKEN")
    if not token and host not in ("127.0.0.1", "localhost"):
        raise SystemExit("FORECAST_API_TOKEN must be set when binding to a non-local address")
    svc = Service(checkpoint, device)
    print(json.dumps({"serving": svc.health()}, default=str)[:2000], flush=True)
    ThreadingHTTPServer((host, port), make_handler(svc, token)).serve_forever()
