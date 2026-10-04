"""Private query-quality log, retained for 90 days by the daily retention job.

Questions can contain personal data, so this is not described as anonymous. No IP, user agent,
or visitor identifier is recorded. A random per-search query_id links voluntary result feedback
to the corresponding search; it does not link searches to a persistent browser identity.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG_DIR = Path(os.getenv("GEOLAB_LOG_DIR", "/opt/geolab/logs"))
ENABLED = os.getenv("GEOLAB_USAGE_LOG", "1").strip().lower() not in {"0", "false", "no"}
_LOCK = threading.Lock()


def new_query_id() -> str:
    return uuid.uuid4().hex[:16]


def _append(name: str, payload: Dict[str, Any]) -> None:
    if not ENABLED:
        return
    stamp = datetime.now(timezone.utc)
    payload = {"ts": stamp.isoformat(timespec="seconds"), **payload}
    path = LOG_DIR / f"{name}-{stamp:%Y-%m}.jsonl"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o750)
        LOG_DIR.chmod(0o750)
        line = json.dumps(payload, ensure_ascii=False)
        with _LOCK:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.chmod(path, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except OSError as exc:  # logging must never break a search
        print(f"[usage-log] could not write {path}: {exc}")


def log_query(query_id: str, app_mode: str, question: str, filters: Dict[str, Any],
              results: List[Dict[str, Any]], seconds: float) -> None:
    """One line per search. `results` is trimmed to what is needed to judge the ranking."""
    _append("queries", {
        "query_id": query_id,
        "app_mode": app_mode,
        "question": question,
        "filters": {key: value for key, value in (filters or {}).items()
                    if value not in (None, "", "all", "Any", "All datasets", False)},
        "n_results": len(results),
        "top": [
            {"rank": position + 1,
             "item_id": row.get("item_id"),
             "source_key": row.get("source_key"),
             "score": round(float(row.get("score", 0.0)), 4)}
            for position, row in enumerate(results[:5])
        ],
        "seconds": round(seconds, 2),
    })
