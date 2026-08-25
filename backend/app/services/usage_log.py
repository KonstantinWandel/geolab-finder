"""Anonymous usage log for the finders.

Two things are recorded, both without any personal data: the query that was asked, and a
thumbs up or down on a single result. No IP address, no user agent, no cookie, no session
identifier, nothing that could tie two queries to the same person. The `query_id` returned
with a search exists only so a vote can name which result list it refers to; it is a random
value that is never stored anywhere else and never reaches a cookie.

Why log at all: without it, ranking work is guided by a hand-written eval instead of real
demand, and there is no way to notice that a whole class of question returns nothing useful.

Files are newline-delimited JSON under GEOLAB_LOG_DIR (default /opt/geolab/logs), one file
per month so they can be rotated or deleted wholesale.
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
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False)
        with _LOCK:
            with path.open("a", encoding="utf-8") as handle:
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


def log_feedback(query_id: str, item_id: Optional[str], vote: str, question: Optional[str],
                 comment: Optional[str]) -> None:
    """One line per vote. Votes are NOT fed back into ranking automatically: see
    scripts/report_usage.py, which turns them into eval candidates for a human to confirm."""
    _append("feedback", {
        "query_id": query_id,
        "item_id": item_id,
        "vote": "up" if str(vote).lower() in {"up", "1", "true", "yes"} else "down",
        "question": (question or "")[:400],
        "comment": (comment or "")[:1000],
    })
