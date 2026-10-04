#!/usr/bin/env python3
"""Run with the backend Python environment, as the service user. No public statistics API."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.privacy_store import PrivacyStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["purge", "metrics"])
args = parser.parse_args()
store = PrivacyStore(Path(os.getenv("GEOLAB_LOG_DIR", "/opt/geolab/logs")))
if args.action == "purge":
    store.purge()
else:
    print(json.dumps(store.metrics(), indent=2))
