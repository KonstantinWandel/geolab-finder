"""Deep links into INKAR, created one at a time and only for indicators someone actually opens.

INKAR keeps no state in its address. Its table and map windows read the selection from the window
that opened them, and the only thing a URL carries is the id of a query stored on the BBSR server
(`inkar.de/#<id>`). A per-indicator link therefore means creating such a query.

The obvious way, writing all 660 up front, would put 660 rows into a federal agency's database for
indicators nobody may ever look at. This service does it the other way round: the finder links to
us, and the first time a reader opens an indicator we build one query, store the id, and redirect.
Every later click reuses it. If nobody ever opens an indicator, nothing is created for it.

Everything else follows from being a guest in someone else's system:

  * one query per indicator, never more, and a stable local cache so a restart does not recreate;
  * one user id for all of them (kept in the cache file), so they can be listed and deleted again
    through the application's own endpoints;
  * a rate limit, so a crawler cannot turn into a burst of writes;
  * `GEOLAB_INKAR_PERMALINKS=0` switches the whole thing off and the links fall back to the portal;
  * any failure at all, network, timeout, unexpected answer, ends in the portal link rather than
    an error page.

The identifiers come from `data_sources/22-inkar/raw/wizard_katalog.json`
(scripts/fetch_inkar_wizard_catalogue.py), because the application uses two of them and the
workbook only carries one; that file also records which spatial level each link should open on.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE = "https://www.inkar.de/"
PORTAL = "https://www.inkar.de/"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")
# inkar.de ships an incomplete certificate chain, the same reason the link checker relaxes this.
CONTEXT = ssl._create_unverified_context()
TIMEOUT = 25


class InkarPermalinkService:
    def __init__(self, catalogue_path: str, cache_path: str,
                 enabled: bool = True, max_new_per_minute: int = 10) -> None:
        self.catalogue_path = Path(catalogue_path)
        self.cache_path = Path(cache_path)
        self.enabled = enabled
        self.max_new_per_minute = max_new_per_minute
        self._lock = threading.Lock()
        self._catalogue: Optional[Dict[str, Any]] = None
        self._cache: Optional[Dict[str, Any]] = None
        self._areas: Dict[str, List[Dict[str, str]]] = {}
        self._recent: List[float] = []

    # ---------------------------------------------------------------- storage
    def _load(self) -> None:
        if self._catalogue is None:
            try:
                self._catalogue = json.loads(self.catalogue_path.read_text(encoding="utf-8")).get("indicators") or {}
            except Exception:
                self._catalogue = {}
        if self._cache is None:
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {"user": "", "links": {}}
            self._cache.setdefault("links", {})
            self._cache.setdefault("user", "")

    def _save(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")
            temporary.replace(self.cache_path)
        except Exception:
            pass  # a link that works but is not remembered is still a working link

    # ---------------------------------------------------------------- INKAR
    def _call(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(BASE + path, data=data, headers={
            "User-Agent": UA, "Referer": BASE, "Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=CONTEXT) as response:
            body = response.read().decode("utf-8", "replace")
        value = json.loads(body)
        return json.loads(value) if isinstance(value, str) and value.strip().startswith("{") else value

    def _guid(self) -> str:
        return str(self._call("Main/GetGuid"))

    def _areas_for(self, level: str) -> List[Dict[str, str]]:
        if level not in self._areas:
            found = self._call(f"Wizard/GetGebieteZumRaumbezug/{level}").get("Gebiete") or []
            self._areas[level] = [{"level": level, "key": a["Schlüssel"], "name": (a["Name"] or "").strip()}
                                  for a in found]
        return self._areas[level]

    def _create(self, m_id: str, entry: Dict[str, Any]) -> Optional[str]:
        indicator = entry["indicator"]
        selection = {
            "IndicatorCollection": [indicator],
            # `indicator` here is the M_ID and `group` the catalogue id: the application really
            # does use two different numbers, and mixing them up yields a table that never loads.
            "TimeCollection": [{"indicator": str(m_id), "group": str(indicator["Gruppe"]),
                                "level": entry["level"], "time": entry.get("year") or "",
                                "selected": True, "visited": False}],
            "SpaceCollection": self._areas_for(entry["level"]),
            "Title": f'GeoLAB: {entry.get("short_name") or indicator["KurznamePlus"]}'
                     f' ({entry.get("level_name") or entry["level"]})',
            "pageorder": 1, "currentpage": 3, "modified": True,
        }
        if not self._cache.get("user"):
            self._cache["user"] = self._guid()
        query_id = self._guid()
        self._call("Main/SaveQuery", {
            "id": query_id,
            "json": json.dumps(selection, ensure_ascii=False).replace('"', "§"),
            "user": self._cache["user"],
            "title": selection["Title"],
        })
        return query_id

    # ---------------------------------------------------------------- public
    def link(self, m_id: str) -> str:
        """The address to send a reader to. Falls back to the portal whenever anything is off."""
        if not self.enabled:
            return PORTAL
        with self._lock:
            self._load()
            known = self._cache["links"].get(str(m_id))
            if known and known.get("id"):
                return f'{BASE}#{known["id"]}'
            entry = self._catalogue.get(str(m_id))
            if not entry:
                return PORTAL
            now = time.time()
            self._recent = [t for t in self._recent if now - t < 60]
            if len(self._recent) >= self.max_new_per_minute:
                return PORTAL
            try:
                query_id = self._create(str(m_id), entry)
            except Exception:
                return PORTAL
            if not query_id:
                return PORTAL
            self._recent.append(now)
            self._cache["links"][str(m_id)] = {
                "id": query_id,
                "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "title": entry.get("short_name", ""),
                "level": entry.get("level", ""),
            }
            self._save()
            return f"{BASE}#{query_id}"

    def status(self) -> Dict[str, Any]:
        with self._lock:
            self._load()
            return {"enabled": self.enabled, "known": len(self._catalogue or {}),
                    "created": len(self._cache["links"]), "user": bool(self._cache.get("user"))}


def from_environment() -> "InkarPermalinkService":
    root = os.getenv("INKAR_METADATA_ROOT") or os.getenv("SOEP_METADATA_ROOT") or "/app/data"
    catalogue = os.getenv("INKAR_WIZARD_CATALOGUE", str(Path(root) / "inkar_wizard_katalog.json"))
    cache = os.getenv("INKAR_PERMALINK_CACHE", str(Path(root) / "inkar_permalinks.json"))
    enabled = os.getenv("GEOLAB_INKAR_PERMALINKS", "1").strip().lower() not in {"0", "false", "no"}
    return InkarPermalinkService(catalogue, cache, enabled=enabled)
