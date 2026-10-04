"""Runtime path and per-search IDs. Consent-gated logging lives in PrivacyStore."""
import os
import uuid
from pathlib import Path

LOG_DIR = Path(os.getenv("GEOLAB_LOG_DIR", "/opt/geolab/logs"))


def new_query_id() -> str:
    return uuid.uuid4().hex[:16]
