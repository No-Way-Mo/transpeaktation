"""Pull raw snapshots from every Transpeaktation data source (no normalizing, no DB writes)."""
from pathlib import Path

INGEST_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = INGEST_DIR / ".env"
DATA_DIR = INGEST_DIR / "data" / "raw"
MANIFEST = DATA_DIR / "_manifest.json"
