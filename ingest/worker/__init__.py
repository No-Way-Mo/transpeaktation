"""Ingestion worker: raw snapshots (ingest/data/raw/) -> normalized, validated,
deduplicated records -> MongoDB (domain entities) / Tiger Data (time series).

    python -m worker [--dry-run] [static|planned|live|<source> ...]
"""
