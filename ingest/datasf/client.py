"""Minimal SODA 2.x client for DataSF. Stdlib only.

DataSF moved from data.sfgov.org to data.sf.gov (the old host 301-redirects).
Docs: https://dev.socrata.com/docs/queries/
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

BASE_URL = "https://data.sf.gov"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class DataSFError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        super().__init__(f"DataSF {status}: {message}" if status else f"DataSF: {message}")
        self.status = status


def load_dotenv(path: Path) -> None:
    """Fill os.environ from a KEY=VALUE .env file without overriding real env vars."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class DataSF:
    def __init__(
        self,
        app_token: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30,
        retries: int = 3,
    ):
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        self.app_token = app_token if app_token is not None else os.environ.get("DATASF_APP_TOKEN") or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Accept": "application/json", "User-Agent": "transpeaktation-ingest/0.1"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:300]
                if e.code in RETRY_STATUSES and attempt < self.retries:
                    time.sleep(float(e.headers.get("Retry-After") or 2**attempt))
                    continue
                raise DataSFError(e.code, body) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                raise DataSFError(None, str(e)) from e

    def query(
        self,
        dataset_id: str,
        *,
        select: str | None = None,
        where: str | None = None,
        order: str | None = None,
        group: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """One SoQL request against /resource/<id>.json."""
        params = {
            "$select": select,
            "$where": where,
            "$order": order,
            "$group": group,
            "$limit": limit,
            "$offset": offset or None,
        }
        return self._get(f"/resource/{dataset_id}.json", params)

    def iter_rows(
        self, dataset_id: str, *, page_size: int = 1000, max_rows: int | None = None, **soql: Any
    ) -> Iterator[dict[str, Any]]:
        """Page through a query. Pass an `order` for stable paging (defaults to :id)."""
        soql.setdefault("order", ":id")
        offset = seen = 0
        while True:
            limit = page_size if max_rows is None else min(page_size, max_rows - seen)
            if limit <= 0:
                return
            page = self.query(dataset_id, limit=limit, offset=offset, **soql)
            yield from page
            seen += len(page)
            offset += len(page)
            if len(page) < limit:
                return

    def metadata(self, dataset_id: str) -> dict[str, Any]:
        """Dataset metadata: name, columns, rowsUpdatedAt (unix seconds), etc."""
        return self._get(f"/api/views/{dataset_id}.json")
