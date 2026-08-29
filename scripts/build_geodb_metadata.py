#!/usr/bin/env python3
"""Flatten the fetched source catalogues in `data_sources/*/raw/` into one metadata file
in the finder's common record schema.

Output: `soep_metadata_output/geodb_metadata.json`, a JSON list whose records look like
what `_normalise_inkar_row` produces in the backend, so the advisor can load them with a
pass-through normaliser and rank them next to INKAR.

Every record MUST carry a working outward link (`source_url` / `indicator_url`); the link
is the product. Records are of three kinds:
  regional_indicator  a real indicator from a catalogue
  register_attribute  an attribute of an entity register (rows are places/institutions)
  portal              one record for a portal that has no machine-readable catalogue

Run:
  python scripts/build_geodb_metadata.py
  python scripts/build_geodb_metadata.py --only regionalatlas --dry-run
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_SOURCES = REPO_ROOT / "data_sources"
REGISTRY = DATA_SOURCES / "registry" / "geo_sources.json"
OUTPUT = REPO_ROOT / "soep_metadata_output" / "geodb_metadata.json"

# Workbook spatial-level wording -> the finder's canonical levels + NUTS aliases, so a
# filter on "Kreise" hits INKAR and the new sources alike.
SPATIAL_MAP: Dict[str, Dict[str, List[str]]] = {
    "Bund": {"spatial": ["Bund"], "nuts": ["Bund", "NUTS0"]},
    "Bundesland": {"spatial": ["Bundesländer"], "nuts": ["Bundesländer", "NUTS1"]},
    "Regierungsbezirke": {"spatial": ["Regierungsbezirke"], "nuts": ["Regierungsbezirke", "NUTS2"]},
    "Kreise & kreisfreie Städte": {"spatial": ["Kreise"], "nuts": ["Kreise", "NUTS3"]},
    "Gemeinden und Verbandsgemeinden": {"spatial": ["Gemeinden"], "nuts": ["Gemeinden", "LAU"]},
    "Bezirke": {"spatial": ["Bezirke"], "nuts": ["Bezirke"]},
    "Bezirksregionen / Ortsteile": {"spatial": ["Ortsteile"], "nuts": ["Ortsteile"]},
    "PLZ": {"spatial": ["PLZ"], "nuts": ["PLZ"]},
    "Adressen / Koordinaten": {"spatial": ["Adressen/Koordinaten"], "nuts": ["Adressen/Koordinaten"]},
    "weitere räumliche Gliederungen": {"spatial": ["Weitere Gliederungen"], "nuts": []},
}


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).replace("\xa0", " ").strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return re.sub(r"[ \t]+", " ", text)


def strip_tags(fragment: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def registry_sources() -> Dict[str, Dict[str, Any]]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Any]] = {}
    for position, record in enumerate(data["sources"], start=1):
        record["folder"] = DATA_SOURCES / f"{position:02d}-{record['slug']}"
        out[record["slug"]] = record
    return out


def map_spatial(levels: Iterable[str]) -> Dict[str, List[str]]:
    spatial: List[str] = []
    nuts: List[str] = []
    for level in levels:
        mapped = SPATIAL_MAP.get(level)
        if not mapped:
            continue
        spatial.extend(mapped["spatial"])
        nuts.extend(mapped["nuts"])
    return {"spatial_levels": sorted(set(spatial)), "nuts_levels": sorted(set(nuts))}


def join_nonempty(parts: Iterable[str]) -> str:
    return "\n".join(part for part in parts if clean(part))


def make_record(
    *,
    source_key: str,
    source_label: str,
    item_type: str,
    item_id: str,
    variable_name: str,
    label: str,
    dataset_label: str,
    theme: str = "",
    description: str = "",
    aliases: str = "",
    unit: str = "",
    stats_summary: str = "",
    spatial_levels: Optional[List[str]] = None,
    nuts_levels: Optional[List[str]] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    years_text: str = "",
    source_url: str = "",
    indicator_url: str = "",
    access_modes: Optional[List[str]] = None,
    update_frequency: str = "",
    status: str = "active",
    api_hint: str = "",
    link_level: str = "portal",
    link_verified: bool = True,
) -> Dict[str, Any]:
    spatial_levels = spatial_levels or []
    nuts_levels = nuts_levels or []
    record: Dict[str, Any] = {
        "source_key": source_key,
        "source_label": source_label,
        "item_type": item_type,
        "item_id": item_id,
        "variable_name": variable_name,
        "label": label,
        "dataset": source_label,
        "dataset_label": dataset_label or source_label,
        "theme": theme,
        "data_type": "regional indicator" if item_type == "regional_indicator" else item_type.replace("_", " "),
        "unit": unit,
        "stats_summary": stats_summary,
        "value_labels": "",
        "rich_description": description or label,
        "aliases": aliases,
        "spatial_levels": spatial_levels,
        "nuts_levels": nuts_levels,
        "year_start": year_start,
        "year_end": year_end,
        "available_years_text": years_text,
        "source_url": indicator_url or source_url,
        "selector_url": source_url,
        "indicator_url": indicator_url or source_url,
        "api_hint": api_hint,
        "access_modes": access_modes or [],
        "update_frequency": update_frequency,
        "status": status,
        # How precisely the outward link lands on the thing the record describes:
        #   indicator  the exact indicator/variable opens
        #   table      the exact table opens
        #   statistic  the statistic that contains it opens
        #   dataset    the file/dataset containing it (the record names the column)
        #   portal     the portal's entry page; the user searches from there
        "link_level": link_level,
        # Whether the link pattern was actually probed and shown to return content that
        # differs from the host's not-found page. False means the portal is a client-rendered
        # app (or refuses scripted requests), so the link follows the documented form but
        # cannot be verified from here. scripts/check_geodb_links.py audits this.
        "link_verified": link_verified,
    }
    record["search_description"] = join_nonempty(
        [
            description,
            f"Einheit / unit: {unit}." if unit else "",
            f"Synonyme / related terms: {aliases}." if aliases else "",
            f"Statistische Grundlage: {stats_summary}." if stats_summary else "",
        ]
    )
    record["embedding_context"] = join_nonempty(
        [
            f"Datenquelle / data source: {source_label}",
            f"Thema / theme: {theme}" if theme else "",
            f"Indikator / indicator: {label}",
            f"Code: {variable_name}" if variable_name else "",
            f"Beschreibung: {description}" if description else "",
            f"Einheit: {unit}" if unit else "",
            f"Synonyme: {aliases}" if aliases else "",
            f"Statistische Grundlage: {stats_summary}" if stats_summary else "",
            f"Räumliche Ebenen / spatial levels: {', '.join(spatial_levels)}" if spatial_levels else "",
            f"Jahre / years: {years_text}" if years_text else "",
            f"Zugang: {', '.join(access_modes or [])}" if access_modes else "",
            f"Aktualisierung: {update_frequency}" if update_frequency else "",
            "Hinweis: Datenangebot wird nicht mehr aktualisiert." if status == "discontinued" else "",
            {"indicator": "Der Link öffnet genau diesen Indikator.",
             "table": "Der Link öffnet genau diese Tabelle.",
             "statistic": "Der Link öffnet die zugehörige Statistik.",
             "dataset": "Der Link öffnet den Datensatz, der dieses Merkmal enthält.",
             "portal": "Der Link öffnet das Portal, dort muss weitergesucht werden."}.get(link_level, ""),
            "" if link_verified else
            "Hinweis: Das Zielportal ist eine JavaScript-Anwendung, der Link folgt der dokumentierten "
            "Form, ist aber nicht serverseitig geprüft.",
            f"URL: {indicator_url or source_url}",
        ]
    )
    return record


# --------------------------------------------------------------------------------------
# Per-source flatteners. Each takes the registry entry and returns a list of records.
# --------------------------------------------------------------------------------------

def flatten_regionalatlas(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = source["folder"] / "raw"
    # /taskrunner/services.json is the current catalogue; /app/json/ is a stale copy.
    catalogue = json.loads((raw / "services_taskrunner.json").read_text(encoding="utf-8"))

    synonyms: Dict[str, str] = {}
    thesaurus_path = raw / "thesaurus.csv"
    if thesaurus_path.exists():
        # The file is UTF-8; reading it as Latin-1 produces "BÃ¤ume" style mojibake.
        try:
            text = thesaurus_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = thesaurus_path.read_text(encoding="latin-1")
        for row in csv.reader(io.StringIO(text), delimiter=";"):
            if len(row) < 6:
                continue
            code, terms = clean(row[2]), clean(row[5])
            if code and terms:
                synonyms[code] = terms

    def levels_from_counts(counts: Iterable[int]) -> List[str]:
        # services.json reports unit counts per geometry level rather than level names.
        # Germany: 16 Länder, ~38 NUTS2 regions, ~400 Kreise, ~11k Gemeinden.
        out: List[str] = []
        for count in counts:
            if count <= 20:
                out.append("Bundesland")
            elif count <= 60:
                out.append("Regierungsbezirke")
            elif count <= 1000:
                out.append("Kreise & kreisfreie Städte")
            else:
                out.append("Gemeinden und Verbandsgemeinden")
        return sorted(set(out))

    records: List[Dict[str, Any]] = []
    for theme in catalogue:
        theme_title = clean(theme.get("title"))
        for group in theme.get("children", []):
            tcode = clean(group.get("code"))
            years = sorted(int(y) for y in group.get("years", {}) if str(y).isdigit())
            raw_levels: List[str] = []
            for entries in group.get("years", {}).values():
                for entry in entries:
                    raw_levels.extend(entry.get("geom_levels", []) or [])
            mapped = map_spatial(levels_from_counts(raw_levels))

            for attribute in group.get("attributes", []):
                icode = clean(attribute.get("code"))
                title = clean(attribute.get("title_short"))
                if not icode or not title:
                    continue
                meta = clean(attribute.get("meta")).replace("wiki\n", "")
                meta = re.sub(r"={2,3}([^=]+)={2,3}", r"\1:", meta)
                meta = re.sub(r"\s*\n\s*", " ", meta).strip()
                url = (
                    "https://regionalatlas.statistikportal.de/"
                    f"?BL=DE&TCode={tcode}&ICode={icode}"
                    + (f"&Jhr={years[-1]}" if years else "")
                )
                records.append(
                    make_record(
                        source_key="regionalatlas",
                link_level="indicator",
                        source_label="Regionalatlas Deutschland",
                        item_type="regional_indicator",
                        item_id=f"regionalatlas:{tcode}:{icode}",
                        variable_name=icode,
                        label=title,
                        dataset_label=clean(group.get("title_short")) or theme_title,
                        theme=theme_title,
                        description=meta,
                        aliases=synonyms.get(icode, ""),
                        unit=clean(attribute.get("unit")),
                        spatial_levels=mapped["spatial_levels"],
                        nuts_levels=mapped["nuts_levels"],
                        year_start=years[0] if years else None,
                        year_end=years[-1] if years else None,
                        years_text=f"{years[0]}-{years[-1]}" if years else "",
                        source_url="https://regionalatlas.statistikportal.de/",
                        indicator_url=url,
                        # The Regionalatlas is a dojo/ArcGIS app: it reads TCode/ICode from the
                        # query string client-side, so a bogus code returns the same page as a
                        # real one and a script cannot check the deep link. Confirmed by hand in
                        # a browser on 2026-08-25, so the pattern counts as verified.
                        link_verified=True,
                        access_modes=source["access_modes"],
                        update_frequency=source["update_frequency"],
                        api_hint=(
                            f"Regionalatlas TCode={tcode}, ICode={icode}. Werte stammen aus der "
                            "Regionalstatistik (www.regionalstatistik.de/genesis/online)."
                        ),
                    )
                )
    return records


def flatten_datenguide_genesis(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    keys_dir = source["folder"] / "raw" / "genesapi-data" / "keys"
    if not keys_dir.exists():
        return []

    # The statistic codes in the Destatis definition text are not all carried by the
    # REGIONAL database: an audit found only 429 of 965 exist there, 468 are federal-only.
    # Linking all of them to regionalstatistik sent half the records to a not-found page,
    # so each code is resolved against the catalogues that were actually enumerated.
    def statistic_codes(path: Path) -> set:
        if not path.exists():
            return set()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {clean(entry.get("Code")) for entry in payload.get("statistics") or []}

    regio_codes = statistic_codes(DATA_SOURCES / "21-datenguide-abgeschaltet" / "raw"
                                 / "genesis_catalogue_regionalstatistik.json")
    bund_codes = statistic_codes(DATA_SOURCES / "28-genesis-online-bund" / "raw"
                                / "genesis_catalogue_destatis.json")

    # Mining the statistic out of the definition text only works where Destatis wrote one in.
    # For the rest, `catalogue/statistics2variable` answers the same question directly, and
    # scripts/resolve_merkmal_statistics.py asks it once per Merkmal. Without this, 1,596 of
    # the 3,305 records here (15% of the whole index) linked to the portal home page.
    resolved_statistics: Dict[str, Dict[str, Any]] = {}
    resolved_path = source["folder"] / "raw" / "merkmal_statistics.json"
    if resolved_path.exists():
        resolved_statistics = json.loads(resolved_path.read_text(encoding="utf-8")).get("merkmale") or {}

    german: Dict[str, Dict[str, Any]] = {}
    english: Dict[str, Dict[str, Any]] = {}
    for path in keys_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        code = clean(payload.get("code"))
        if not code:
            continue
        (german if payload.get("lang") == "de" else english)[code] = payload

    # Some Merkmale are classification keys that recur verbatim across statistics
    # ("Tierarten" 9x, "Bodennutzungsarten" 7x). They are identical in meaning, so only the
    # best-linked one is kept: a statistic-level link beats a portal-level one, and after that
    # the lowest code wins for a stable, reproducible choice.
    by_label: Dict[str, List[str]] = {}
    for code, payload in german.items():
        label = clean(payload.get("name"))
        if label:
            by_label.setdefault(label.lower(), []).append(code)

    records: List[Dict[str, Any]] = []
    for code, payload in sorted(german.items()):
        name = clean(payload.get("name"))
        if not name:
            continue
        description = clean(payload.get("description"))
        # The Destatis definition text repeats the term and a copyright line; keep the
        # substance, drop the trailing copyright.
        description = re.sub(r"©\s*Statistisches Bundesamt[^\n]*", "", description).strip()
        # Skip a duplicate classification Merkmal unless this code is the chosen winner.
        siblings = by_label.get(name.lower(), [])
        if len(siblings) > 1:
            def rank(candidate: str) -> tuple:
                text = clean(german.get(candidate, {}).get("description"))
                has_statistic = "Statistik(en):" in text
                return (0 if has_statistic else 1, candidate)
            if code != min(siblings, key=rank):
                continue

        english_name = clean(english.get(code, {}).get("name"))

        # The Regionalstatistik portal is a JSF app: query parameters like
        # ?operation=merkmal&code=... are ignored and land on the homepage. The one
        # pattern that really deep-links is /genesis/online/statistic/<5-digit code>,
        # and the Destatis definition text names the statistics that use the key
        # ("Erläuterung für folgende Statistik(en): 12612 Statistik der Geburten").
        statistics = re.findall(r"(\d{5})\s+([^\n]{4,80})", description.split("Statistik(en):", 1)[1]) \
            if "Statistik(en):" in description else []
        statistic_names = "; ".join(f"{c} {n.strip()}" for c, n in statistics[:4])
        # Prefer a statistic that the regional database really carries; fall back to the
        # federal one; only then to the portal entry.
        statistic_code = next((c for c, _ in statistics if c in regio_codes), "")
        held_by = "regional"
        if not statistic_code:
            statistic_code = next((c for c, _ in statistics if c in bund_codes), "")
            held_by = "federal" if statistic_code else "unknown"
        if held_by == "unknown":
            # Nothing in the text; use what the API said this Merkmal belongs to.
            api_entry = resolved_statistics.get(code) or {}
            api_statistics = api_entry.get("statistics") or []
            if api_statistics:
                statistic_code = clean(api_statistics[0].get("code"))
                held_by = "regional" if api_entry.get("instance") == "regionalstatistik" else "federal"
                if not statistic_names:
                    statistic_names = "; ".join(
                        f"{clean(item.get('code'))} {clean(item.get('label'))}"
                        for item in api_statistics[:4])
        if held_by == "regional":
            # Verified against a deliberately bogus code: a real statistic answers about 12.7 KB,
            # code 99999 answers 8.9 KB.
            url = f"https://www.regionalstatistik.de/genesis/online/statistic/{statistic_code}"
            link_ok, level = True, "statistic"
        elif held_by == "federal":
            # Same federal portal as the GENESIS table links, confirmed by hand in a browser on
            # 2026-08-25. It is a client-rendered SPA, so the response is a 2.5 KB shell whatever
            # the code is: the link works for a human but cannot be probed from here, and saying
            # otherwise would be the difference between checking and assuming.
            url = f"https://www-genesis.destatis.de/datenbank/online/statistic/{statistic_code}"
            link_ok, level = False, "statistic"
        else:
            url = "https://www.regionalstatistik.de/genesis/online"
            link_ok, level = True, "portal"
        records.append(
            make_record(
                source_key="regionalstatistik",
                source_label="Regionalstatistik / GENESIS (Regionaldatenbank)",
                item_type="regional_indicator",
                item_id=f"genesis:{code}",
                variable_name=code,
                label=name,
                dataset_label=clean(payload.get("type")) or "Merkmal",
                theme="Regionalstatistik",
                description=description or name,
                aliases=", ".join(part for part in [english_name, statistic_names] if part),
                stats_summary=statistic_names,
                spatial_levels=["Bundesländer", "Kreise", "Gemeinden"],
                nuts_levels=["Bundesländer", "NUTS1", "Kreise", "NUTS3", "Gemeinden", "LAU"],
                source_url="https://www.regionalstatistik.de/genesis/online",
                indicator_url=url,
                link_level=level,
                link_verified=link_ok,
                access_modes=["machine-readable API", "web UI / search form only"],
                update_frequency=source["update_frequency"],
                api_hint=(
                    f"GENESIS-Merkmal {code}"
                    + (f", erhoben in Statistik {statistic_names}." if statistic_names else ".")
                    + (" Diese Statistik führt die Regionaldatenbank." if held_by == "regional"
                       else " Diese Statistik liegt in der Bundesdatenbank, nicht in der Regionaldatenbank."
                       if held_by == "federal" else "")
                    + " Tabellen im Portal über die Merkmalssuche finden oder per "
                    "Regionalstatistik-Webservice-API abrufen (Token nötig)."
                ),
            )
        )
    return records


def flatten_btw21(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Strukturdaten for the Bundestag constituencies, for every election edition on disk.

    The 2021 and 2025 files have the same shape (a `Spalten-Nr.` row, then a `Land` header row,
    then one column per indicator) but different constituency boundaries and reference dates, so
    each edition is indexed separately: the same label means a different measurement in each.
    """
    raw = source["folder"] / "raw"
    editions = [
        (2021, "btw21_strukturdaten.csv", "Bundestagswahl 2021",
         "https://www.bundeswahlleiter.de/bundestagswahlen/2021/strukturdaten/beschreibung.html"),
        (2025, "btw2025_strukturdaten.csv", "Bundestagswahl 2025",
         "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/strukturdaten.html"),
    ]

    # Descriptions: <h3> indicator heading followed by explanatory text (2021 documentation page;
    # the indicator definitions carry over to 2025).
    descriptions: Dict[str, str] = {}
    page_path = raw / "beschreibung.html"
    if page_path.exists():
        page = page_path.read_text(encoding="utf-8", errors="replace")
        for block in re.split(r"<h3[^>]*>", page)[1:]:
            heading, _, rest = block.partition("</h3>")
            heading = strip_tags(heading)
            body = strip_tags(rest.split("<h3")[0])[:1200]
            if heading:
                descriptions[heading.lower()] = body

    def tokens(text: str) -> set:
        return {t for t in re.split(r"[^a-zäöüß]+", text.lower()) if len(t) > 3}

    def describe(column: str) -> str:
        # Headings ("Bevölkerung und Alter") and column names ("Bevölkerung am
        # 31.12.2019 - Deutsche (in 1000)") never match literally, so score by how much
        # of the heading's vocabulary the column repeats.
        column_tokens = tokens(column)
        best, best_score = "", 0.0
        for heading, body in descriptions.items():
            heading_tokens = tokens(heading)
            if not heading_tokens:
                continue
            score = len(heading_tokens & column_tokens) / len(heading_tokens)
            if score > best_score:
                best, best_score = body, score
        return best if best_score >= 0.5 else ""

    records: List[Dict[str, Any]] = []
    for year, filename, edition_label, doc_url in editions:
        csv_path = raw / filename
        if not csv_path.exists():
            continue
        lines = [line for line in csv_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                 if not line.startswith("#")]
        header: List[str] = []
        for line in lines:
            fields = [clean(f) for f in line.split(";")]
            if fields and fields[0].startswith("Spalten-Nr"):
                continue
            if fields and fields[0] == "Land":
                header = fields
                break
        if not header:
            raise RuntimeError(f"Could not find the header row in {filename}")
        for position, column in enumerate(header[3:], start=1):  # skip Land, WK-Nr, WK-Name
            if not column:
                continue
            records.append(
                make_record(
                    source_key="btw_strukturdaten",
                    link_level="dataset",
                    source_label="Strukturdaten für die Wahlkreise (Bundestagswahl)",
                    item_type="regional_indicator",
                    item_id=f"btw{year}:{position:02d}",
                    variable_name=f"BTW{year}-{position:02d}",
                    label=f"{column} [{year}]",
                    dataset_label=f"Strukturdaten {edition_label}",
                    theme="Politik / Wahlkreisstruktur",
                    description=describe(column),
                    spatial_levels=["Bundestagswahlkreise", "Bundesländer"],
                    nuts_levels=["Bundestagswahlkreise", "Bundesländer", "NUTS1"],
                    year_start=year,
                    year_end=year,
                    years_text=str(year),
                    source_url=source["url"],
                    indicator_url=doc_url,
                    access_modes=source["access_modes"],
                    update_frequency=source["update_frequency"],
                    api_hint=f"Spalte {position} in {filename} (Wahlkreisebene, Bundeswahlleiterin). "
                             f"Gebietsstand der Wahlkreise zur {edition_label}.",
                )
            )
    return records

def flatten_migration_regionen(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    archive_path = source["folder"] / "raw" / "migration_integration_regionen.zip"
    with zipfile.ZipFile(archive_path) as archive:
        name = next(n for n in archive.namelist() if n.endswith("beschreibung.xlsx"))
        with archive.open(name) as handle:
            frame = pd.read_excel(io.BytesIO(handle.read()), header=None)

    header_row = frame.index[frame[0].astype(str).str.strip() == "Spalte"]
    start = int(header_row[0]) + 1 if len(header_row) else 4

    records: List[Dict[str, Any]] = []
    current_time = ""
    current_source = ""
    for _, row in frame.iloc[start:].iterrows():
        code = clean(row.get(0))
        content = clean(row.get(1))
        if not code or not content:
            continue
        unit = clean(row.get(2))
        current_time = clean(row.get(3)) or current_time
        current_source = clean(row.get(4)) or current_source
        if code in {"RS", "NAME"}:  # geometry keys, not indicators
            continue
        records.append(
            make_record(
                source_key="migration_integration",
                link_level="dataset",
                source_label="Migration und Integration in den Regionen (Destatis)",
                item_type="regional_indicator",
                item_id=f"migration_integration:{code}",
                variable_name=code,
                label=content,
                dataset_label="Migration.Integration.Regionen",
                theme="Migration",
                description=content,
                unit=unit,
                stats_summary=current_source,
                spatial_levels=["Kreise"],
                nuts_levels=["Kreise", "NUTS3"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=current_time or "Stichtag 31.12.2022",
                source_url=source["url"],
                indicator_url=source["url"],
                access_modes=source["access_modes"],
                update_frequency=source["update_frequency"],
                api_hint=f"Spalte {code} in migration_integration_regionen_daten.csv (Kreisebene).",
            )
        )
    return records


def flatten_hochschulkompass(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = source["folder"] / "raw" / "hs_liste.txt"
    if not path.exists():
        return []
    text = path.read_text(encoding="latin-1")
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    header = [clean(h) for h in rows[0]]
    institutions = len(rows) - 1

    # Rows are institutions, so the indexable items are the ATTRIBUTES of the register,
    # each phrased as what a researcher could derive from it at a place.
    described = {
        "Hochschultyp": "Art der Hochschule (Universität, Fachhochschule/HAW, künstlerische Hochschule, ...).",
        "Trägerschaft": "Trägerschaft der Hochschule (öffentlich-rechtlich, privat, kirchlich).",
        "Anzahl Studierende": "Studierendenzahl je Hochschule; aggregierbar zu Studierenden je Kreis, Gemeinde oder Postleitzahl.",
        "Gründungsjahr": "Gründungsjahr der Hochschule.",
        "Promotionsrecht": "Ob die Hochschule das Promotionsrecht besitzt.",
        "Habilitationsrecht": "Ob die Hochschule das Habilitationsrecht besitzt.",
        "Bundesland": "Bundesland des Hochschulstandorts.",
        "Postleitzahl (Hausanschrift)": "Postleitzahl des Hochschulstandorts; erlaubt Distanzberechnungen zur nächsten Hochschule.",
        "Ort (Hausanschrift)": "Ort des Hochschulstandorts; Grundlage für Standort- und Erreichbarkeitsanalysen.",
        "Straße": "Straßenanschrift der Hochschule; georeferenzierbar über Geocoding.",
        "Mitglied HRK": "Mitgliedschaft in der Hochschulrektorenkonferenz.",
    }
    records: List[Dict[str, Any]] = []
    for column in header:
        if column not in described:
            continue
        records.append(
            make_record(
                source_key="hochschulkompass",
                link_level="dataset",
                source_label="Hochschulkompass (HRK)",
                item_type="register_attribute",
                item_id=f"hochschulkompass:{column}",
                variable_name=column,
                label=f"{column} (Hochschulverzeichnis)",
                dataset_label="Hochschulliste (hs_liste.txt)",
                theme="Bildung",
                description=(
                    f"{described[column]} Merkmal im Hochschulverzeichnis des Hochschulkompass "
                    f"mit {institutions} Hochschulen in Deutschland, adressgenau (Straße, PLZ, Ort)."
                ),
                spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU", "Bundesländer", "NUTS1"],
                source_url=source["url"],
                indicator_url=source["url"],
                access_modes=source["access_modes"],
                update_frequency=source["update_frequency"] or "laufend",
                api_hint="Spalte in der Hochschulliste (Tab-getrennt, Latin-1) des Hochschulkompass.",
            )
        )
    return records


def flatten_laendermonitor(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ländermonitor Frühkindliche Bildungssysteme.

    The indicator names come from the server-rendered overview page. The definitions live in
    public Methodik PDFs, one per topic area, which are two-column and therefore only readable
    in reading order (`pdftotext` without `-layout`): with `-layout` the columns interleave and
    every definition picks up half a sentence from its neighbour."""
    import subprocess
    import tempfile

    raw = source["folder"] / "raw"
    page = (raw / "uebersicht-aller-indikatoren.html").read_text(encoding="utf-8", errors="replace")
    headings = [strip_tags(match) for match in re.findall(r"<h2[^>]*>(.*?)</h2>", page, re.S)]
    indicators = [h for h in headings if "|" in h]

    # Pull the methodology text once per PDF, in reading order.
    methodology: Dict[str, List[str]] = {}
    for pdf_path in sorted(raw.glob("Methodik_*.pdf")):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            subprocess.run(["pdftotext", str(pdf_path), str(out_path)],
                           check=True, capture_output=True, timeout=120)
            methodology[pdf_path.stem] = out_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f"[warn] laendermonitor: could not read {pdf_path.name}: {exc}")
        finally:
            out_path.unlink(missing_ok=True)

    def definition_for(leaf: str) -> Tuple[str, str]:
        """The paragraphs following the heading line that matches this indicator."""
        target = leaf.strip().lower()
        for source_name, lines in methodology.items():
            for index, line in enumerate(lines):
                if line.strip().lower() == target or (len(target) > 12 and target in line.strip().lower()
                                                      and len(line.strip()) < len(target) + 24):
                    collected: List[str] = []
                    for following in lines[index + 1: index + 26]:
                        text = following.strip()
                        if not text:
                            if collected:
                                break
                            continue
                        # a short line with no sentence end is the next heading
                        if collected and len(text) < 60 and not text.endswith((".", ":", ",", ";")):
                            break
                        collected.append(text)
                    if collected:
                        return " ".join(collected)[:1200], source_name
        return "", ""

    records: List[Dict[str, Any]] = []
    for heading in dict.fromkeys(indicators):
        parts = [clean(part) for part in heading.split("|")]
        definition, source_name = definition_for(parts[-1])
        records.append(
            make_record(
                source_key="laendermonitor",
                source_label="Ländermonitor Frühkindliche Bildungssysteme (Bertelsmann Stiftung)",
                item_type="regional_indicator",
                item_id=f"laendermonitor:{'-'.join(parts).lower()}",
                variable_name=parts[-1],
                label=heading,
                dataset_label=parts[0],
                theme="Kinder und Jugend / Frühkindliche Bildung",
                description=join_nonempty([
                    f"Indikator des Ländermonitors zu {parts[0]}: {' / '.join(parts[1:])}.",
                    f"Definition laut Methodik des Ländermonitors: {definition}" if definition else "",
                    "Vergleich der Bundesländer und regionaler Einheiten zur Kindertagesbetreuung.",
                    f"Quelle der Definition: {source_name.replace('_', ' ')}.pdf" if source_name else "",
                ]),
                spatial_levels=["Bundesländer", "Kreise"],
                nuts_levels=["Bundesländer", "NUTS1", "Kreise", "NUTS3"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url=source["url"],
                link_level="dataset",
                access_modes=source["access_modes"],
                update_frequency=source["update_frequency"],
                api_hint="Indikator im Ländermonitor; Definitionen in den Methodik-PDFs der jeweiligen Bereiche.",
            )
        )
    return records


def flatten_ba_strukturdaten(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The BA booklets are laid out as: a section header row (label in column 0, no
    values), then one row per indicator (label in column 0, numbers in the value
    columns). The `Glossar Strukturdaten` sheet defines the underlying concepts, so its
    definitions are matched onto the indicator labels."""
    path = next((p for p in (source["folder"] / "raw").glob("sdi-*.xlsx")), None)
    if path is None:
        return []

    glossary: Dict[str, str] = {}
    try:
        sheet = pd.read_excel(path, sheet_name="Glossar Strukturdaten", header=None)
        for _, row in sheet.iterrows():
            term = clean(row.get(0)).replace("-\n", "").replace("\n", " ")
            definition = clean(row.get(2)).replace("\n", " ")
            if term and definition and len(definition) > 40:
                glossary[term.lower()] = definition
    except ValueError:
        pass

    def define(label: str) -> str:
        lowered = label.lower()
        for term, definition in glossary.items():
            if term and term in lowered:
                return definition
        return ""

    records: List[Dict[str, Any]] = []
    seen: set = set()
    for sheet_name, kind in [("Strukturdaten", "Strukturdaten"), ("Strukturindikatoren", "Strukturindikatoren")]:
        try:
            frame = pd.read_excel(path, sheet_name=sheet_name, header=None)
        except ValueError:
            continue
        section = ""
        for _, row in frame.iterrows():
            label = clean(row.get(0)).replace("\n", " ")
            values = [clean(v) for v in row.tolist()[1:]]
            has_value = any(re.match(r"^-?[\d.,]+$", v) for v in values if v)
            if not label or len(label) < 4:
                continue
            if re.match(r"^(Strukturdaten|Strukturindikatoren|Stand:|Quelle|Erstellt|Impressum|©|\d{3} )", label):
                continue
            if not has_value:
                section = label  # section header row, e.g. "Bevölkerungsstatistik (...)"
                continue
            code_match = re.match(r"^([A-Z]\d{1,2})\s+(.*)$", label)
            code = code_match.group(1) if code_match else ""
            title = code_match.group(2) if code_match else label
            key = (sheet_name, title.lower())
            if key in seen:
                continue
            seen.add(key)
            index = len(records) + 1
            records.append(
                make_record(
                    source_key="ba_strukturdaten",
                link_level="dataset",
                    source_label="Strukturdaten und -indikatoren des regionalen Arbeitsmarktes (Bundesagentur für Arbeit)",
                    item_type="regional_indicator",
                    item_id=f"ba_sdi:{sheet_name}:{code or index:04}",
                    variable_name=code or f"BA-SDI-{index:03d}",
                    label=title,
                    dataset_label=section or kind,
                    theme="Arbeitsmarkt & Beschäftigung",
                    description=join_nonempty(
                        [
                            f"{title}. Merkmal der BA-Reihe '{kind} des regionalen Arbeitsmarktes', "
                            f"Abschnitt '{section}'." if section else f"{title}. Merkmal der BA-Reihe '{kind}'.",
                            define(title),
                        ]
                    ),
                    stats_summary=section,
                    spatial_levels=["Bundesländer", "Kreise", "Weitere Gliederungen"],
                    nuts_levels=["Bundesländer", "NUTS1", "Kreise", "NUTS3"],
                    year_start=source["coverage_start_year"],
                    year_end=source["coverage_end_year"],
                    years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                    source_url=source["url"],
                    indicator_url=source["url"],
                    access_modes=source["access_modes"],
                    update_frequency=source["update_frequency"],
                    api_hint=(
                        "Heft der Reihe 'Strukturdaten und -indikatoren' (XLSX je Agenturbezirk/Kreis) unter "
                        "statistik.arbeitsagentur.de; Regionen werden über den Heft-Code gewählt."
                    ),
                )
            )
    return records


def _deutschlandatlas_maps(folder: Path) -> List[Dict[str, str]]:
    """The atlas's own map pages, harvested by scripts/fetch_sources.py."""
    path = folder / "raw" / "karten_index.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("maps") or []


# Three indicators whose wording shares no words with their map's title, so no threshold can
# match them without also creating false matches elsewhere. Keyed by Indikatorenkuerzel (stable)
# rather than by label (changes with the reference year). Both URLs verified: HTTP 200 at 124/113
# KB against 96 KB for a bogus code.
DEUTSCHLANDATLAS_MAP_OVERRIDES: Dict[str, str] = {
    "bquali_mabschl": "https://www.deutschlandatlas.bund.de/DE/Karten/Wie-wir-arbeiten/050/_node.html",
    "bquali_oabschl": "https://www.deutschlandatlas.bund.de/DE/Karten/Wie-wir-arbeiten/050/_node.html",
    "v_5g": "https://www.deutschlandatlas.bund.de/DE/Karten/Wie-wir-uns-vernetzen/"
            "Mobile-Breitbandverfuegbarkeit-Karte/_node.html",
}


def _match_map(label: str, maps: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Best map page for an indicator label.

    The map titles are shorter than the indicator names ("Beschaeftigungsquote" for
    "Beschaeftigungsquote (Maenner)"), so an exact match is tried first, then containment of the
    map's words in the indicator's, then a token-overlap threshold. Anything weaker is left
    unmatched on purpose: a wrong map link is worse than the dataset link it replaces.
    """
    def tokens(value: str) -> set:
        cleaned = re.sub(r"\(.*?\)", " ", (value or "").replace("\u00ad", "").casefold())
        return {t for t in re.split(r"[^a-z0-9\u00e4\u00f6\u00fc\u00df]+", cleaned) if len(t) > 2}

    label_tokens = tokens(label)
    if not label_tokens:
        return None
    normalised = " ".join(sorted(label_tokens))
    for entry in maps:
        if " ".join(sorted(tokens(entry["title"]))) == normalised:
            return entry
    best, best_score = None, 0.0
    for entry in maps:
        title_tokens = tokens(entry["title"])
        if not title_tokens:
            continue
        if title_tokens <= label_tokens:
            # map title is the short form of the indicator name
            score = 0.90 + len(title_tokens) / 100.0
        elif label_tokens <= title_tokens:
            # some index entries are the title followed by the map's own blurb, so the
            # indicator name sits INSIDE them; the shortest such entry is the closest one
            score = 0.85 + 1.0 / (1 + len(title_tokens))
        else:
            score = len(title_tokens & label_tokens) / len(title_tokens | label_tokens)
        if score > best_score:
            best, best_score = entry, score
    return best if best_score >= 0.7 else None


def flatten_deutschlandatlas(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The Deutschlandatlas ships both halves of a catalogue: the PDF documents every
    indicator (`<name> | Indikatorenkürzel: <code>`, definition, Gebietsstand, Datenbasis,
    methodischer Hinweis) and the XLSX shows which spatial level and reference date each
    indicator is actually published for."""
    raw = source["folder"] / "raw"
    maps = _deutschlandatlas_maps(source["folder"])
    matched_maps = 0
    pdf_path = raw / "Indikatoren_Deutschlandatlas.pdf"
    xlsx_path = raw / "Deutschlandatlas-Daten.xlsx"

    text = ""
    if pdf_path.exists():
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            subprocess.run(["pdftotext", "-layout", str(pdf_path), str(out_path)], check=True,
                           capture_output=True, timeout=120)
            text = out_path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f"[warn] deutschlandatlas: pdftotext unavailable or failed ({exc}); using the XLSX only")
        finally:
            out_path.unlink(missing_ok=True)

    # Page headers repeat the section name ("Wo wir leben | Stand: ..."), which gives the theme.
    themes: Dict[int, str] = {}
    lines = text.splitlines()
    for position, line in enumerate(lines):
        header = re.match(r"^\s*([A-ZÄÖÜ][^|]{3,60}?)\s*\|\s*Stand:", line)
        if header:
            themes[position] = clean(header.group(1))

    def theme_at(position: int) -> str:
        best = ""
        for line_number, name in themes.items():
            if line_number <= position:
                best = name
            else:
                break
        return best

    documented: Dict[str, Dict[str, str]] = {}
    for position, line in enumerate(lines):
        match = re.match(r"^(.{3,90}?)\s*\|\s*Indikatoren?kürzel:\s*([A-Za-z0-9_]+)\s*$", line.strip())
        if not match:
            continue
        name, code = clean(match.group(1)), clean(match.group(2))
        window = lines[position + 1: position + 22]
        for offset, following in enumerate(window):
            if re.match(r"^.{3,90}?\s*\|\s*Indikatoren?kürzel:", following.strip()):
                window = window[:offset]
                break
        block = "\n".join(window)
        definition = clean(block.splitlines()[0]) if block.strip() else ""

        def field(label: str) -> str:
            found = re.search(rf"{label}:\s*(.+?)(?=\n\s*(?:Gebietsstand|Datenbasis|Methodischer Hinweis|Seite \d+)|\Z)",
                              block, re.S)
            return re.sub(r"\s+", " ", found.group(1)).strip() if found else ""

        documented[code] = {
            "name": name,
            "definition": definition,
            "gebietsstand": field("Gebietsstand"),
            "datenbasis": field("Datenbasis"),
            "hinweis": field("Methodischer Hinweis"),
            "theme": theme_at(position),
        }

    # Which sheets (level + reference date) carry each indicator.
    level_names = {"GEM": "Gemeinden und Verbandsgemeinden", "KRS": "Kreise & kreisfreie Städte",
                   "VBGEM": "Gemeinden und Verbandsgemeinden"}
    published: Dict[str, List[str]] = {}
    header_texts: Dict[str, str] = {}
    if xlsx_path.exists():
        workbook = pd.ExcelFile(xlsx_path)
        for sheet in workbook.sheet_names:
            match = re.match(r"Deutschlandatlas_(GEM|VBGEM|KRS)(\d{2})(\d{2})", sheet)
            if not match:
                continue
            prefix, _, year = match.groups()
            frame = pd.read_excel(xlsx_path, sheet_name=sheet, header=None, nrows=4)
            for cell in frame.iloc[3].tolist():
                header = clean(str(cell)).replace("\n", " ")
                code_match = re.search(r"Indikatorkürzel:\s*([A-Za-z0-9_]+)", header)
                if not code_match:
                    continue
                code = code_match.group(1)
                published.setdefault(code, []).append(f"{level_names[prefix]}|20{year}")
                header_texts.setdefault(code, re.sub(r"Indikatorkürzel:\s*\S+\s*", "", header).strip())

    codes = sorted(set(documented) | set(published))
    records: List[Dict[str, Any]] = []
    for code in codes:
        info = documented.get(code, {})
        entries = published.get(code, [])
        # "... im Jahr 2023 in %" is the reference year of the values; the year in the
        # sheet name is only the Gebietsstand (the boundary vintage), so prefer the former.
        data_years = [int(y) for y in re.findall(r"im Jahr (\d{4})", info.get("definition", ""))]
        levels = sorted({entry.split("|")[0] for entry in entries})
        years = data_years or sorted({int(entry.split("|")[1]) for entry in entries})
        mapped = map_spatial(levels)
        label = info.get("name") or header_texts.get(code, code)
        description = join_nonempty([
            info.get("definition") or header_texts.get(code, ""),
            f"Datenbasis: {info['datenbasis']}" if info.get("datenbasis") else "",
            f"Methodischer Hinweis: {info['hinweis']}" if info.get("hinweis") else "",
            f"Gebietsstand: {info['gebietsstand']}" if info.get("gebietsstand") else "",
        ])
        match = _match_map(label, maps)
        if not match and code in DEUTSCHLANDATLAS_MAP_OVERRIDES:
            match = {"url": DEUTSCHLANDATLAS_MAP_OVERRIDES[code], "title": label}
        if match:
            matched_maps += 1
        records.append(
            make_record(
                source_key="deutschlandatlas",
                source_label="Deutschlandatlas (BBSR / Statistisches Bundesamt)",
                item_type="regional_indicator",
                item_id=f"deutschlandatlas:{code}",
                variable_name=code,
                label=label,
                dataset_label=info.get("theme") or "Deutschlandatlas",
                theme=info.get("theme") or "Deutschlandatlas",
                description=description or label,
                stats_summary=info.get("datenbasis", ""),
                spatial_levels=mapped["spatial_levels"] or ["Gemeinden", "Kreise"],
                nuts_levels=mapped["nuts_levels"] or ["Gemeinden", "LAU", "Kreise", "NUTS3"],
                year_start=years[0] if years else None,
                year_end=years[-1] if years else None,
                years_text=(f"{years[0]}-{years[-1]}" if len(years) > 1 else (str(years[0]) if years else "")),
                source_url="https://www.deutschlandatlas.bund.de/",
                # The atlas does publish a page per map; the index lives at /DE/Karten/_node.html
                # and is reachable with a cookie jar (it answers 307 to a cookie check, which
                # earlier looked like a hard 400). An indicator without a confident title match
                # keeps the download route, which always exists.
                indicator_url=(match["url"] if match else
                               "https://www.deutschlandatlas.bund.de/DE/Service/Downloads/downloads_node.html"),
                link_level="indicator" if match else "dataset",
                link_verified=bool(match),
                access_modes=source["access_modes"] or ["direct file download", "interactive map viewer"],
                update_frequency=source["update_frequency"],
                api_hint=(
                    (f"Gebietsstand: {info['gebietsstand']}. " if info.get("gebietsstand") else "")
                    + f"Indikatorenkürzel (Spaltenname) {code}"
                    + (f", Blatt 'Deutschlandatlas_{info['gebietsstand']}'"
                       if info.get("gebietsstand") else "")
                    + " in 'Deutschlandatlas-Daten.xlsx' (Download: "
                    "https://www.deutschlandatlas.bund.de/SharedDocs/Downloads/DE/"
                    "Deutschlandatlas-Daten.html), fehlende Werte = -9999. Indikatorendokumentation: "
                    "https://www.deutschlandatlas.bund.de/SharedDocs/Downloads/DE/"
                    "Indikatoren_Deutschlandatlas.html"
                ),
            )
        )
    if maps:
        print(f"[info] deutschlandatlas: {matched_maps} of {len(records)} indicators matched to a map page "
              f"({len(maps)} map pages harvested)")
    return records


# G-BA Qualitätsbericht sections: the XML schema is derived from the data, the German
# gloss is authored here so the records read as concepts rather than element names.
GBA_SECTIONS: Dict[str, str] = {
    "Anzahl_Betten": "Zahl der aufgestellten Betten je Krankenhausstandort.",
    "Fallzahlen": "Fallzahlen des Standorts: vollstationäre, teilstationäre, stationsäquivalente und ambulante Fälle.",
    "Krankenhaus": "Stammdaten des Krankenhauses und seiner Standorte: Name, Institutionskennzeichen (IK), Standortnummer, Anschrift und Kontakt.",
    "Krankenhaus_Art": "Art des Krankenhauses, unter anderem Universitätsklinikum und Ausbildungsstatus.",
    "Krankenhaustraeger": "Träger des Krankenhauses und Trägerart (öffentlich, freigemeinnützig, privat).",
    "Organisationseinheiten_Fachabteilungen": "Fachabteilungen des Standorts mit Fachabteilungsschlüssel, Betten, Fallzahlen, Diagnosen (ICD), Prozeduren (OPS) und Leistungsangeboten.",
    "Personal_des_Krankenhauses": "Personalausstattung des Krankenhauses: Ärztinnen und Ärzte, Fachärzte, Pflegepersonal, spezielles therapeutisches Personal, jeweils in Vollkräften.",
    "Medizinisch_Pflegerische_Leistungsangebote": "Medizinisch-pflegerische Leistungsangebote des Standorts (MP-Schlüssel).",
    "Nicht_Medizinische_Leistungsangebote": "Nicht-medizinische Serviceangebote des Standorts (NM-Schlüssel).",
    "Apparative_Ausstattung": "Apparative Ausstattung des Standorts (Großgeräte wie CT, MRT, Linksherzkathetermessplatz), inklusive Notfallverfügbarkeit.",
    "Barrierefreiheit": "Aspekte der Barrierefreiheit des Standorts und Ansprechpersonen für Menschen mit Beeinträchtigung.",
    "Akademische_Lehre": "Akademische Lehre und wissenschaftliche Tätigkeit des Krankenhauses.",
    "Ausbildung_andere_Heilberufe": "Ausbildung in anderen Heilberufen am Standort.",
    "Qualitaetssicherung": "Ergebnisse der externen Qualitätssicherung, Qualitätsindikatoren und Bewertungen.",
    "Mindestmengen": "Mindestmengenrelevante Leistungen und erbrachte Leistungsmengen des Standorts.",
    "Hygiene": "Hygiene- und Infektionsmanagement des Standorts, Personal und Maßnahmen.",
    "Patientenmanagement": "Patienten- und Beschwerdemanagement des Standorts.",
    "Umgang_mit_Risiken": "Klinisches Risikomanagement, Fehlermeldesysteme und Sicherheitsmaßnahmen.",
    "Datengestuetzte_Qualitaetssicherung": "Datengestützte Qualitätssicherung (DeQS): Leistungsbereiche, Fallzahlen und Dokumentationsraten je Standort.",
}


def flatten_gba_qualitaetsbericht(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per top-level section of the G-BA Qualitätsbericht XML schema. The
    section list is read out of a real report (so it tracks the actual data), the German
    gloss comes from GBA_SECTIONS, and everything else is derived from the archive names."""
    import xml.etree.ElementTree as ET
    import zipfile

    raw = source["folder"] / "raw"
    archives = sorted(raw.glob("xml_*.zip"))
    if not archives:
        return []
    years = sorted(int(re.search(r"(\d{4})", a.name).group(1)) for a in archives)

    sections: Dict[str, int] = {}
    hospitals = 0
    with zipfile.ZipFile(archives[-1]) as archive:
        names = [n for n in archive.namelist() if n.endswith("-xml.xml")]
        hospitals = len(names)
        # A large report exercises most of the schema; a tiny one would under-report it.
        biggest = max(names, key=lambda n: archive.getinfo(n).file_size)
        root = ET.fromstring(archive.read(biggest))
        subsections: Dict[str, Dict[str, int]] = {}
        for child in root:
            tag = re.sub(r"\{.*?\}", "", child.tag)
            sections[tag] = sections.get(tag, 0) + len(list(child.iter()))
            # One level deeper: "Personal_des_Krankenhauses" alone does not tell a searcher that
            # nursing staff, physicians and therapists are each recorded separately.
            for grandchild in child:
                sub = re.sub(r"\{.*?\}", "", grandchild.tag)
                subsections.setdefault(tag, {})
                subsections[tag][sub] = subsections[tag].get(sub, 0) + len(list(grandchild.iter()))

    records: List[Dict[str, Any]] = []
    for tag, field_count in sorted(sections.items()):
        if tag in {"Einleitung"}:  # software/contact boilerplate, not data
            continue
        gloss = GBA_SECTIONS.get(tag, "")
        label = tag.replace("_", " ")
        records.append(
            make_record(
                source_key="gba_qualitaetsbericht",
                link_level="dataset",
                source_label="Qualitätsberichte der Krankenhäuser (G-BA)",
                item_type="register_attribute",
                item_id=f"gba:{tag}",
                variable_name=tag,
                label=label,
                dataset_label="Qualitätsbericht XML",
                theme="Gesundheit",
                description=join_nonempty([
                    gloss or f"Abschnitt '{label}' des strukturierten Qualitätsberichts.",
                    f"Berichtsteil im maschinenlesbaren Qualitätsbericht nach §136b SGB V, je Krankenhausstandort "
                    f"(Berichtsjahr {years[-1]}: {hospitals} Standorte, Berichtsjahre {years[0]}-{years[-1]})."
                    + (f" Der Abschnitt umfasst rund {field_count} Einzelfelder." if field_count > 3 else ""),
                    "Standortgenau (Anschrift, Institutionskennzeichen), damit auf Gemeinde-, Kreis- oder "
                    "Postleitzahlebene aggregierbar.",
                ]),
                spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU", "Kreise", "NUTS3", "Bundesländer", "NUTS1"],
                year_start=years[0],
                year_end=years[-1],
                years_text=f"{years[0]}-{years[-1]}",
                source_url="https://www.g-ba.de/themen/qualitaetssicherung/datenerhebung-zur-qualitaetssicherung/datenerhebung-qualitaetsbericht/",
                indicator_url="https://www.deutsches-krankenhaus-verzeichnis.de/app/suche",
                access_modes=["direct file download", "web UI / search form only"],
                update_frequency="jährlich",
                api_hint=(
                    f"Element <{tag}> im Qualitätsbericht-XML. Jahresarchive xml_<Jahr>.zip enthalten je Standort "
                    "eine XML-Datei; die Referenzdatenbank des G-BA liefert die Rohdaten."
                ),
            )
        )

    for parent, children in sorted(subsections.items()):
        if parent in {"Einleitung"}:
            continue
        for child_tag, field_count in sorted(children.items()):
            if child_tag in {"Kontakt_Person_lang", "Datensatz", "Software"} or field_count < 2:
                continue
            readable = child_tag.replace("_", " ")
            records.append(
                make_record(
                    source_key="gba_qualitaetsbericht",
                    source_label="Qualitätsberichte der Krankenhäuser (G-BA)",
                    item_type="register_attribute",
                    item_id=f"gba:{parent}:{child_tag}",
                    variable_name=child_tag,
                    label=f"{readable} ({parent.replace('_', ' ')})",
                    dataset_label=f"Qualitätsbericht: {parent.replace('_', ' ')}",
                    theme="Gesundheit",
                    description=join_nonempty([
                        f"Unterabschnitt '{readable}' im Berichtsteil '{parent.replace('_', ' ')}' des "
                        f"strukturierten Qualitätsberichts nach §136b SGB V.",
                        GBA_SECTIONS.get(parent, ""),
                        f"Der Unterabschnitt umfasst rund {field_count} Einzelfelder je Krankenhausstandort."
                        if field_count > 3 else "",
                        "Standortgenau (Anschrift, Institutionskennzeichen) und damit auf Gemeinde-, "
                        "Kreis- oder Postleitzahlebene aggregierbar.",
                    ]),
                    spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "Kreise", "Bundesländer"],
                    nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU", "Kreise", "NUTS3",
                                 "Bundesländer", "NUTS1"],
                    year_start=years[0],
                    year_end=years[-1],
                    years_text=f"{years[0]}-{years[-1]}",
                    source_url="https://www.g-ba.de/themen/qualitaetssicherung/datenerhebung-zur-qualitaetssicherung/datenerhebung-qualitaetsbericht/",
                    indicator_url="https://www.deutsches-krankenhaus-verzeichnis.de/app/suche",
                    link_level="dataset",
                    access_modes=["direct file download", "web UI / search form only"],
                    update_frequency="jährlich",
                    api_hint=f"Element <{child_tag}> unter <{parent}> im Qualitätsbericht-XML.",
                )
            )
    return records


# Bundes-Klinik-Atlas: attribute gloss, keyed on the XML attribute name.
BKA_ATTRIBUTES: Dict[str, str] = {
    "Name": "Name des Krankenhausstandorts.",
    "Strasse": "Straßenanschrift des Standorts.",
    "PLZ": "Postleitzahl des Standorts.",
    "Ort": "Ort des Standorts.",
    "Land": "Bundesland des Standorts.",
    "Laengengrad": "Längengrad des Standorts (WGS84); erlaubt Distanz- und Erreichbarkeitsberechnungen.",
    "Breitengrad": "Breitengrad des Standorts (WGS84); erlaubt Distanz- und Erreichbarkeitsberechnungen.",
    "GeoreferenzOst": "Ostwert der Georeferenz des Standorts (UTM).",
    "GeoreferenzNord": "Nordwert der Georeferenz des Standorts (UTM).",
    "TraegerArt": "Trägerart des Standorts (öffentlich, freigemeinnützig, privat).",
    "Kinderklinik": "Kennzeichen, ob der Standort eine Kinderklinik ist.",
    "Sicherstellungsauftrag": "Kennzeichen, ob der Standort einen Sicherstellungszuschlag/-auftrag hat.",
    "AnzahlFAB": "Anzahl der Fachabteilungen am Standort.",
    "AnzahlBetten": "Anzahl der Betten am Standort; Grundlage für Bettendichte je Einwohner.",
    "AnzahlTeilstationaerBehandlungsplaetze": "Anzahl teilstationärer Behandlungsplätze am Standort.",
    "AnzahlFaelle": "Anzahl der Behandlungsfälle am Standort.",
    "AnzahlPfleger": "Anzahl der Pflegekräfte am Standort (Vollkräfte).",
    "PflegePersonalQuotient": "Pflegepersonalquotient des Standorts (Verhältnis Pflegeaufwand zu Pflegepersonal).",
    "Stufe": "Stufe der Notfallversorgung des Standorts (0 bis 3).",
    "Schwerverletztenversorgung": "Teilnahme des Standorts an der Schwerverletztenversorgung.",
    "Kinder": "Notfallversorgung für Kinder am Standort.",
    "Spezialversorgung": "Spezialversorgungsmodule der Notfallversorgung am Standort.",
    "StrokeUnit": "Vorhandensein einer Stroke Unit (Schlaganfalleinheit) am Standort.",
    "ChestPainUnit": "Vorhandensein einer Chest Pain Unit (Brustschmerzeinheit) am Standort.",
    "StufeNichtVereinbart": "Kennzeichen, dass keine Stufe der Notfallversorgung vereinbart wurde.",
    "Schluessel": "Merkmal der Barrierefreiheit des Standorts (Schlüssel je Aspekt).",
    "Shortener": "Kurzbezeichnung eines Zertifikats des Standorts.",
    "Modul": "Modul eines Zertifikats des Standorts.",
    "GueltigkeitEnde": "Ende der Gültigkeit eines Zertifikats des Standorts.",
    "STOID": "Standort-ID des Krankenhausstandorts (bundeseinheitlicher Standortbezeichner).",
    "FABID": "Fachabteilungsschlüssel einer Fachabteilung des Standorts.",
    "Bezeichnung": "Bezeichnung der Fachabteilung des Standorts.",
    "Gruppe": "Erkrankungsgruppe, für die der Standort Fallzahlen ausweist.",
    "Anzahl": "Fallzahl des Standorts für eine Erkrankung bzw. Erkrankungsgruppe; Grundlage für Spezialisierungs- und Versorgungsanalysen.",
    "Leistungsbereich": "Mindestmengenrelevanter Leistungsbereich (z. B. komplexe Eingriffe), für den der Standort eine Leistungsberechtigung ausweist.",
    "Leistungsberechtigung": "Ob der Standort für einen mindestmengenrelevanten Leistungsbereich leistungsberechtigt ist.",
    "SondergenehmigungLand": "Ob das Land eine Sondergenehmigung für den Leistungsbereich erteilt hat.",
    "GeoreferenzZone": "UTM-Zone der Georeferenz des Standorts.",
    "Telefon": "Telefonnummer des Standorts.",
    "EMail": "E-Mail-Adresse des Standorts.",
    "URL": "Website des Standorts.",
}


def flatten_bundes_klinik_atlas(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The Bundes-Klinik-Atlas open-data export (this replaces the discontinued Weisse
    Liste in the workbook). Rows are hospital sites, so the indexable items are the
    site-level attributes, read out of the export XML itself."""
    import xml.etree.ElementTree as ET
    import zipfile

    archive_path = next((p for p in (source["folder"] / "raw").glob("Bundes-Klinik-Atlas*.zip")), None)
    if archive_path is None:
        return []

    with zipfile.ZipFile(archive_path) as archive:
        xml_name = next((n for n in archive.namelist() if n.endswith(".xml") and "__MACOSX" not in n), None)
        if xml_name is None:
            return []
        export_date = re.search(r"(\d{4})(\d{2})(\d{2})", archive_path.name)
        root = ET.fromstring(archive.read(xml_name))

    sites = len(root.findall(".//Standort"))
    groups: Dict[str, Dict[str, Any]] = {}
    for element in root.iter():
        tag = re.sub(r"\{.*?\}", "", element.tag)
        for attribute in element.attrib:
            groups.setdefault(attribute, {"element": tag, "count": 0})
            groups[attribute]["count"] += 1

    year = int(export_date.group(1)) if export_date else None
    records: List[Dict[str, Any]] = []
    for attribute, info in sorted(groups.items()):
        gloss = BKA_ATTRIBUTES.get(attribute, "")
        section = info["element"].replace("Standort", "").replace("Kontakt", "Kontakt ") or info["element"]
        records.append(
            make_record(
                source_key="bundes_klinik_atlas",
                link_level="dataset",
                source_label="Bundes-Klinik-Atlas (IQTIG, Open Data)",
                item_type="register_attribute",
                item_id=f"bundesklinikatlas:{info['element']}:{attribute}",
                variable_name=attribute,
                label=f"{attribute} ({section})",
                dataset_label=info["element"],
                theme="Gesundheit",
                description=join_nonempty([
                    gloss or f"Merkmal '{attribute}' im Element <{info['element']}> des Bundes-Klinik-Atlas-Exports.",
                    f"Standortgenaues Merkmal im offenen Datenexport des Bundes-Klinik-Atlas "
                    f"({sites} Krankenhausstandorte, Stand {export_date.group(0) if export_date else 'unbekannt'}), "
                    "mit Koordinaten je Standort, damit auf Gemeinde-, Kreis- oder Postleitzahlebene aggregierbar.",
                ]),
                spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU", "Kreise", "NUTS3", "Bundesländer", "NUTS1"],
                year_start=year,
                year_end=year,
                years_text=str(year) if year else "",
                source_url="https://bundes-klinik-atlas.de/",
                indicator_url="https://bundes-klinik-atlas.de/open-data/",
                access_modes=["direct file download", "web UI / search form only"],
                update_frequency="laufend",
                api_hint=f"Attribut @{attribute} am Element <{info['element']}> im TVERZ-Export (XML + XSD).",
            )
        )
    return records


OEPNV_ITEMS = [
    ("haltestellen", "Haltestellen und Stationen",
     "Haltestellenverzeichnis mit Koordinaten, Namen und Verkehrsmitteln; Grundlage für Distanz- und "
     "Erreichbarkeitsanalysen zum nächsten ÖPNV-Zugang."),
    ("fahrplandaten_gtfs", "Fahrplandaten (GTFS / NeTEx)",
     "Soll-Fahrplandaten der Verkehrsverbünde als GTFS bzw. NeTEx: Linien, Routen, Fahrten, Abfahrtszeiten, "
     "Betriebstage; erlaubt Bedienungshäufigkeit und Taktdichte je Haltestelle oder Gebiet."),
    ("echtzeitdaten", "Echtzeit-Abfahrten und Verspätungen",
     "Echtzeitinformationen der Verkehrsunternehmen zu Abfahrten, Verspätungen und Ausfällen über die "
     "OpenService-Schnittstelle (EFA/TRIAS)."),
    ("stoerungen_aufzuege", "Betriebsstörungen von Aufzügen und Rolltreppen",
     "Meldungen zu Störungen von Aufzügen und Rolltreppen an Stationen; Indikator für barrierefreie Zugänglichkeit."),
    ("fahrplanauskunft", "Fahrplanauskunft und Routing (EFA / TRIAS)",
     "Verbindungsauskunft zwischen zwei Orten inklusive Umsteigepunkten und Reisezeit; erlaubt die Berechnung "
     "von ÖPNV-Reisezeiten zwischen Gebietseinheiten."),
    ("abfahrtsmonitor", "Abfahrtsmonitor je Haltestelle",
     "Abfahrten je Haltestelle in einem Zeitfenster (XML_DM_REQUEST); Grundlage für Bedienungshäufigkeit."),
]


def flatten_opendata_oepnv(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """opendata-oepnv.de: the dataset catalogue is public even though downloading a
    dataset needs a free account, so the real German dataset names are indexed from the
    saved catalogue page, each with its own deep link. The API description Konstantin
    supplied provides the access note."""
    raw = source["folder"] / "raw"
    description_path = raw / "description_api.txt"
    api_text = clean(description_path.read_text(encoding="utf-8", errors="replace"))[:600] if description_path.exists() else ""

    records: List[Dict[str, Any]] = []
    catalogue_path = raw / "datensaetze.html"
    seen: set = set()
    if catalogue_path.exists():
        page = catalogue_path.read_text(encoding="utf-8", errors="replace")
        # Each dataset card is a link whose href carries tx_vrrkit_view[dataset_name].
        for href, inner in re.findall(r'<a[^>]+href="([^"]*dataset_name[^"]*)"[^>]*>(.*?)</a>', page, re.S):
            name = strip_tags(inner)
            slug_match = re.search(r"dataset_name(?:%5D|\])=([^&\"]+)", href)
            if not slug_match or not name or name.lower() in {"weiterlesen", "mehr", "details"}:
                continue
            slug = html.unescape(slug_match.group(1))
            if slug in seen:
                continue
            seen.add(slug)
            url = html.unescape(href)
            if url.startswith("?"):
                url = "https://www.opendata-oepnv.de/ht/de/datensaetze" + url
            elif url.startswith("/"):
                url = "https://www.opendata-oepnv.de" + url
            elif not url.startswith("http"):
                url = "https://www.opendata-oepnv.de/" + url
            kind = ("Soll-Fahrplandaten" if "fahrplan" in slug else
                    "Haltestellendaten" if "haltestelle" in slug else
                    "Liniendaten" if "linien" in slug else "Datensatz")
            records.append(
                make_record(
                    source_key="opendata_oepnv",
                    source_label="Open Data ÖPNV (mCLOUD / Verkehrsverbünde)",
                    item_type="dataset",
                    item_id=f"opendata_oepnv:{slug}",
                    variable_name=slug,
                    label=name,
                    dataset_label=kind,
                    theme="Verkehr / Mobilität",
                    description=join_nonempty([
                        f"Datensatz '{name}' im Portal Open Data ÖPNV ({kind}).",
                        "Soll-Fahrplandaten enthalten Linien, Routen, Fahrten und Abfahrtszeiten (GTFS bzw. NeTEx) "
                        "und erlauben Bedienungshäufigkeit und Taktdichte je Haltestelle oder Gebiet."
                        if kind == "Soll-Fahrplandaten" else
                        "Haltestellendaten enthalten Haltestellen und Stationen mit Koordinaten, Namen und "
                        "Verkehrsmitteln; Grundlage für Distanz- und Erreichbarkeitsanalysen zum nächsten ÖPNV-Zugang."
                        if kind == "Haltestellendaten" else
                        "Liniendaten beschreiben die Linien eines Verbundes, teils mit Haltestellenreferenz.",
                        "Download nach kostenfreier Registrierung auf opendata-oepnv.de.",
                    ]),
                    spatial_levels=["Adressen/Koordinaten", "Gemeinden", "Weitere Gliederungen"],
                    nuts_levels=["Adressen/Koordinaten", "Gemeinden", "LAU"],
                    year_start=source["coverage_start_year"],
                    year_end=source["coverage_end_year"],
                    years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                    source_url=source["url"],
                    indicator_url=url,
                    link_level="dataset",
                    access_modes=["direct file download", "on request / registration needed"],
                    update_frequency=source["update_frequency"] or "laufend",
                    api_hint=f"Datensatz-Slug '{slug}' auf opendata-oepnv.de; Download nach Login.",
                )
            )

    # The live API products are not datasets in the catalogue, so they are added on top.
    for code, label, gloss in OEPNV_ITEMS:
        records.append(
            make_record(
                source_key="opendata_oepnv",
                source_label="Open Data ÖPNV (mCLOUD / Verkehrsverbünde)",
                item_type="regional_indicator",
                item_id=f"opendata_oepnv:api:{code}",
                variable_name=code,
                label=label,
                dataset_label="OpenService-Schnittstelle",
                theme="Verkehr / Mobilität",
                description=join_nonempty([
                    gloss,
                    "Zugang: die OpenService-Schnittstelle des VRR ist ohne Registrierung nutzbar "
                    "(EFA-JSON/rapidJSON oder TRIAS); Datensatzdownloads über opendata-oepnv.de nach Login.",
                ]),
                stats_summary=api_text,
                spatial_levels=["Adressen/Koordinaten", "Gemeinden", "Weitere Gliederungen"],
                nuts_levels=["Adressen/Koordinaten", "Gemeinden", "LAU"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url=source["url"],
                link_level="portal",
                access_modes=["machine-readable API", "on request / registration needed"],
                update_frequency=source["update_frequency"] or "laufend",
                api_hint=(
                    "OpenService ohne Registrierung: https://openservice-test.vrr.de/openservice/"
                    "XML_DM_REQUEST?outputFormat=rapidJSON&version=10.4.18.18 ; TRIAS: "
                    "https://openservice-test.vrr.de/opendataT/trias"
                ),
            )
        )
    return records


GERMAN_COMPANY_FIELDS = [
    ("name", "Firmenname", "Eingetragener Name des Unternehmens."),
    ("street", "Straßenanschrift", "Straße und Hausnummer des Unternehmenssitzes; adressgenau georeferenzierbar."),
    ("zip", "Postleitzahl", "Postleitzahl des Unternehmenssitzes; erlaubt Aggregation auf PLZ-, Gemeinde- und Kreisebene."),
    ("city", "Ort", "Ort des Unternehmenssitzes."),
    ("hrCourt", "Registergericht", "Zuständiges Handelsregistergericht des Unternehmens."),
    ("hrNumber", "Handelsregisternummer", "Handelsregisternummer des Unternehmens."),
    ("hrType", "Registerart", "Art des Registereintrags (HRA, HRB)."),
    ("lei", "Legal Entity Identifier (LEI)", "Globaler LEI-Code des Unternehmens."),
    ("ebid", "EBID", "European Business Identifier des Unternehmens."),
    ("active", "Aktiv-Status", "Ob das Unternehmen aktiv oder erloschen ist; erlaubt Gründungs- und Schließungsanalysen."),
    ("url", "Unternehmenswebsite", "Website des Unternehmens."),
    ("id", "Implisense-ID", "Interne Unternehmens-ID des Anbieters, Schlüssel für Detailabfragen."),
]


def flatten_german_companies(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """RapidAPI company-data lookup: rows are companies, so the indexable items are the
    company attributes that can be queried and returned (verified against a live sample
    response saved in raw/api_response_sample.json)."""
    records: List[Dict[str, Any]] = []
    for code, label, gloss in GERMAN_COMPANY_FIELDS:
        records.append(
            make_record(
                source_key="german_companies",
                link_level="dataset",
                source_label="German Company Data (Implisense, RapidAPI)",
                item_type="register_attribute",
                item_id=f"german_companies:{code}",
                variable_name=code,
                label=f"{label} (Unternehmensdaten)",
                dataset_label="German Company Data API",
                theme="Wirtschaft und Unternehmen",
                description=join_nonempty([
                    gloss,
                    "Merkmal der Unternehmensdatenbank deutscher Firmen; adressgenau und damit auf PLZ-, "
                    "Gemeinde- oder Kreisebene aggregierbar (Unternehmensdichte, Branchenbesatz, Standortwahl).",
                    "Zugang über einen RapidAPI-Schlüssel; die Abfrage erfolgt als POST auf /lookup.",
                ]),
                spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden"],
                nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU"],
                source_url=source["url"],
                indicator_url=source["url"],
                access_modes=["machine-readable API", "on request / registration needed"],
                update_frequency=source["update_frequency"] or "laufend",
                api_hint=(
                    "POST https://german-company-data.p.rapidapi.com/lookup?size=N mit Headern x-rapidapi-host "
                    "und x-rapidapi-key; Filterfelder: query, name, street, zip, city, hrCourt, hrNumber, hrType, "
                    "lei, ebid, email, url, active."
                ),
            )
        )
    return records

# One entry per GENESIS instance whose catalogue scripts/fetch_genesis_catalogue.py wrote.
# `link_verified` records whether the deep link could be checked from here: regionalstatistik
# is a server-rendered JSF app (a bogus code returns a visibly smaller error page, so the
# pattern is proven), while the federal and Zensus portals are client-rendered SPAs that
# return the same 2 KB shell for every code, valid or not. Those links use the documented
# route form and are flagged as unverified rather than silently trusted.
GENESIS_INSTANCES = {
    "regionalstatistik": {
        "source_key": "regionalstatistik",
        "source_label": "Regionalstatistik / GENESIS (Regionaldatenbank)",
        "dataset_label": "GENESIS-Tabelle (Regionaldatenbank)",
        "url": "https://www.regionalstatistik.de/genesis/online?operation=table&code={code}",
        "portal": "https://www.regionalstatistik.de/genesis/online",
        "link_verified": True,
        "default_levels": ["Kreise & kreisfreie Städte"],
        "note": "Abrufbar in der Regionaldatenbank Deutschland; Download als CSV/XLSX nach "
                "kostenfreier Anmeldung oder über die GENESIS-Webservice-API.",
    },
    "destatis": {
        "source_key": "genesis_bund",
        "source_label": "GENESIS-Online (Statistisches Bundesamt)",
        "dataset_label": "GENESIS-Tabelle (Bund)",
        "url": "https://www-genesis.destatis.de/genesis/online?operation=table&code={code}",
        "portal": "https://www-genesis.destatis.de/genesis/online",
        # Client-rendered portal: checked by hand in a browser on 2026-08-25.
        "link_verified": True,
        "default_levels": ["Bundesland"],
        "note": "Bundesdatenbank: die meisten Tabellen liegen auf Bundes- oder Länderebene, "
                "einzelne auch tiefer. Download als CSV/XLSX nach kostenfreier Anmeldung oder "
                "über die GENESIS-Webservice-API.",
    },
    "zensus": {
        "source_key": "zensus2022",
        "source_label": "Zensus 2022 (Statistische Ämter des Bundes und der Länder)",
        "dataset_label": "Zensus-2022-Tabelle",
        "url": "https://ergebnisse.zensus2022.de/datenbank/online/table/{code}",
        "portal": "https://ergebnisse.zensus2022.de/",
        # Client-rendered portal: checked by hand in a browser on 2026-08-25.
        "link_verified": True,
        # Deliberately empty: in Zensus 2022 the regional level is encoded in the opaque table
        # code, not in the title, and it ranges from Bundesland to 100 m grid cell. Guessing a
        # level here would put wrong values behind the spatial filter.
        "default_levels": [],
        "note": "Zensus 2022: Gebäude, Wohnungen, Haushalte und Personenmerkmale, je nach "
                "Merkmal bis auf Gemeinde- oder Gitterzellenebene. Die räumliche Ebene steckt "
                "im Tabellencode, nicht in einem Parameter.",
    },
}

# Zensus 2022 encodes the regional level in the opaque table code, so scripts/resolve_zensus_levels.py
# resolves it per table through metadata/table. GEO variable -> our canonical level vocabulary.
ZENSUS_GEO_LEVELS = {
    "GEODL": "Bund",
    "GEOBL": "Bundesland",
    "GEORB": "Regierungsbezirke",
    "GEOLK": "Kreise & kreisfreie Städte",
    "GEOGM": "Gemeinden und Verbandsgemeinden",
    "GEOVB": "Gemeinden und Verbandsgemeinden",
    "GEOBZ": "Bezirke",
    "GEOWK": "weitere räumliche Gliederungen",
    "GEOEV": "weitere räumliche Gliederungen",
    "GEORK": "weitere räumliche Gliederungen",
}

# Coarse to fine, so a table that carries several geo columns can be described by its finest.
LEVEL_GRANULARITY = [
    "Bund", "Bundesland", "Regierungsbezirke", "Kreise & kreisfreie Städte",
    "Gemeinden und Verbandsgemeinden", "Adressen / Koordinaten",
]

DEPTH_MARKERS = [
    ("gemeinde", "Gemeinden und Verbandsgemeinden"),
    ("kreis", "Kreise & kreisfreie Städte"),
    ("krfr", "Kreise & kreisfreie Städte"),
    ("regierungsbezirk", "Regierungsbezirke"),
    ("bundesl", "Bundesland"),
    ("länder", "Bundesland"),
    ("laender", "Bundesland"),
    ("wahlkreis", "weitere räumliche Gliederungen"),
    ("gitterzelle", "weitere räumliche Gliederungen"),
    ("raster", "weitere räumliche Gliederungen"),
]


def flatten_genesis_tables(source: Dict[str, Any], instances: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Table-level records for the GENESIS instance(s) whose catalogue sits in this source folder.

    A table code is the finest linkable unit these portals offer, and the regional depth is
    usually spelled out in the table title ("... regionale Tiefe: Kreise und krfr. Städte",
    "Gebietsfläche: Kreise"), which is what tags the spatial level."""
    raw = source["folder"] / "raw"
    records: List[Dict[str, Any]] = []

    resolved_levels: Dict[str, List[List[Any]]] = {}
    levels_path = raw / "zensus_table_levels.json"
    if levels_path.exists():
        resolved_levels = {code: entry.get("geo") or []
                           for code, entry in json.loads(levels_path.read_text(encoding="utf-8")).items()}

    for instance in (instances or list(GENESIS_INSTANCES)):
        config = GENESIS_INSTANCES[instance]
        path = raw / f"genesis_catalogue_{instance}.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        # Nearly every Zensus table has a "Deutschland" column, so naming the level in the label
        # is only useful when it is finer than national or when the title itself repeats.
        title_counts: Dict[str, int] = {}
        for table in payload.get("tables") or []:
            key = re.sub(r"\s+", " ", clean(table.get("Content"))).lower()
            title_counts[key] = title_counts.get(key, 0) + 1

        for table in payload.get("tables") or []:
            code = clean(table.get("Code"))
            title = re.sub(r"\s+", " ", clean(table.get("Content")))
            if not code or not title:
                continue
            statistic_code = clean(table.get("StatistikCode"))
            statistic_name = clean(table.get("StatistikContent"))

            depth_text = ""
            for marker in ("regionale Tiefe", "regionale Ebene"):
                if marker in title:
                    depth_text = title.split(marker, 1)[1].strip(" :;-")
                    break
            lowered = (depth_text or title).lower()
            levels = sorted({level for needle, level in DEPTH_MARKERS if needle in lowered})

            # A resolved Zensus level beats anything guessed from the title.
            geo_labels: List[str] = []
            resolved_canonical: List[str] = []
            for geo_code, geo_label, _values in resolved_levels.get(code, []):
                canonical = ZENSUS_GEO_LEVELS.get(str(geo_code)[:5])
                if canonical:
                    levels.append(canonical)
                    resolved_canonical.append(canonical)
                if geo_label:
                    geo_labels.append(clean(geo_label))
            levels = sorted(set(levels))

            # The finest resolved level, and the label of that level, for the suffix below.
            finest = ""
            finest_label = ""
            for candidate, label_text in zip(resolved_canonical, geo_labels):
                if (candidate in LEVEL_GRANULARITY and
                        (not finest or LEVEL_GRANULARITY.index(candidate) > LEVEL_GRANULARITY.index(finest))):
                    finest, finest_label = candidate, label_text
            title_repeats = title_counts.get(re.sub(r"\s+", " ", title).lower(), 0) > 1 if instance == "zensus" else False
            # Church units and constituencies are not on the granularity ladder, but they are
            # exactly what tells the repeated "Personen: Religion" tables apart.
            if not finest_label and title_repeats:
                finest_label = next((label for label in reversed(geo_labels)
                                     if label and label != "Deutschland"), "")
            name_the_level = instance == "zensus" and finest_label and (finest not in {"", "Bund"} or title_repeats)
            mapped = map_spatial(levels or config["default_levels"])

            period = clean(table.get("Time")) or clean(table.get("Zeitraum"))
            years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", f"{period} {title}")]

            # A Zensus "period" of "09.05.2011 - 15.05.2022" is not an interval: it means the
            # table carries both census reference dates. Shown raw, a Zensus 2022 hit looks like
            # it is from 2011. Name the censuses instead.
            census_note = ""
            if instance == "zensus":
                has_2011 = "09.05.2011" in period or "09.05.2011" in statistic_name
                has_2022 = "15.05.2022" in period or "15.05.2022" in statistic_name
                if has_2011 and has_2022:
                    period = "Zensus 2011 und Zensus 2022 (Stichtage 09.05.2011 und 15.05.2022)"
                    census_note = "Die Tabelle weist beide Zensen aus und erlaubt damit den Vergleich 2011 zu 2022."
                elif has_2011:
                    period = "Zensus 2011 (Stichtag 09.05.2011)"
                    census_note = ("Achtung: Tabelle des Zensus 2011, nicht des Zensus 2022. Sie liegt in der "
                                   "Zensus-Datenbank als Vergleichsmaterial.")
                elif has_2022:
                    period = "Zensus 2022 (Stichtag 15.05.2022)"
            records.append(
                make_record(
                    source_key=config["source_key"],
                    source_label=config["source_label"],
                    item_type="table",
                    item_id=f"{instance}_table:{code}",
                    variable_name=code,
                    label=(f"{title} [{finest_label}]" if name_the_level else title),
                    dataset_label=config["dataset_label"],
                    theme=statistic_name or config["source_label"],
                    description=join_nonempty([
                        title,
                        f"Tabelle der Statistik {statistic_code} {statistic_name}." if statistic_name else "",
                        f"Regionale Tiefe: {depth_text}." if depth_text else "",
                        f"Zeitraum: {period}." if period else "",
                        config["note"],
                        "" if config["link_verified"] else
                        "Hinweis: Das Portal ist eine JavaScript-Anwendung; der Tabellenlink folgt der "
                        "dokumentierten Form, konnte aber nicht serverseitig geprüft werden.",
                    ]),
                    stats_summary=f"{statistic_code} {statistic_name}".strip(),
                    spatial_levels=mapped["spatial_levels"],
                    nuts_levels=mapped["nuts_levels"],
                    year_start=min(years) if years else None,
                    year_end=max(years) if years else None,
                    years_text=period,
                    source_url=config["portal"],
                    indicator_url=config["url"].format(code=code),
                    link_level="table",
                    link_verified=config["link_verified"],
                    access_modes=["machine-readable API", "web UI / search form only", "direct file download"],
                    update_frequency=source["update_frequency"],
                    api_hint=(
                        f"GENESIS-Tabelle {code}"
                        + (f" (Statistik {statistic_code})" if statistic_code else "")
                        + ". Abruf über POST /rest/2020/data/tablefile mit dem Token im HTTP-Header "
                        "`username` (nicht als Parameter, sonst Gastzugang)."
                    ),
                )
            )
    return records


UNFALLATLAS_LABELS = {
    "UIDENTSTLAE": "Unfall-ID (laufende Nummer je Unfall)",
    "ID": "Unfall-ID (laufende Nummer je Unfall)",
    "OBJECTID": "Objekt-ID des Unfalldatensatzes",
    "ULAND": "Bundesland des Unfallorts",
    "UREGBEZ": "Regierungsbezirk des Unfallorts",
    "UKREIS": "Kreis des Unfallorts",
    "UGEMEINDE": "Gemeinde des Unfallorts",
    "UJAHR": "Unfalljahr",
    "UMONAT": "Unfallmonat",
    "USTUNDE": "Unfallstunde",
    "UWOCHENTAG": "Wochentag des Unfalls",
    "UKATEGORIE": "Unfallkategorie (Getötete, Schwerverletzte, Leichtverletzte)",
    "UART": "Unfallart (Zusammenstoß, Abkommen von der Fahrbahn, ...)",
    "UTYP1": "Unfalltyp (Fahr-, Abbiege-, Einbiege-, Überschreiten-Unfall, ...)",
    "ULICHTVERH": "Lichtverhältnisse (Tageslicht, Dämmerung, Dunkelheit)",
    "IstStrassenzustand": "Straßenzustand (trocken, nass, winterglatt)",
    "STRZUSTAND": "Straßenzustand (trocken, nass, winterglatt)",
    "IstRad": "Unfall mit Fahrradbeteiligung",
    "IstPKW": "Unfall mit Pkw-Beteiligung",
    "IstFuss": "Unfall mit Fußgängerbeteiligung",
    "IstKrad": "Unfall mit Kraftradbeteiligung",
    "IstGkfz": "Unfall mit Güterkraftfahrzeug-Beteiligung",
    "IstSonstige": "Unfall mit Beteiligung sonstiger Verkehrsmittel",
    "IstSonstig": "Unfall mit Beteiligung sonstiger Verkehrsmittel",
    "LINREFX": "X-Koordinate des Unfallorts (EPSG:25832)",
    "LINREFY": "Y-Koordinate des Unfallorts (EPSG:25832)",
    "XGCSWGS84": "Längengrad des Unfallorts (WGS84)",
    "YGCSWGS84": "Breitengrad des Unfallorts (WGS84)",
    "PLST": "Plausibilitätskennzeichen des Datensatzes",
}


def flatten_unfallatlas(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Unfallatlas: one geocoded record per reported injury accident. Rows are accidents, so
    the indexable items are the accident attributes, taken from the CSV header of the newest
    yearly archive and described from the official Datensatzbeschreibung PDF."""
    import subprocess
    import tempfile
    import zipfile

    raw = source["folder"] / "raw"
    archives = sorted(raw.glob("Unfallorte*_CSV.zip"))
    if not archives:
        return []
    years = sorted({int(m.group(1)) for a in archives if (m := re.search(r"(\d{4})", a.name))})

    with zipfile.ZipFile(archives[-1]) as archive:
        member = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
        if member is None:
            return []
        with archive.open(member) as handle:
            header_line = handle.readline().decode("latin-1")
    # The first cell carries a UTF-8 BOM even though the body is Latin-1.
    columns = [clean(c).lstrip("﻿").lstrip("ï»¿") for c in header_line.strip().split(";")]
    columns = [c for c in columns if c]

    text = ""
    pdf_path = next(iter(raw.glob("*Unfallatlas*.pdf")), None)
    if pdf_path is not None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            subprocess.run(["pdftotext", "-layout", str(pdf_path), str(out_path)],
                           check=True, capture_output=True, timeout=120)
            text = out_path.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f"[warn] unfallatlas: pdftotext failed ({exc}); using column names only")
        finally:
            out_path.unlink(missing_ok=True)

    # The PDF is a "Spaltenname | Inhalt" table: each column name starts a block that runs
    # until the next known column name appears at the start of a line.
    descriptions: Dict[str, str] = {}
    if text:
        lines = text.splitlines()
        starts: List[Tuple[int, str]] = []
        for position, line in enumerate(lines):
            token = line.strip().split(" ")[0] if line.strip() else ""
            if token and token in columns + ["ID"]:
                starts.append((position, token))
        for index, (position, token) in enumerate(starts):
            stop = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
            block = " ".join(l.strip() for l in lines[position:stop])
            block = re.sub(r"https?://\S+", "", block)
            block = re.sub(r"Seite \d+ von \d+|Datensatzbeschreibung", " ", block)
            block = re.sub(r"\s+", " ", block).strip()
            if block and token not in descriptions:
                descriptions[token] = block[:900]

    mapped = map_spatial(["Bundesland", "Regierungsbezirke", "Kreise & kreisfreie Städte",
                          "Gemeinden und Verbandsgemeinden", "Adressen / Koordinaten"])
    records: List[Dict[str, Any]] = []
    for column in columns:
        records.append(
            make_record(
                source_key="unfallatlas",
                source_label="Unfallatlas (Statistische Ämter des Bundes und der Länder)",
                item_type="register_attribute",
                item_id=f"unfallatlas:{column}",
                variable_name=column,
                label=UNFALLATLAS_LABELS.get(column, column),
                dataset_label="Unfallorte (CSV je Jahr)",
                theme="Verkehr / Mobilität",
                description=join_nonempty([
                    descriptions.get(column, "") or f"Merkmal {column} der Unfalldaten.",
                    f"Merkmal im Unfallatlas: jeder Datensatz ist ein polizeilich erfasster Unfall mit "
                    f"Personenschaden, punktgenau georeferenziert (EPSG:25832 und WGS84), Unfalljahre "
                    f"{years[0]}-{years[-1]}. Aggregierbar auf Gemeinde-, Kreis- und Landesebene sowie "
                    "auf Raster oder Straßenabschnitte.",
                    "Die Länder treten schrittweise bei, daher ist die Abdeckung in frühen Jahren unvollständig.",
                ]),
                spatial_levels=mapped["spatial_levels"],
                nuts_levels=mapped["nuts_levels"],
                year_start=years[0],
                year_end=years[-1],
                years_text=f"{years[0]}-{years[-1]}",
                source_url="https://unfallatlas.statistikportal.de/",
                indicator_url="https://unfallatlas.statistikportal.de/",
                link_level="dataset",
                access_modes=["direct file download", "interactive map viewer"],
                update_frequency=source["update_frequency"] or "jährlich",
                api_hint=(
                    f"Spalte {column} in Unfallorte<Jahr>_EPSG25832_CSV.zip (Semikolon-getrennt, Latin-1); "
                    "Koordinaten in XGCSWGS84/YGCSWGS84 bzw. LINREFX/LINREFY (EPSG:25832)."
                ),
            )
        )
    return records


def datenstand_note(hints: List[str]) -> str:
    """The Breitband sheets carry their reference date in a free cell above the header row."""
    found = [h for h in hints if "Datenstand" in h or re.match(r"^\d{2}\.\d{4}$", h)]
    return f"Datenstand: {'; '.join(found)}." if found else ""


def flatten_breitband(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Gigabit-Grundbuch workbooks (Breitbandatlas + Mobilfunk-Monitoring). Each sheet is a
    use case (Privathaushalte, Fläche, Schulen, Autobahnen, ...) and each column after the
    geography block is an availability class, so a record is the pair of the two. The same
    bandwidth classes repeat once per technology block, with the block name in a merged cell
    above the header, so those labels are forward-filled to disambiguate."""
    raw = source["folder"] / "raw"
    books = [
        (raw / "bba_12_2025.xlsx", "Breitbandatlas (Festnetz und Mobilfunk)",
         "Festnetz- und Mobilfunkverfügbarkeit nach Bandbreitenklasse"),
        (raw / "Auswertung_Mobilfunkmonitoring.xlsx", "Mobilfunk-Monitoring",
         "Mobilfunkverfügbarkeit nach Technologie (2G, 4G, 5G, 5G-SA) je Netzbetreiber und über alle Betreiber"),
    ]
    geo_columns = {"ags", "name", "verwaltungsebene", "land", "kreis", "raumkategorie"}
    records: List[Dict[str, Any]] = []
    for path, book_label, book_gloss in books:
        if not path.exists():
            continue
        workbook = pd.ExcelFile(path)
        for sheet in workbook.sheet_names:
            if sheet.lower().startswith("erl"):
                continue
            frame = pd.read_excel(path, sheet_name=sheet, header=None, nrows=12)
            header_row = None
            for index in range(len(frame)):
                if "ags" in [clean(v).lower() for v in frame.iloc[index].tolist()]:
                    header_row = index
                    break
            if header_row is None:
                continue
            header = [clean(v) for v in frame.iloc[header_row].tolist()]
            group_of: Dict[int, str] = {}
            for offset in range(1, 4):
                index = header_row - offset
                if index < 0:
                    continue
                current = ""
                for position, value in enumerate(frame.iloc[index].tolist()):
                    text = clean(value)
                    if text and not text.lower().startswith(("datenstand", "zurück", "angaben")):
                        current = text
                    if current and position not in group_of:
                        group_of[position] = current
            measures = [(position, h) for position, h in enumerate(header)
                        if h and h.lower() not in geo_columns]
            level_hint = [clean(v) for v in frame.iloc[header_row + 1: header_row + 4].stack().tolist()]
            mapped = map_spatial(["Bundesland", "Kreise & kreisfreie Städte",
                                  "Gemeinden und Verbandsgemeinden"])
            seen_measures: set = set()
            for position, measure in measures:
                if measure.lower().startswith(("datenstand", "angaben", "zurück")):
                    continue
                group = group_of.get(position, "")
                if group.lower() in {sheet.lower(), ""} or group.lower().startswith("mobilfunk-monitoring"):
                    group = ""
                measure_label = f"{group} {measure}".strip() if group else measure
                if measure_label in seen_measures:
                    continue
                seen_measures.add(measure_label)
                records.append(
                    make_record(
                        source_key="breitband",
                        source_label="Gigabit-Grundbuch / Breitbandatlas (Bundesnetzagentur, BMDV)",
                        item_type="regional_indicator",
                        item_id=f"breitband:{path.stem}:{sheet}:{measure_label}",
                        variable_name=f"{sheet}|{measure_label}",
                        label=f"{measure_label} ({sheet})",
                        dataset_label=book_label,
                        theme="Digitalisierung",
                        description=join_nonempty([
                            f"Verfügbarkeit '{measure_label}' für die Nutzungsart '{sheet}'. {book_gloss}.",
                            "Ausgewiesen als Versorgungsgrad in Prozent je Gebietseinheit, von Bundes- bis "
                            "Gemeindeebene (AGS), mit Raumkategorie; zusätzlich liegen Rasterdaten "
                            "(Gitterzellen, GeoPackage) und Mobilfunk-Geodaten vor.",
                            datenstand_note(level_hint),
                        ]),
                        spatial_levels=mapped["spatial_levels"] + ["Weitere Gliederungen"],
                        nuts_levels=mapped["nuts_levels"],
                        year_start=2025,
                        year_end=2025,
                        years_text="Stand 12.2025",
                        source_url="https://gigabitgrundbuch.bund.de/",
                        indicator_url="https://gigabitgrundbuch.bund.de/",
                        link_level="dataset",
                        access_modes=["direct file download", "interactive map viewer"],
                        update_frequency=source["update_frequency"] or "halbjährlich",
                        api_hint=f"Spalte '{measure}' (Block '{group or sheet}') im Tabellenblatt '{sheet}' von {path.name}.",
                    )
                )
    return records


def flatten_ba_arbeitsmarkt_kommunal(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """'Arbeitsmarkt kommunal': one XLSX per municipality inside a district archive, all with
    the same indicator set on the 'Daten' sheet. Section headers sit in column A and the
    breakdowns in column B, so a record is the pair."""
    import io
    import zipfile

    archive_path = next(iter((source["folder"] / "raw").glob("amk-*.zip")), None)
    if archive_path is None:
        return []
    with zipfile.ZipFile(archive_path) as archive:
        member = next((n for n in archive.namelist() if n.lower().endswith(".xlsx")), None)
        if member is None:
            return []
        payload = archive.read(member)
        municipalities = sum(1 for n in archive.namelist() if n.lower().endswith(".xlsx"))

    frame = pd.read_excel(io.BytesIO(payload), sheet_name="Daten", header=None)
    years = sorted({int(v) for v in frame.iloc[6].tolist()
                    if str(v).replace(".0", "").isdigit() and 1990 < float(v) < 2100})

    records: List[Dict[str, Any]] = []
    section = ""
    seen: set = set()
    for _, row in frame.iterrows():
        first = clean(str(row.get(0))).replace("\n", " ")
        second = clean(str(row.get(1))).replace("\n", " ")
        values = [clean(v) for v in row.tolist()[2:]]
        has_value = any(re.match(r"^-?[\d.,]+$", v) for v in values if v)
        if first and not has_value and not second:
            is_place_header = bool(re.match(r"^\d{5,}", first)) or "Gebietsstand" in first
            if len(first) > 12 and not is_place_header and not first.startswith(("Statistik", "Quelle", "Stand", "©")):
                section = first
            continue
        label_part = second or first
        if not label_part or label_part in {"dar.", "nan", "Merkmale"} or not has_value:
            continue
        label = f"{section}: {label_part}" if section else label_part
        if label in seen:
            continue
        seen.add(label)
        records.append(
            make_record(
                source_key="ba_arbeitsmarkt_kommunal",
                source_label="Arbeitsmarkt kommunal (Bundesagentur für Arbeit)",
                item_type="regional_indicator",
                item_id=f"amk:{len(seen):03d}",
                variable_name=f"AMK-{len(seen):03d}",
                label=label[:120],
                dataset_label=section or "Arbeitsmarkt kommunal",
                theme="Arbeitsmarkt & Beschäftigung",
                description=join_nonempty([
                    f"{label}. Merkmal der BA-Reihe 'Arbeitsmarkt kommunal', die je Kreis ein Archiv mit "
                    f"einer Tabelle pro Gemeinde liefert (Beispielarchiv: {municipalities} Gemeinden).",
                    f"Jahresreihe {years[0]}-{years[-1]}." if years else "",
                    "Gemeindescharfe Arbeitsmarktdaten, die in INKAR und im Regionalatlas nur auf "
                    "Kreisebene vorliegen.",
                ]),
                stats_summary=section,
                spatial_levels=["Gemeinden", "Kreise"],
                nuts_levels=["Gemeinden", "LAU", "Kreise", "NUTS3"],
                year_start=years[0] if years else source["coverage_start_year"],
                year_end=years[-1] if years else source["coverage_end_year"],
                years_text=f"{years[0]}-{years[-1]}" if years else "",
                source_url=source["url"],
                indicator_url=source["url"],
                link_level="dataset",
                access_modes=source["access_modes"],
                update_frequency=source["update_frequency"],
                api_hint=(
                    "Heft 'Arbeitsmarkt kommunal' je Kreis: amk-<Kreisschlüssel>-0-<JJJJMM>-zip.zip, "
                    "darin eine XLSX pro Gemeinde, Tabellenblatt 'Daten'."
                ),
            )
        )
    return records


# Breitbandatlas raster column vocabulary. The columns follow the scheme
# <richtung>_<netz>_<nutzung>_<technologie>_<bandbreite>, documented only by the column
# names themselves, so the expansions are spelled out here.
RASTER_TOKENS = {
    "down": "Downstream", "up": "Upstream",
    "fn": "Festnetz", "mf": "Mobilfunk",
    "hh": "Haushalte", "gew": "Gewerbe (Unternehmen)", "gwg": "Gewerbegebiete",
    "alle": "alle Technologien", "ftthb": "FTTB/H", "ftth": "FTTH", "fttb": "FTTB",
    "fttc": "FTTC", "hfc": "HFC (Kabel)", "sonst": "sonstige Technologien",
}


def flatten_breitband_raster(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Grid-cell level broadband coverage. The GeoPackages are 0.3 to 1.8 GB, so only their
    schema is read (see scripts/extract_gpkg_schema.py) and one record per attribute is
    emitted: that is what a researcher needs in order to know the raster exists and what it
    measures."""
    raw = source["folder"] / "raw"
    records: List[Dict[str, Any]] = []
    skip = {"id", "geom", "raster_id", "raster_rowid", "ags", "bl"}

    for schema_path in sorted(raw.glob("*_schema.json")):
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        readme = " ".join(payload.get("readme", {}).values())
        readme = re.sub(r"\s+", " ", readme)[:400]
        for layer in payload.get("layers", []):
            cells = layer.get("rows")
            for column in layer.get("columns", []):
                name = clean(column.get("name"))
                if not name or name.lower() in skip:
                    continue
                parts = name.split("_")
                bandwidth = parts[-1] if parts[-1].isdigit() else ""
                words = [RASTER_TOKENS.get(part.lower(), part) for part in parts if not part.isdigit()]
                label = ", ".join(words) + (f", mindestens {bandwidth} Mbit/s" if bandwidth else "")
                records.append(
                    make_record(
                        source_key="breitband",
                        source_label="Gigabit-Grundbuch / Breitbandatlas (Bundesnetzagentur, BMDV)",
                        item_type="regional_indicator",
                        item_id=f"breitband_raster:{layer.get('table')}:{name}",
                        variable_name=name,
                        label=f"{label} (Gitterzelle)",
                        dataset_label="Versorgungsdaten je Gitterzelle (GeoPackage)",
                        theme="Digitalisierung",
                        description=join_nonempty([
                            f"{label}. Versorgungsgrad in Prozent je Gitterzelle des geographischen "
                            f"Gitters für Deutschland (BKG, UTM)"
                            + (f", {cells:,} Zellen".replace(",", ".") if isinstance(cells, int) else "") + ".",
                            "Feinste räumliche Auflösung im Datenangebot des Finders: unterhalb der "
                            "Gemeindeebene und damit für Erreichbarkeits- und Ungleichheitsanalysen "
                            "innerhalb von Gemeinden nutzbar. Jede Zelle trägt zusätzlich den AGS.",
                            f"Nutzungshinweis der Quelle: {readme}" if readme else "",
                        ]),
                        unit="Prozent" if bandwidth else "",
                        spatial_levels=["Weitere Gliederungen", "Gemeinden", "Kreise"],
                        nuts_levels=["Weitere Gliederungen", "Gemeinden", "LAU", "Kreise", "NUTS3"],
                        year_start=2025,
                        year_end=2025,
                        years_text="Stand 31.12.2025",
                        source_url="https://gigabitgrundbuch.bund.de/",
                        indicator_url="https://gigabitgrundbuch.bund.de/",
                        link_level="dataset",
                        access_modes=["direct file download", "interactive map viewer"],
                        update_frequency=source["update_frequency"] or "halbjährlich",
                        api_hint=(
                            f"Spalte {name} in Tabelle {layer.get('table')} des GeoPackage "
                            f"({payload.get('archive')}); lesbar mit GDAL/OGR, geopandas oder SQLite."
                        ),
                    )
                )
    return records


# BA workbook sheet names are internal shorthand ("Unterbeschäftigung_RK", "Eckwerte_Grusi").
# They reach the user as the dataset facet, so they are spelled out.
BA_SHEET_LABELS: Dict[str, str] = {
    "_RK": " (nach Rechtskreisen)",
    "_Grusi": " (Grundsicherung)",
    "Alo_Bestand": "Arbeitslose: Bestand",
    "Alo_Bewegungen": "Arbeitslose: Zu- und Abgänge",
    "Alo_Struktur": "Arbeitslose: Struktur",
}


def ba_sheet_label(sheet: str) -> str:
    """Readable dataset label for a BA workbook sheet name."""
    if sheet in BA_SHEET_LABELS:
        return BA_SHEET_LABELS[sheet]
    for suffix, replacement in BA_SHEET_LABELS.items():
        if suffix.startswith("_") and sheet.endswith(suffix):
            return sheet[: -len(suffix)] + replacement
    return sheet.replace("_", " ")


def flatten_ba_arbeitsmarktreport(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """'Arbeitsmarktreport': a monthly booklet per region whose 22 sheets carry the BA's
    headline labour-market indicators. Labels sit in the first two columns (indented for
    breakdowns) and the values further right, so a row counts as an indicator when it has a
    label and at least one numeric value."""
    path = next((p for p in (source["folder"] / "raw").glob("amr-*.xlsx")), None)
    if path is None:
        return []
    workbook = pd.ExcelFile(path)
    skip_sheets = {"deckblatt", "impressum", "hinweise", "inhaltsverzeichnis", "statistik-infoseite"}

    records: List[Dict[str, Any]] = []
    seen: set = set()
    for sheet in workbook.sheet_names:
        if sheet.lower() in skip_sheets:
            continue
        frame = pd.read_excel(path, sheet_name=sheet, header=None)
        section = ""
        for _, row in frame.iterrows():
            values = row.tolist()
            first = clean(str(values[0])).replace("\n", " ") if values else ""
            second = clean(str(values[1])).replace("\n", " ") if len(values) > 1 else ""
            # Column A doubles as a share column in some sheets, so a numeric "label" is data.
            if re.match(r"^-?[\d.,]+$", first):
                first = ""
            numeric = [v for v in values[2:] if re.match(r"^-?[\d.,]+$", clean(str(v)))]
            label_part = second or first
            if not label_part or label_part in {"dar.", "nan", "Merkmale", "insgesamt"}:
                continue
            if re.match(r"^(Quelle|Stand|Erstellt|Impressum|©|Statistik der)", label_part):
                continue
            if not numeric:
                if len(label_part) > 10 and not second:
                    section = label_part
                continue
            label = f"{section}: {label_part}".strip(": ") if section and section != label_part else label_part
            key = (sheet, label.lower())
            if key in seen:
                continue
            seen.add(key)
            records.append(
                make_record(
                    source_key="ba_arbeitsmarktreport",
                    source_label="Arbeitsmarktreport (Bundesagentur für Arbeit)",
                    item_type="regional_indicator",
                    item_id=f"amr:{sheet}:{len(seen):04d}",
                    variable_name=f"AMR-{len(seen):04d}",
                    label=label[:130],
                    dataset_label=ba_sheet_label(sheet),
                    theme="Arbeitsmarkt & Beschäftigung",
                    description=join_nonempty([
                        f"{label}. Merkmal im Tabellenblatt '{sheet}' des monatlichen "
                        "BA-Arbeitsmarktreports, veröffentlicht je Land, Agenturbezirk und Kreis.",
                        "Monatliche Fortschreibung, damit deutlich aktueller und feiner in der Zeit "
                        "als die jährlichen Indikatoren in INKAR oder im Regionalatlas.",
                    ]),
                    stats_summary=section,
                    spatial_levels=["Bundesländer", "Kreise", "Weitere Gliederungen"],
                    nuts_levels=["Bundesländer", "NUTS1", "Kreise", "NUTS3"],
                    year_start=source["coverage_start_year"],
                    year_end=source["coverage_end_year"],
                    years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}, monatlich",
                    source_url=source["url"],
                    indicator_url=source["url"],
                    link_level="dataset",
                    access_modes=source["access_modes"],
                    update_frequency=source["update_frequency"] or "monatlich",
                    api_hint=(
                        "Heft 'Arbeitsmarktreport' je Region: /Statistikdaten/Detail/<JJJJMM>/ama/amr-amr/"
                        "amr-<Region>-0-<JJJJMM>-xlsx.xlsx, Tabellenblatt "
                        f"'{sheet}'."
                    ),
                )
            )

    # The same headline label recurs across sheets with a different meaning ("Bestand an
    # Arbeitslosen: Insgesamt" in Eckwerte vs Eckwerte SGB II vs SGB III), so a label that
    # is not unique gets its sheet appended. Otherwise the result list shows three
    # indistinguishable rows.
    counts: Dict[str, int] = {}
    for record in records:
        counts[record["label"]] = counts.get(record["label"], 0) + 1
    for record in records:
        if counts.get(record["label"], 0) > 1:
            record["label"] = f"{record['label']} [{record['dataset_label']}]"
    return records


def flatten_db_isr(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deutsche Bahn Infrastrukturregister, from its own open GeoServer.

    The viewer is a MapStore2 app in front of a public GeoServer, so no registration is needed
    (InfraGO support confirmed this, ticket IIBV31-13354): WMS GetCapabilities lists the map
    themes and WFS DescribeFeatureType lists the attributes per feature type. Both are indexed,
    because "which layers exist" and "does anything record platform height" are different
    questions.

    ISR publishes each feature type twice, German and English (`..._EN`). The pair is matched
    positionally so the English attribute name becomes the alias of the German one instead of a
    duplicate record."""
    import xml.etree.ElementTree as ET

    raw = source["folder"] / "raw"
    viewer = "https://geoviewer.deutschebahn.com/maps/#/context/ISR/275618"
    ows = "https://geoviewer.deutschebahn.com/geoviewer-geoserver/ows"
    records: List[Dict[str, Any]] = []
    mapped = map_spatial(["Adressen / Koordinaten", "Gemeinden und Verbandsgemeinden",
                          "Kreise & kreisfreie Städte", "Bundesland"])

    # --- map themes from the WMS capabilities -----------------------------------------
    wms_path = raw / "isr_wms_capabilities.xml"
    if wms_path.exists():
        text = wms_path.read_text(encoding="utf-8", errors="replace")
        blocks = re.findall(r"<Layer[^>]*>(.*?)</Layer>", text, re.S)
        seen: set = set()
        for block in blocks:
            name = re.search(r"<Name>(ISR:[^<]+)</Name>", block)
            title = re.search(r"<Title>([^<]*)</Title>", block)
            abstract = re.search(r"<Abstract>([^<]*)</Abstract>", block)
            if not name:
                continue
            layer = clean(name.group(1))
            heading = clean(title.group(1)) if title else layer
            key = (layer, heading.lower())
            if key in seen or heading.lower().endswith("_en"):
                continue
            seen.add(key)
            records.append(
                make_record(
                    source_key="db_isr",
                    source_label="Infrastrukturregister der DB InfraGO (ISR)",
                    item_type="regional_indicator",
                    item_id=f"db_isr:wms:{layer}:{heading[:40]}",
                    variable_name=layer.split(":")[-1],
                    label=f"{heading} (ISR-Kartenebene)",
                    dataset_label="ISR Kartenebenen (WMS)",
                    theme="Verkehr / Mobilität",
                    description=join_nonempty([
                        f"Kartenebene '{heading}' im Infrastrukturregister der DB InfraGO, "
                        f"GeoServer-Layer {layer}.",
                        clean(abstract.group(1)) if abstract else "",
                        "Merkmale des deutschen Schienennetzes streckenscharf bzw. punktgenau: "
                        "Strecken, Betriebsstellen, Bahnsteige, Tunnel, Brücken und Bahnübergänge, "
                        "jeweils mit Koordinaten und damit auf Gemeinde-, Kreis- oder Landesebene "
                        "aggregierbar.",
                        "Ohne Registrierung nutzbar: der Kartenviewer ist frei zugänglich und der "
                        "GeoServer liefert WMS und WFS offen aus.",
                    ]),
                    spatial_levels=mapped["spatial_levels"],
                    nuts_levels=mapped["nuts_levels"],
                    year_start=source["coverage_start_year"],
                    year_end=source["coverage_end_year"],
                    years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                    source_url=viewer,
                    indicator_url=viewer,
                    link_level="dataset",
                    access_modes=["interactive map viewer", "machine-readable API", "direct file download"],
                    update_frequency=source["update_frequency"] or "laufend",
                    api_hint=(
                        f"WMS-Layer {layer} unter {ows} (GetCapabilities/GetMap). "
                        "Keine Anmeldung nötig."
                    ),
                )
            )

    # --- attributes from DescribeFeatureType -------------------------------------------
    attributes_path = raw / "isr_wfs_attributes.json"
    if attributes_path.exists():
        payload = json.loads(attributes_path.read_text(encoding="utf-8"))
        layers = payload.get("layers", {})
        english = {name[:-3]: entry for name, entry in layers.items() if name.endswith("_EN")}
        skip_fields = {"geom", "the_geom", "geometry", "shape", "id", "lade_id", "objectid"}
        for name, entry in sorted(layers.items()):
            if name.endswith("_EN"):
                continue
            fields = entry.get("fields") or []
            english_fields = (english.get(name, {}) or {}).get("fields") or []
            short = name.split(":")[-1].replace("ISR_V_", "").replace("GEO_", "").replace("_", " ").title()
            for position, field in enumerate(fields):
                field_name = clean(field.get("name"))
                normalised = field_name.lower().replace("_", "")
                if (not field_name or field_name.lower() in skip_fields
                        or normalised == name.split(":")[-1].lower().replace("_", "")):
                    continue
                english_name = clean(english_fields[position]["name"]) if position < len(english_fields) else ""
                readable = re.sub(r"_+", " ", field_name).strip().title()
                records.append(
                    make_record(
                        source_key="db_isr",
                        source_label="Infrastrukturregister der DB InfraGO (ISR)",
                        item_type="register_attribute",
                        item_id=f"db_isr:field:{name}:{field_name}",
                        variable_name=field_name,
                        label=f"{readable} ({short})",
                        dataset_label=f"ISR {short} (WFS)",
                        theme="Verkehr / Mobilität",
                        description=join_nonempty([
                            f"Merkmal {field_name} der ISR-Objektart {short} ({name}).",
                            f"English field name: {english_name}." if english_name else "",
                            "Attribut im Infrastrukturregister der DB InfraGO, über WFS ohne "
                            "Anmeldung abrufbar und punktgenau bzw. streckenscharf georeferenziert.",
                        ]),
                        aliases=english_name,
                        spatial_levels=mapped["spatial_levels"],
                        nuts_levels=mapped["nuts_levels"],
                        year_start=source["coverage_start_year"],
                        year_end=source["coverage_end_year"],
                        years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                        source_url=viewer,
                        indicator_url=viewer,
                        link_level="dataset",
                        access_modes=["machine-readable API", "interactive map viewer", "direct file download"],
                        update_frequency=source["update_frequency"] or "laufend",
                        api_hint=(
                            f"WFS: {ows}?service=WFS&version=2.0.0&request=GetFeature"
                            f"&typeNames={name}&outputFormat=application/json ; Merkmal {field_name}."
                        ),
                    )
                )
    return records


# The NeTEx specification has thousands of XML elements, almost all of them machinery. Indexing
# it wholesale would bury the German data sources, so these are the concepts a researcher would
# actually search for, with a German gloss each.
NETEX_CONCEPTS = [
    ("StopPlace", "Haltestelle als Ort (Bahnhof, Busbahnhof, Haltestellenbereich) mit Koordinaten und Adresse"),
    ("Quay", "Bahnsteig oder Steig innerhalb einer Haltestelle, der eigentliche Ein- und Ausstiegspunkt"),
    ("ScheduledStopPoint", "Fahrplanmäßiger Halt einer Linie, Verknüpfung zwischen Fahrplan und Ort"),
    ("StopPlaceEntrance", "Zugang zu einer Haltestelle, Grundlage für Wege- und Barrierefreiheitsanalysen"),
    ("AccessibilityAssessment", "Barrierefreiheit einer Haltestelle oder eines Fahrzeugs, etwa stufenfreier Zugang"),
    ("AccessibilityLimitation", "Einzelne Einschränkung der Barrierefreiheit, zum Beispiel Rollstuhlzugang, Aufzug, Blindenleitsystem"),
    ("PathLink", "Fußweg innerhalb einer Haltestelle, für Umsteigezeiten und Erreichbarkeit"),
    ("Line", "Linie eines Verkehrsunternehmens mit Nummer, Name und Verkehrsmittel"),
    ("Route", "Geografischer Linienweg als Abfolge von Punkten"),
    ("JourneyPattern", "Halteabfolge einer Fahrt entlang einer Route"),
    ("ServiceJourney", "Einzelne Fahrt mit Abfahrts- und Ankunftszeiten"),
    ("DatedServiceJourney", "Einer konkreten Kalenderlage zugeordnete Fahrt"),
    ("TimetabledPassingTime", "Planmäßige Durchfahrts-, Ankunfts- oder Abfahrtszeit an einem Halt"),
    ("DayType", "Verkehrstag, etwa Montag bis Freitag, Schulferien, Feiertag"),
    ("OperatingPeriod", "Zeitraum, in dem ein Fahrplan gilt"),
    ("Operator", "Verkehrsunternehmen, das Fahrten durchführt"),
    ("Authority", "Aufgabenträger oder Verbund, der den Verkehr bestellt"),
    ("TransportMode", "Verkehrsmittel, etwa Bus, Straßenbahn, S-Bahn, Zug, Fähre"),
    ("Interchange", "Geplanter Anschluss zwischen zwei Fahrten"),
    ("SiteFrame", "Rahmen mit allen Ortsdaten, also Haltestellen, Bahnsteige und Zugänge"),
    ("ServiceFrame", "Rahmen mit Linien, Routen und Halten"),
    ("TimetableFrame", "Rahmen mit den Fahrten und Fahrzeiten"),
    ("ResourceFrame", "Rahmen mit Unternehmen, Verkehrsmitteln und weiteren Stammdaten"),
    ("FareFrame", "Rahmen mit Tarifzonen und Preisen"),
    ("TariffZone", "Tarifzone, Grundlage für Preis- und Erreichbarkeitsanalysen"),
    ("PointProjection", "Zuordnung eines Punktes zu einem anderen Bezugssystem"),
    ("VehicleType", "Fahrzeugtyp mit Kapazität und Ausstattung"),
    ("Notice", "Hinweistext zu Linie, Fahrt oder Halt"),
]


def flatten_transit_formats(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """GTFS and NeTEx field schemas.

    The ÖPNV datasets in this index are delivered in these two formats, so "which field carries
    step-free access" or "where is the departure time" is a discovery question this tool should
    answer. GTFS is small enough to index field by field, straight from the specification. NeTEx
    is not: its schema has thousands of elements, so only the concepts a researcher would look
    for are listed, each with a German gloss."""
    raw = source["folder"] / "raw"
    records: List[Dict[str, Any]] = []
    levels = ["Adressen / Koordinaten", "Gemeinden und Verbandsgemeinden", "weitere räumliche Gliederungen"]
    mapped = map_spatial(levels)

    gtfs_path = raw / "gtfs_reference.md"
    if gtfs_path.exists():
        text = gtfs_path.read_text(encoding="utf-8", errors="replace")
        current_file = ""
        for line in text.splitlines():
            heading = re.match(r"^###\s+([a-z_]+\.(?:txt|geojson))\s*$", line.strip())
            if heading:
                current_file = heading.group(1)
                continue
            row = re.match(r"^\|\s+`([^`]+)`\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*(.*?)\s*\|?$", line)
            if not row or not current_file:
                continue
            field, field_type, presence, description = (clean(part).replace("*", "").replace("`", "")
                                                        for part in row.groups())
            if field.lower() in {"field name"}:
                continue
            # The spec writes rich markdown in the description; keep it readable as plain text.
            description = re.sub(r"<br\s*/?>", " ", description)
            description = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", description)
            description = re.sub(r"[`*]", "", description)
            description = re.sub(r"\s+", " ", description).strip()
            records.append(
                make_record(
                    source_key="transit_formats",
                    source_label="GTFS und NeTEx (Datenformate der ÖPNV-Fahrplandaten)",
                    item_type="register_attribute",
                    item_id=f"gtfs:{current_file}:{field}",
                    variable_name=field,
                    label=f"{field} ({current_file})",
                    dataset_label=f"GTFS {current_file}",
                    theme="Verkehr / Mobilität",
                    description=join_nonempty([
                        f"GTFS-Feld {field} in {current_file}. {description}"[:900],
                        f"Typ: {field_type}. Vorkommen: {presence}." if field_type or presence else "",
                        "GTFS ist das Format, in dem die deutschlandweiten und verbundbezogenen "
                        "Soll-Fahrplandaten auf opendata-oepnv.de veröffentlicht werden.",
                    ]),
                    unit=field_type,
                    spatial_levels=mapped["spatial_levels"],
                    nuts_levels=mapped["nuts_levels"],
                    source_url="https://gtfs.org/documentation/schedule/reference/",
                    indicator_url=f"https://gtfs.org/documentation/schedule/reference/#{current_file.replace('.', '')}",
                    link_level="dataset",
                    access_modes=["direct file download", "machine-readable API"],
                    update_frequency="laufend",
                    api_hint=(
                        f"Spalte {field} in {current_file} eines GTFS-Feeds, etwa "
                        "'Deutschlandweite Sollfahrplandaten (GTFS)' auf opendata-oepnv.de."
                    ),
                )
            )

    for element, gloss in NETEX_CONCEPTS:
        records.append(
            make_record(
                source_key="transit_formats",
                source_label="GTFS und NeTEx (Datenformate der ÖPNV-Fahrplandaten)",
                item_type="register_attribute",
                item_id=f"netex:{element}",
                variable_name=element,
                label=f"{element} (NeTEx)",
                dataset_label="NeTEx",
                theme="Verkehr / Mobilität",
                description=join_nonempty([
                    f"NeTEx-Element {element}: {gloss}.",
                    "NeTEx ist das europäische Austauschformat für Fahrplan-, Halte- und Tarifdaten "
                    "und wird für die deutschlandweiten Sollfahrplandaten neben GTFS ausgeliefert.",
                    "Hier sind bewusst nur die inhaltlich relevanten Konzepte aufgeführt, nicht das "
                    "vollständige XML-Schema.",
                ]),
                spatial_levels=mapped["spatial_levels"],
                nuts_levels=mapped["nuts_levels"],
                source_url="https://www.opendata-oepnv.de/ht/de/organisation/delfi/startseite",
                indicator_url="https://www.opendata-oepnv.de/ht/de/organisation/delfi/startseite",
                link_level="dataset",
                access_modes=["direct file download", "on request / registration needed"],
                update_frequency="laufend",
                api_hint=(
                    f"NeTEx-Element {element}; Profil siehe prCEN/TS 16614 PI Profile "
                    "(Dokument im Ordner raw/ dieser Quelle)."
                ),
            )
        )
    return records


def _pdf_bbox_lines(path: Path) -> List[List[Tuple[float, float, str]]]:
    """Text lines with real page geometry: [page][(xMin, yMin, text)].

    `pdftotext -layout` renders a two-column table into a fixed-width grid whose column
    boundary drifts between pages, so any character-offset split cuts some rows mid-word.
    The word coordinates from `-bbox-layout` say where the columns actually are.
    """
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".xhtml", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        subprocess.run(["pdftotext", "-bbox-layout", str(path), str(out_path)],
                       check=True, capture_output=True, timeout=300)
        xml = out_path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[warn] could not read {path.name}: {exc}")
        return []
    finally:
        out_path.unlink(missing_ok=True)

    pages: List[List[Tuple[float, float, str]]] = []
    head_re = re.compile(r'^<line xMin="([\d.]+)" yMin="([\d.]+)"')
    word_re = re.compile(r"<word [^>]*>(.*?)</word>", re.S)
    for chunk in xml.split("<page ")[1:]:
        lines: List[Tuple[float, float, str]] = []
        for raw in chunk.split("<line ")[1:]:
            head = head_re.match("<line " + raw[: raw.find(">") + 1])
            if not head:
                continue
            words = [w for w in (html.unescape(x).strip() for x in word_re.findall(raw[: raw.find("</line>")])) if w]
            text = re.sub(r"\s+", " ", " ".join(words)).strip()
            if text:
                lines.append((float(head.group(1)), float(head.group(2)), text))
        pages.append(lines)
    return pages


def _column_split(lines: List[Tuple[float, float, str]]) -> Optional[float]:
    """x midway between the term column and the definition column on one page."""
    counts: Dict[int, int] = {}
    for x, _y, _t in lines:
        counts[int(round(x / 2.0)) * 2] = counts.get(int(round(x / 2.0)) * 2, 0) + 1
    if not counts:
        return None
    def_x = max(counts, key=lambda k: (counts[k], -k))
    left = {x: n for x, n in counts.items() if x < def_x - 15}
    if not left:
        return None
    term_x = max(left, key=lambda k: (left[k], -k))
    return (term_x + def_x) / 2.0


def _pdf_text(path: Path, layout: bool = True) -> str:
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        out_path = Path(tmp.name)
    try:
        args = ["pdftotext"] + (["-layout"] if layout else []) + [str(path), str(out_path)]
        subprocess.run(args, check=True, capture_output=True, timeout=180)
        return out_path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[warn] could not read {path.name}: {exc}")
        return ""
    finally:
        out_path.unlink(missing_ok=True)


def flatten_ba_glossary(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The BA's own glossary: the definition of every labour-market concept its statistics
    measure. The map behind this workbook row publishes no machine-readable indicator list, but
    the concepts are what a researcher actually searches for ("Unterbeschaeftigung",
    "Aktivierungsquote"), and the glossary is the authoritative wording for them.

    The PDF is a two-column table (term | definition) whose column boundary MOVES between pages
    (observed at columns 23, 26 and 30), and a long term wraps onto further lines in the left
    column. So the boundary is measured per page from the indent shared by the definition
    continuation lines, and a new entry starts only where a left-column line follows definition
    text rather than another term fragment.
    """
    pdf = source["folder"] / "raw" / "ba_gesamtglossar.pdf"
    if not pdf.exists():
        return []
    pages = _pdf_bbox_lines(pdf)
    if not pages:
        return []

    SKIP = re.compile(
        r"^(Definitionen\s*[-\u2013]\s*Glossar|Glossar der Statistik|Begriff$|Erkl\u00e4rung$|Impressum|"
        r"Nutzungsbedingungen|Produktlinie|Herausgeberin|R\u00fcckfragen|Zitierhinweis|Titel:|Stand:|"
        r"Erstellungsdatum|Weiterf\u00fchrende|Seite \d|\d+$|E-Mail|Internet$|Telefon)", re.I)

    # A term too long for the left column wraps onto the next line, and the wrap is
    # recognisable: it sits one line-height below (~12pt, vs ~15pt+ between table rows) and it
    # continues the words above it (trailing hyphen, lowercase start, a dangling preposition, or
    # an unclosed bracket). Everything else in the left column starts a new glossary entry.
    DANGLING = {"bei", "in", "im", "am", "an", "auf", "aus", "bis", "der", "des", "die", "das",
                "dem", "den", "durch", "f\u00fcr", "gegen", "mit", "nach", "ohne", "\u00fcber", "um",
                "und", "von", "vor", "zu", "zur", "zum", "je", "pro", "als", "aus\u00dfer"}

    entries: List[Tuple[str, List[str]]] = []
    term_parts: List[str] = []
    body: List[str] = []

    def flush() -> None:
        if term_parts and body:
            term = re.sub(r"([a-z\u00e4\u00f6\u00fc\u00df])-\s+(?=[a-z\u00e4\u00f6\u00fc\u00df])", r"\1", " ".join(term_parts))
            term = re.sub(r"\s+", " ", term).strip(" .:\u2013-")
            definition = re.sub(r"([a-z\u00e4\u00f6\u00fc\u00df])-\s+(?=[a-z\u00e4\u00f6\u00fc\u00df])", r"\1", " ".join(body))
            definition = re.sub(r"\s+", " ", definition).strip()
            if 3 < len(term) < 90:
                entries.append((term, [definition]))
        term_parts.clear()
        body.clear()

    def continues(prev_y: Optional[float], y: float, text: str) -> bool:
        if not term_parts or prev_y is None or y - prev_y > 13.5:
            return False
        prev = term_parts[-1]
        joined = " ".join(term_parts)
        return (prev.endswith("-")
                or text[:1].islower()
                or prev.split(" ")[-1].lower() in DANGLING
                or joined.count("(") > joined.count(")"))

    for lines in pages:
        page_lines = [(x, y, t) for x, y, t in lines if 60.0 < y < 780.0 and not SKIP.match(t)]
        split = _column_split(page_lines)
        if split is None:
            continue
        last_term_y: Optional[float] = None
        for x, y, text in sorted(page_lines, key=lambda r: (r[1], r[0])):
            if x < split:
                if len(text.rstrip(".")) < 3:          # alphabet section marker ("A", "0-9")
                    continue
                if not continues(last_term_y, y, text):
                    flush()
                term_parts.append(text)
                last_term_y = y
            else:
                body.append(text)
        flush()

    records: List[Dict[str, Any]] = []
    seen: set = set()
    for term, lines in entries:
        definition = " ".join(lines).strip()
        # Reject fragments: a real term starts with a capital and is not a cut-off word.
        # Reject anything that is not a term: sentences that leaked out of the definition
        # column, page furniture from the impressum, and cut-off fragments.
        if (len(definition) < 40 or term.lower() in seen or not term[:1].isupper()
                or len(term) < 5 or len(term.split()) > 8
                or re.search(r"@|http|\.pdf", term)
                or re.search(r",\s|\b(sind|ist|werden|wird|handelt|gelten|z\u00e4hlen)\b", term)
                or definition.startswith("http") or "@arbeitsagentur" in definition):
            continue
        seen.add(term.lower())
        summary = definition if len(definition) <= 600 else definition[:600].rsplit(" ", 1)[0] + " ..."
        records.append(
            make_record(
                source_key="ba_glossar",
                source_label="Glossar der Statistik der Bundesagentur f\u00fcr Arbeit",
                item_type="concept",
                item_id="ba_glossar:" + re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")[:60],
                variable_name=term,
                label=term,
                dataset_label="Glossar der Statistik der BA",
                theme="Arbeitsmarkt & Besch\u00e4ftigung",
                description=summary,
                spatial_levels=["Bundesl\u00e4nder", "Kreise", "Gemeinden"],
                nuts_levels=["Bundesl\u00e4nder", "NUTS1", "Kreise", "NUTS3", "Gemeinden", "LAU"],
                source_url="https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Definitionen/Glossar/Glossar-Nav.html",
                indicator_url="https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Definitionen/Glossar/Glossar-Nav.html",
                link_level="dataset",
                access_modes=["direct file download"],
                update_frequency="halbj\u00e4hrlich",
                api_hint="Eintrag im Gesamtglossar der Statistik der BA (PDF, halbj\u00e4hrlich aktualisiert). "
                         "Definiert, was die BA-Arbeitsmarktstatistiken z\u00e4hlen.",
            )
        )
    if len(records) < 150:
        print(f"[warn] ba glossary: only {len(records)} clean entries parsed")
    return records


# Record structure of the offeneregister.de company dump. The keys are the ones documented in
# the annotated `de_companies_ocdata.jsonl` sample on https://offeneregister.de/daten/ (saved as
# raw/daten.html), not invented: the dump itself is multi-GB and is never downloaded here.
OFFENEREGISTER_FIELDS: List[Tuple[str, str, str]] = [
    ("name", "Firmenname",
     "Eingetragener Name des Unternehmens, inklusive Rechtsform."),
    ("company_number", "Registernummer",
     "Registerzeichen und -nummer, etwa \u201eM\u00fcnchen HRB 73315\u201c. Eindeutige Kennung eines "
     "Unternehmens \u00fcber alle Ver\u00e4nderungen hinweg und damit der Schl\u00fcssel f\u00fcr Panels."),
    ("native_company_number", "Registernummer in nationaler Schreibweise",
     "Registernummer in der Schreibweise des Handelsregisters."),
    ("registrar", "Registergericht",
     "Zust\u00e4ndiges Amtsgericht des Registereintrags. Grobe regionale Zuordnung ohne Geocoding."),
    ("federal_state", "Bundesland",
     "Bundesland des Registergerichts."),
    ("jurisdiction_code", "Rechtsraum",
     "Code des Rechtsraums (de, de_by, de_nw, ...)."),
    ("registered_address", "Gesch\u00e4ftsanschrift",
     "Adresse des Unternehmens als Freitext. Geocodierbar und damit auf PLZ-, Gemeinde- oder "
     "Kreisebene aggregierbar, etwa f\u00fcr Unternehmensdichte."),
    ("registered_office", "Sitz der Gesellschaft",
     "Ort des Gesellschaftssitzes laut Registereintrag."),
    ("current_status", "Status des Unternehmens",
     "Aktueller Registerstatus, etwa aktiv oder gel\u00f6scht. Grundlage f\u00fcr L\u00f6schungs- und "
     "Bestandsanalysen."),
    ("previous_names", "Fr\u00fchere Firmennamen",
     "Liste fr\u00fcherer Namen mit Gültigkeitszeitraum. Erlaubt es, Umfirmierungen von "
     "Neugr\u00fcndungen zu unterscheiden."),
    ("officers", "Organe und Vertretungsberechtigte",
     "Gesch\u00e4ftsf\u00fchrer, Vorst\u00e4nde, Prokuristen und Gesellschafter mit Position, Eintritts- und "
     "Austrittsdatum sowie Wohnort. Grundlage f\u00fcr Verflechtungs- und Netzwerkanalysen."),
    ("retrieved_at", "Abrufdatum",
     "Zeitpunkt, zu dem der Registerauszug abgerufen wurde. Bestimmt den Datenstand."),
    ("all_attributes", "Rohattribute des Registerauszugs",
     "Unver\u00e4nderte Felder des Registerauszugs, etwa Kapital, Gegenstand des Unternehmens und "
     "Rechtsform, soweit im Auszug enthalten."),
]


# What StaDa records per station. The gloss is authored; the counts in the descriptions are
# computed from the downloaded file so a record states how much variation the field actually has.
STADA_FIELDS: List[Tuple[str, str, str]] = [
    ("category", "Bahnhofskategorie",
     "Preis- und Ausstattungskategorie 1 bis 7 der Station. Kategorie 1 sind die größten "
     "Fernverkehrsknoten, Kategorie 7 kleine Haltepunkte. Der üblichste Indikator für die "
     "Bedeutung eines Bahnhofs im Netz."),
    ("priceCategory", "Preisklasse der Station",
     "Preisklasse, nach der das Stationsentgelt berechnet wird."),
    ("productLine", "Produktlinie der Station",
     "Funktion im Netz: Metropolbahnhof, Knotenbahnhof, S-Bahnhof, Zubringerbahnhof."),
    ("hasSteplessAccess", "Stufenfreier Zugang",
     "Stufenfreier Zugang zu den Bahnsteigen (ja, teilweise, nein). Kernindikator für "
     "Barrierefreiheit im Nahverkehr."),
    ("hasMobilityService", "Mobilitätsservice / Ein- und Ausstiegshilfe",
     "Verfügbarkeit der Ein- und Ausstiegshilfe, oft nur nach Voranmeldung."),
    ("mobilityServiceStaff", "Personal des Mobilitätsservice",
     "Anwesenheitszeiten des Mobilitätsservice-Personals je Wochentag und Feiertag."),
    ("localServiceStaff", "Servicepersonal vor Ort",
     "Anwesenheitszeiten des Servicepersonals je Wochentag und Feiertag."),
    ("hasParking", "Park-and-ride / Pkw-Stellplätze",
     "Pkw-Stellplätze am Bahnhof. Grundlage für Park-and-ride-Analysen."),
    ("hasBicycleParking", "Fahrradabstellanlage",
     "Abstellanlagen für Fahrräder am Bahnhof (Bike-and-ride)."),
    ("hasLocalPublicTransport", "Anschluss an den ÖPNV",
     "Anschluss an Bus, Tram oder U-Bahn am Bahnhof. Indikator für intermodale Verknüpfung."),
    ("hasTaxiRank", "Taxistand", "Taxistand am Bahnhof."),
    ("hasCarRental", "Mietwagenangebot", "Mietwagenschalter oder -station am Bahnhof."),
    ("hasTravelCenter", "Reisezentrum", "Personalbesetztes Reisezentrum am Bahnhof."),
    ("hasTravelNecessities", "Reisebedarf / Einkaufsmöglichkeit",
     "Verkaufsstelle für Reisebedarf am Bahnhof."),
    ("hasDBLounge", "DB Lounge", "DB Lounge am Bahnhof, faktisch nur an Großstadtknoten."),
    ("hasLockerSystem", "Schließfächer", "Schließfachanlage am Bahnhof."),
    ("hasPublicFacilities", "Öffentliche Toiletten", "Oeffentlich zugängliche Toiletten am Bahnhof."),
    ("hasWiFi", "WLAN am Bahnhof", "Oeffentliches WLAN am Bahnhof."),
    ("wirelessLan", "WLAN-Details", "Art und Betreiber des WLAN-Angebots, wo erfasst."),
    ("hasRailwayMission", "Bahnhofsmission",
     "Bahnhofsmission am Bahnhof, ein Indikator für soziale Infrastruktur am Verkehrsknoten."),
    ("hasLostAndFound", "Fundbüro", "Fundbüro am Bahnhof."),
    ("DBinformation", "DB Information",
     "Servicepoint DB Information mit Öffnungszeiten, wo vorhanden."),
    ("mailingAddress", "Anschrift des Bahnhofs",
     "Straße, Postleitzahl und Ort des Bahnhofs. Geocodierbar und auf PLZ-, Gemeinde- oder "
     "Kreisebene aggregierbar."),
    ("evaNumbers", "EVA-Nummer und Koordinaten",
     "EVA-Nummer der Betriebsstelle mit WGS84-Koordinaten (Punktgeometrie). Der Schlüssel, mit "
     "dem Fahrplandaten (GTFS, NeTEx, HAFAS) an die Station gehängt werden."),
    ("ril100Identifiers", "RIL100 / Betriebsstellenkürzel",
     "Betriebsstellenkürzel nach Richtlinie 100 mit Koordinaten und Primary Location Code. "
     "Verbindet die Station mit dem Infrastrukturregister (ISR) und den Streckendaten."),
    ("ifopt", "IFOPT-Kennung",
     "IFOPT-Kennung der Haltestelle (de:<Gemeindeschlüssel>:<Nummer>), die den amtlichen "
     "Gemeindeschlüssel enthält und damit die Zuordnung zur Gemeinde erlaubt."),
    ("municipalityCode", "Amtlicher Gemeindeschlüssel",
     "Amtlicher Gemeindeschlüssel (AGS) der Gemeinde, in der die Station liegt. Der direkte "
     "Join-Schlüssel zu Gemeinde- und Kreisstatistiken."),
    ("federalState", "Bundesland der Station",
     "Bundesland und Bundeslandcode (DE-NW, DE-BY, ...) der Station."),
    ("aufgabentraeger", "Aufgabenträger des SPNV",
     "Zuständiger Aufgabenträger des Schienenpersonennahverkehrs (Zweckverband, Landesgesellschaft). "
     "Erlaubt Vergleiche der Ausstattung zwischen Bestellerorganisationen."),
    ("regionalbereich", "Regionalbereich der DB InfraGO",
     "Regionalbereich (RB Nord, Ost, Süd, Süd-Ost, West, Mitte) der Station."),
    ("stationManagement", "Bahnhofsmanagement",
     "Zuständiges Bahnhofsmanagement der DB InfraGO."),
    ("szentrale", "Zuständige 3-S-Zentrale",
     "3-S-Zentrale (Service, Sicherheit, Sauberkeit), die die Station betreut, mit Kontakt."),
    ("timeTableOffice", "Fahrplanbüro", "Zuständiges Fahrplanbüro der Station."),
    ("localizedNames", "Übersetzter Stationsname",
     "Stationsname in weiteren Sprachen, wo erfasst (Grenzbahnhöfe)."),
    ("number", "Stationsnummer (StaDa-ID)",
     "Eindeutige Stationsnummer der StaDa-Datenbank, der Primärschlüssel der Station."),
    ("name", "Name der Station", "Offizieller Stationsname."),
]


def flatten_db_stada(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DB StaDa station data. Following the register rule, what gets indexed is what StaDa
    RECORDS about a station (category, accessibility, facilities, Aufgabenträger, coordinates),
    not the 5,408 station rows: a concept query is about the attribute, not about one station."""
    path = source["folder"] / "raw" / "stada_stations.json"
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    stations = document.get("result") or []
    if not stations:
        return []

    def coverage(field: str) -> str:
        filled = sum(1 for row in stations if row.get(field) not in (None, "", [], {}))
        values = [row.get(field) for row in stations if isinstance(row.get(field), (str, int, bool))]
        summary = f"Erfasst für {filled} von {len(stations)} Stationen."
        distinct = sorted({str(v) for v in values})
        if 1 < len(distinct) <= 8:
            counts = {v: sum(1 for x in values if str(x) == v) for v in distinct}
            summary += " Verteilung: " + ", ".join(f"{v} ({counts[v]})" for v in distinct) + "."
        return summary

    records: List[Dict[str, Any]] = []
    for field, label, gloss in STADA_FIELDS:
        records.append(
            make_record(
                source_key="db_stada",
                source_label="Bahnhofsdaten StaDa (DB InfraGO / DB Station&Service)",
                item_type="register_attribute",
                item_id=f"db_stada:{field}",
                variable_name=field,
                label=f"{label} (Bahnhof)",
                dataset_label="StaDa Bahnhofsdaten",
                theme="Verkehr & Erreichbarkeit",
                description=join_nonempty([gloss, coverage(field)]),
                spatial_levels=["Adressen/Koordinaten", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "Gemeinden", "LAU", "Kreise", "NUTS3",
                             "Bundesländer", "NUTS1"],
                source_url="https://developers.deutschebahn.com/db-api-marketplace/apis/product/stada",
                indicator_url="https://developers.deutschebahn.com/db-api-marketplace/apis/product/stada",
                link_level="dataset",
                access_modes=["machine-readable API"],
                update_frequency="laufend",
                api_hint=f"Feld {field} in GET /station-data/v2/stations der DB-StaDa-API "
                         f"({len(stations)} Stationen). Die Marketplace-Zugangsdaten sind zwei Header, "
                         "DB-Client-Id und DB-Api-Key.",
            )
        )
    records.append(
        make_record(
            source_key="db_stada",
            source_label="Bahnhofsdaten StaDa (DB InfraGO / DB Station&Service)",
            item_type="dataset",
            item_id="db_stada:stations",
            variable_name="stations",
            label="Verzeichnis aller Personenbahnhöfe in Deutschland (StaDa)",
            dataset_label="StaDa Bahnhofsdaten",
            theme="Verkehr & Erreichbarkeit",
            description=f"Vollständiges Verzeichnis der {len(stations)} Personenbahnhöfe und "
                        "Haltepunkte der DB InfraGO mit Koordinaten, amtlichem Gemeindeschlüssel, "
                        "Bahnhofskategorie, Barrierefreiheit, Ausstattung und Aufgabenträger. "
                        "Punktgenau und damit auf jede Gebietsebene aggregierbar, etwa für "
                        "Bahnanbindung und Erreichbarkeit je Gemeinde.",
            spatial_levels=["Adressen/Koordinaten", "Gemeinden", "Kreise", "Bundesländer"],
            nuts_levels=["Adressen/Koordinaten", "Gemeinden", "LAU", "Kreise", "NUTS3",
                         "Bundesländer", "NUTS1"],
            source_url="https://developers.deutschebahn.com/db-api-marketplace/apis/product/stada",
            indicator_url="https://developers.deutschebahn.com/db-api-marketplace/apis/product/stada",
            link_level="dataset",
            access_modes=["machine-readable API"],
            update_frequency="laufend",
            api_hint="GET /db-api-marketplace/apis/station-data/v2/stations?limit=10000 mit den "
                     "Headern DB-Client-Id und DB-Api-Key. Kostenloser Zugang nach Registrierung.",
        )
    )
    return records


def flatten_offeneregister(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """offeneregister.de mirrors the German commercial register as open data. The dump is
    multi-GB, so only the record structure is indexed: what the register records about a company,
    which is what decides whether it is worth downloading."""
    records: List[Dict[str, Any]] = []
    for field, label, gloss in OFFENEREGISTER_FIELDS:
        records.append(
            make_record(
                source_key="offeneregister",
                source_label="Open Data Handelsregister (offeneregister.de)",
                item_type="register_attribute",
                item_id=f"offeneregister:{field}",
                variable_name=field,
                label=f"{label} (Handelsregister)",
                dataset_label="offeneregister Unternehmensdaten",
                theme="Wirtschaft und Unternehmen",
                description=join_nonempty([
                    gloss,
                    "Merkmal im offenen Abzug des deutschen Handelsregisters (JSONL bzw. SQLite, "
                    "mehrere Gigabyte, CC-BY). Adressgenau und damit auf PLZ-, Gemeinde- oder "
                    "Kreisebene aggregierbar, etwa für Unternehmensdichte, Gründungen und "
                    "Löschungen im Zeitverlauf.",
                ]),
                spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "Kreise"],
                nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU", "Kreise", "NUTS3"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url="https://offeneregister.de/daten/",
                link_level="dataset",
                access_modes=["direct file download", "machine-readable API"],
                update_frequency=source["update_frequency"] or "laufend",
                api_hint=f"Feld {field} in de_companies_ocdata.jsonl bzw. openregister.db von offeneregister.de.",
            )
        )
    return records


def flatten_destatis_mobility(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Destatis experimental statistic on regional mobility from mobile-network data. It was
    discontinued in 2022, but the series stays citable, so its indicator groups are indexed from
    the saved page with the discontinuation stated on every record."""
    page_path = source["folder"] / "raw" / "portal.html"
    if not page_path.exists():
        return []
    page = page_path.read_text(encoding="utf-8", errors="replace")
    headings = [strip_tags(match) for match in re.findall(r"<h[23][^>]*>(.*?)</h[23]>", page, re.S)]
    wanted = [h for h in dict.fromkeys(headings)
              if re.search(r"mobilit|distanz|bewegung|verkehrsträger|tagesverlauf", h, re.I)
              and not h.lower().startswith("mehr zum")]

    records: List[Dict[str, Any]] = []
    for heading in wanted:
        records.append(
            make_record(
                source_key="destatis_mobilitaet",
                source_label="Regionale Mobilität und Infektionsgeschehen (Destatis, experimentell)",
                item_type="regional_indicator",
                item_id=f"destatis_mobilitaet:{heading.lower()[:50]}",
                variable_name=heading,
                label=f"{heading} (Mobilfunkdaten)",
                dataset_label="Mobilitätsindikatoren aus Mobilfunkdaten",
                theme="Verkehr / Mobilität",
                description=join_nonempty([
                    f"Indikatorgruppe '{heading}' der experimentellen Statistik zur regionalen "
                    "Mobilität, berechnet aus anonymisierten Mobilfunkdaten auf Kreisebene, "
                    "wöchentlich für den Zeitraum 2020 bis 2022.",
                    "Hinweis: Das Angebot wird nicht mehr aktualisiert. Die historische Reihe bleibt "
                    "zitierbar und ist für die Pandemiejahre die einzige flächendeckende Quelle zu "
                    "tatsächlicher Bewegung statt gemeldeter Pendlerwege.",
                ]),
                spatial_levels=["Kreise"],
                nuts_levels=["Kreise", "NUTS3"],
                year_start=2020,
                year_end=2022,
                years_text="2020-2022, wöchentlich (eingestellt)",
                source_url=source["url"],
                indicator_url=source["url"],
                link_level="dataset",
                access_modes=source["access_modes"],
                update_frequency="eingestellt",
                status="discontinued",
                api_hint="Indikatorgruppe der EXSTAT-Seite 'Mobilitätsindikatoren auf Basis von Mobilfunkdaten'.",
            )
        )
    return records


# ---------------------------------------------------------------------------
# OpenStreetMap POI layers
# ---------------------------------------------------------------------------
# What each layer is good for, in the language a researcher would search in. The counts and the
# tag list come from raw/taginfo_counts.json, so nothing here restates a number.
OSM_LAYER_NOTES: Dict[str, str] = {
    "playground": "Öffentliche Spielplätze. Der systematische Ersatz für die Spielplatzportale: "
                  "punktgenau, bundesweit einheitlich getaggt und damit als Distanz zum nächsten "
                  "Spielplatz oder als Spielplatzdichte je Gemeinde auswertbar.",
    "pharmacy": "Apotheken. Grundlage für Apothekendichte und Distanz zur nächsten Apotheke, "
                "kleinräumiger als die Erreichbarkeitsindikatoren des Deutschlandatlas.",
    "doctors": "Arztpraxen (Allgemein- und Fachärzte). Punktgenaue Alternative zur Arztsuche der "
               "Bundesärztekammer, die keinen Export anbietet.",
    "dentist": "Zahnarztpraxen.",
    "hospital": "Krankenhausstandorte. Ergänzt das G-BA-Verzeichnis und den Klinik-Atlas um eine "
                "punktgenaue, frei nutzbare Standortgeometrie.",
    "clinic": "Kliniken, Ambulanzen und medizinische Versorgungszentren ohne Vollversorgung.",
    "school": "Schulstandorte aller Schularten. Für Schuldichte und Schulwegdistanzen; die "
              "Schulart steht im Tag school:DE bzw. isced:level.",
    "kindergarten": "Kindergärten, Kitas und Krippen. Punktgenaue Ergänzung zur Betreuungsquote "
                    "aus INKAR und dem Ländermonitor.",
    "university": "Hochschulen und Colleges. Punktgeometrie zum Hochschulkompass-Register.",
    "library": "Öffentliche und wissenschaftliche Bibliotheken.",
    "place_of_worship": "Gotteshäuser aller Religionen; die Konfession steht im Tag religion "
                        "bzw. denomination. Für Distanz zum nächsten Gotteshaus.",
    "cinema": "Kinos.",
    "theatre": "Theater und Bühnen.",
    "restaurant": "Gastronomiebetriebe (Restaurants, Cafés, Imbisse, Kneipen, Bars). Für "
                  "Gastronomiedichte je Einwohner.",
    "supermarket": "Supermärkte. Kernindikator für Nahversorgung und Lebensmittelerreichbarkeit.",
    "bank": "Bankfilialen. Für Filialdichte und Filialabbau im Zeitverlauf.",
    "post_office": "Postfilialen und Postagenturen.",
    "social_facility": "Soziale Einrichtungen: Pflegeheime, Tagespflege, Tafeln, Beratungsstellen, "
                       "Obdachlosenhilfe. Die Art steht im Tag social_facility bzw. "
                       "social_facility:for.",
    "community_centre": "Bürgerhäuser, Gemeindezentren und Nachbarschaftstreffs. Näherung für "
                        "soziale Infrastruktur und Treffpunkte.",
    "bus_stop": "Bushaltestellen. Feinste verfügbare ÖPNV-Punktebene ohne Fahrplanbezug; für "
                "Fahrplandaten siehe Open Data ÖPNV (GTFS/NeTEx).",
    "railway_station": "Bahnhöfe und Haltepunkte. Ergänzt die StaDa-Bahnhofsdaten um Stationen "
                       "ohne DB-Bezug (S-Bahn-, Tram- und Privatbahnstationen).",
    "sports": "Sportanlagen: Sportzentren, Spielfelder, Fitnessstudios, Schwimmbäder.",
    "park": "Parks und öffentliche Gärten. Für Grünflächenversorgung und Distanz zur nächsten "
            "Grünfläche.",
    "charging_station": "Ladesäulen für Elektroautos. Feinere Alternative zum "
                        "Erreichbarkeitsindikator des Deutschlandatlas.",
    "police": "Polizeidienststellen und Feuerwachen.",
    "fuel": "Tankstellen.",
}


def flatten_osm_poi(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per OSM POI layer, with the object count measured for Germany.

    OSM is the systematic answer to the workbook rows that are only a search mask (playgrounds,
    physician search): the tags are documented, the extract is free, and every object carries
    coordinates. What a researcher needs from us is the tag filter, so the record carries the
    ready Overpass query and links to the tag's own wiki page.
    """
    path = source["folder"] / "raw" / "taginfo_counts.json"
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    as_of = (document.get("data_until") or "")[:10]

    records: List[Dict[str, Any]] = []
    for key, info in (document.get("layers") or {}).items():
        tags = list((info.get("tags") or {}).keys())
        if not tags:
            continue
        first_key, first_value = tags[0].split("=", 1)
        total = info.get("total")
        counted = (f"In Deutschland etwa {total:,} Objekte".replace(",", ".") + f" (taginfo, Stand {as_of})."
                   if total else "")
        if len(tags) > 1:
            counted += " Der Layer fasst mehrere Tags zusammen: " + ", ".join(tags) + "."
        records.append(
            make_record(
                source_key="osm_poi",
                source_label="OpenStreetMap POI-Layer (Overpass)",
                item_type="poi_layer",
                item_id=f"osm:{key}",
                variable_name=tags[0],
                label=f"{info.get('label', key)} (OpenStreetMap)",
                dataset_label="OpenStreetMap POI-Layer",
                theme="Infrastruktur & Erreichbarkeit",
                description=join_nonempty([OSM_LAYER_NOTES.get(key, ""), counted]),
                spatial_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "PLZ", "Gemeinden", "LAU", "Kreise", "NUTS3",
                             "Bundesländer", "NUTS1"],
                year_start=2004,
                year_end=int(as_of[:4]) if as_of[:4].isdigit() else None,
                years_text=f"2004-{as_of[:4]}" if as_of[:4].isdigit() else "laufend",
                source_url=f"https://wiki.openstreetmap.org/wiki/Tag:{first_key}%3D{first_value}",
                indicator_url=f"https://wiki.openstreetmap.org/wiki/Tag:{first_key}%3D{first_value}",
                link_level="indicator",
                access_modes=["machine-readable API", "direct file download"],
                update_frequency="laufend",
                api_hint="Overpass-Abfrage für Deutschland: "
                         '[out:json][timeout:600];area["ISO3166-1"="DE"][admin_level=2]->.de;'
                         f"nwr{info.get('selector', '')}(area.de);out center; "
                         "Alternativ Geofabrik-Auszug (.osm.pbf) und lokale Filterung; "
                         f"Zählstand über https://taginfo.geofabrik.de/europe:germany/tags/{tags[0]}",
            )
        )
    return records


# ---------------------------------------------------------------------------
# Wegweiser Kommune
# ---------------------------------------------------------------------------
# The site is a Liferay app whose indicator tree loads client-side, so the products are named
# here and every record links to the one page that does exist (/daten). Each entry is
# (id, label, description).
WEGWEISER_PRODUCTS: List[Tuple[str, str, str]] = [
    ("indikatoren", "Kommunale Indikatoren (Wegweiser Kommune)",
     "Rund 100 Indikatoren zu Demografie, Bildung, Arbeitsmarkt, Soziales, Finanzen und Wohnen "
     "für alle Gemeinden ab 5.000 Einwohnern, Kreise und Bundesländer. Frei abrufbar und als "
     "Tabelle exportierbar."),
    ("bevoelkerungsprognose", "Bevölkerungsprognose bis 2040 (Wegweiser Kommune)",
     "Kleinräumige Bevölkerungsvorausberechnung nach Alter und Geschlecht bis 2040 für Gemeinden "
     "ab 5.000 Einwohnern. Die einzige Projektionsebene in dieser Sammlung: INKAR und die "
     "amtliche Statistik liefern Bestände, keine kommunalen Prognosen."),
    ("demografietypen", "Demografietypen der Kommunen (Wegweiser Kommune)",
     "Typisierung der Kommunen nach demografischer Ausgangslage und Entwicklung (Demografietypen). "
     "Erlaubt Vergleichsgruppen für Fallauswahl und Matching."),
    ("kommunalprofile", "Kommunalprofile und Berichte (Wegweiser Kommune)",
     "Zusammenfassende Profile je Kommune mit Zeitreihen und Vergleichswerten, als PDF und Tabelle."),
]


def flatten_wegweiser(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Wegweiser Kommune: indexed at product level.

    The indicator tree is rendered client-side and /statistik redirects to /daten, so there is no
    machine-readable indicator list to flatten. What is indexed is what the portal offers, above
    all the municipal population projection to 2040, which nothing else here has.
    """
    landing = "https://www.wegweiser-kommune.de/daten"
    records: List[Dict[str, Any]] = []
    for key, label, description in WEGWEISER_PRODUCTS:
        records.append(
            make_record(
                source_key="wegweiser_kommune",
                source_label="Wegweiser Kommune (Bertelsmann Stiftung)",
                item_type="dataset",
                item_id=f"wegweiser:{key}",
                variable_name=key,
                label=label,
                dataset_label="Wegweiser Kommune",
                theme="Bevölkerung & Kommunalentwicklung",
                description=description,
                spatial_levels=["Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Gemeinden", "LAU", "Kreise", "NUTS3", "Bundesländer", "NUTS1"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url=landing,
                link_level="dataset",
                access_modes=source["access_modes"] or ["direct file download", "interactive map viewer"],
                update_frequency=source["update_frequency"] or "jährlich",
                api_hint="Abruf über wegweiser-kommune.de/daten (Auswahl von Kommune, Thema und "
                         "Jahr, Export als XLSX/CSV). Keine offene API; der Indikatorenbaum wird "
                         "clientseitig geladen.",
            )
        )
    return records


# ---------------------------------------------------------------------------
# DWD Climate Data Center
# ---------------------------------------------------------------------------
DWD_VARIABLES: Dict[str, str] = {
    "air_temperature": "Lufttemperatur",
    "air_temperature_max": "Maximum der Lufttemperatur",
    "air_temperature_mean": "Mittel der Lufttemperatur",
    "air_temperature_min": "Minimum der Lufttemperatur",
    "climate_indices": "Klimaindizes (u. a. Hitze-, Frost- und Vegetationskennzahlen)",
    "cloud_type": "Wolkenart",
    "cloudiness": "Bedeckungsgrad",
    "dew_point": "Taupunkttemperatur",
    "drought_index": "Trockenheitsindex (de Martonne)",
    "duett": "Deutsches Wetterdienst-Testreferenzjahr (DUETT)",
    "erosivity": "Erosivität des Niederschlags (R-Faktor)",
    "evapo_p": "Potenzielle Verdunstung",
    "evapo_r": "Reale Verdunstung",
    "evaporation_fao": "Verdunstung nach FAO-Referenzverfahren",
    "extreme_temperature": "Extremwerte der Temperatur",
    "extreme_wind": "Extremwerte des Windes",
    "frost_days": "Frosttage",
    "frost_depth": "Frosteindringtiefe",
    "hostrada": "HOSTRADA: stündliche Rasterdaten für urbane Räume",
    "hot_days": "Heiße Tage (Maximum ab 30 Grad)",
    "hyras_de": "HYRAS: hydrometeorologische Rasterdaten",
    "ice_days": "Eistage (Maximum unter 0 Grad)",
    "kl": "Klimastandardwerte der Stationen (Temperatur, Niederschlag, Sonne, Wind, Feuchte)",
    "moisture": "Luftfeuchte",
    "more_precip": "Niederschlag der Niederschlagsstationen (inkl. Schneehöhe)",
    "more_weather_phenomena": "Weitere Wettererscheinungen",
    "phenology": "Phänologie (Eintrittstermine der Pflanzenentwicklung)",
    "precipGE10mm_days": "Tage mit mindestens 10 mm Niederschlag",
    "precipGE20mm_days": "Tage mit mindestens 20 mm Niederschlag",
    "precipGE30mm_days": "Tage mit mindestens 30 mm Niederschlag",
    "precipitation": "Niederschlagshöhe",
    "pressure": "Luftdruck",
    "radiation_diffuse": "Diffuse Sonnenstrahlung",
    "radiation_direct": "Direkte Sonnenstrahlung",
    "radiation_global": "Globalstrahlung",
    "radolan": "RADOLAN: radargestützte Niederschlagshöhe",
    "regnie": "REGNIE: regionalisierte Niederschlagshöhe",
    "snowcover_days": "Tage mit Schneedecke",
    "soil": "Bodenklima (Temperatur und Feuchte im Boden)",
    "soil_moist": "Bodenfeuchte",
    "soil_moisture": "Bodenfeuchte",
    "soil_temperature": "Bodentemperatur",
    "soil_temperature_5cm": "Bodentemperatur in 5 cm Tiefe",
    "solar": "Strahlung und Sonnenscheindauer",
    "summer_days": "Sommertage (Maximum ab 25 Grad)",
    "sun": "Sonnenscheindauer",
    "sunshine_duration": "Sonnenscheindauer",
    "vegetation_begin": "Beginn der Vegetationsperiode",
    "vegetation_end": "Ende der Vegetationsperiode",
    "visibility": "Sichtweite",
    "water_balance": "Klimatische Wasserbilanz",
    "water_equiv": "Wasseräquivalent der Schneedecke",
    "weather_phenomena": "Wettererscheinungen (Gewitter, Hagel, Nebel, Sturm)",
    "wind": "Windgeschwindigkeit und Windrichtung",
    "wind_parameters": "Windparameter (Weibull-Verteilung)",
    "wind_synop": "Wind aus SYNOP-Meldungen",
    "moisture_": "Luftfeuchte",
}

DWD_AGGREGATIONS: Dict[str, str] = {
    "1_minute": "Minutenwerte",
    "5_minutes": "5-Minuten-Werte",
    "10_minutes": "10-Minuten-Werte",
    "hourly": "Stundenwerte",
    "subdaily": "Terminwerte (mehrmals täglich)",
    "daily": "Tageswerte",
    "monthly": "Monatswerte",
    "seasonal": "Jahreszeitenwerte",
    "halfyear": "Halbjahreswerte",
    "annual": "Jahreswerte",
    "multi_annual": "Vieljährige Mittelwerte (Klimanormalperioden)",
    "return_periods": "Wiederkehrintervalle (Starkniederschlag)",
}


def flatten_dwd(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DWD Climate Data Center, indexed from the real directory tree.

    opendata.dwd.de is an open Apache index, so the tree IS the catalogue: one record per
    (grid or station) x aggregation x variable, each linking to the directory that holds the
    files. Directories that are documentation, obsolete duplicates or project-specific bundles
    are skipped rather than dressed up as indicators.
    """
    path = source["folder"] / "raw" / "cdc_tree.json"
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    root = document.get("root", "https://opendata.dwd.de/climate_environment/CDC").rstrip("/")

    branch_labels = {
        "grids_germany": ("Rasterdaten (1 km) für Deutschland",
                          ["Rasterzellen", "Gemeinden", "Kreise", "Bundesländer"],
                          ["Rasterzellen", "Gemeinden", "LAU", "Kreise", "NUTS3",
                           "Bundesländer", "NUTS1"]),
        "observations_germany/climate": ("Stationsmessungen der DWD-Klimastationen",
                                         ["Adressen/Koordinaten", "Kreise", "Bundesländer"],
                                         ["Adressen/Koordinaten", "Kreise", "NUTS3",
                                          "Bundesländer", "NUTS1"]),
    }

    records: List[Dict[str, Any]] = []
    for branch, aggregations in (document.get("tree") or {}).items():
        if branch not in branch_labels:
            continue
        branch_label, levels, nuts = branch_labels[branch]
        for aggregation, variables in sorted(aggregations.items()):
            aggregation_label = DWD_AGGREGATIONS.get(aggregation, aggregation)
            for variable in sorted(variables):
                if (variable.startswith("__error__") or variable.startswith("Project_")
                        or "obsolete" in variable or variable in {"standard_format", "wind_test"}):
                    continue
                gloss = DWD_VARIABLES.get(variable)
                if not gloss and variable.startswith("mean_"):
                    gloss = f"Vieljähriges Mittel der Periode {variable.replace('mean_', '')}"
                if not gloss:
                    continue
                grid = branch == "grids_germany"
                records.append(
                    make_record(
                        source_key="dwd_cdc",
                        source_label="DWD Climate Data Center (CDC)",
                        item_type="climate_dataset",
                        item_id=f"dwd:{branch.replace('/', '_')}:{aggregation}:{variable}",
                        variable_name=f"{aggregation}/{variable}",
                        label=f"{gloss}, {aggregation_label} "
                              f"({'1-km-Raster' if grid else 'Stationen'})",
                        dataset_label=branch_label,
                        theme="Klima & Umwelt",
                        description=f"{gloss}, {aggregation_label.lower()}, als "
                                    f"{'flächendeckendes 1-km-Raster für Deutschland' if grid else 'Messreihe der DWD-Klimastationen'}. "
                                    "Offen und ohne Anmeldung herunterladbar (Datenlizenz "
                                    "Deutschland, Namensnennung). "
                                    + ("Rasterzellen sind auf Gemeinde-, Kreis- oder Landesebene "
                                       "aggregierbar und damit mit der Regionalstatistik verknüpfbar."
                                       if grid else
                                       "Stationen sind punktgenau (Koordinaten in der "
                                       "Stationsliste) und lassen sich Gemeinden zuordnen."),
                        spatial_levels=levels,
                        nuts_levels=nuts,
                        year_start=source["coverage_start_year"],
                        year_end=source["coverage_end_year"],
                        years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                        source_url=f"{root}/{branch}/{aggregation}/{variable}/",
                        indicator_url=f"{root}/{branch}/{aggregation}/{variable}/",
                        link_level="dataset",
                        access_modes=["direct file download", "machine-readable API"],
                        update_frequency=source["update_frequency"] or "laufend",
                        api_hint=f"Verzeichnis {branch}/{aggregation}/{variable}/ auf "
                                 "opendata.dwd.de; die DESCRIPTION- und BESCHREIBUNG-PDFs im "
                                 "Verzeichnis dokumentieren Format, Einheit und Stationsliste.",
                    )
                )
    return records


# ---------------------------------------------------------------------------
# BORIS-D (Bodenrichtwerte)
# ---------------------------------------------------------------------------
GERMAN_STATES: List[str] = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen",
    "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz",
    "Saarland", "Sachsen-Anhalt", "Sachsen", "Schleswig-Holstein", "Thüringen",
]

BORIS_PRODUCTS: List[Tuple[str, str, str]] = [
    ("bodenrichtwert", "Bodenrichtwert (zonal und lagetypisch)",
     "Durchschnittlicher Lagewert des Bodens je Quadratmeter für eine Bodenrichtwertzone, "
     "jährlich zum Stichtag 1. Januar von den Gutachterausschüssen beschlossen. Der amtliche "
     "Bodenpreis und damit das Gegenstück zu den Mietpreisen in INKAR."),
    ("bodenrichtwertzone", "Bodenrichtwertzone (Geometrie)",
     "Flächengeometrie der Bodenrichtwertzone, auf die sich ein Bodenrichtwert bezieht. "
     "Kleinräumiger als jede Verwaltungsebene und damit auf Gemeinde- oder Kreisebene "
     "aggregierbar."),
    ("beitragszustand", "Entwicklungs- und Beitragszustand der Fläche",
     "Entwicklungszustand (Bauland, Rohbauland, Bauerwartungsland, land- und "
     "forstwirtschaftliche Fläche) und beitragsrechtlicher Zustand der Bodenrichtwertzone. "
     "Bestimmt, was ein Bodenrichtwert vergleichbar macht."),
    ("nutzungsart", "Art der Nutzung (Bodenrichtwert)",
     "Vorherrschende Nutzungsart der Zone (Wohnbaufläche, gemischte Baufläche, Gewerbe, "
     "Sonderbaufläche) samt Maß der baulichen Nutzung (GFZ, WGFZ)."),
    ("immobilienrichtwert", "Immobilienrichtwerte und Grundstücksmarktberichte",
     "Ergänzende Auswertungen der Gutachterausschüsse: Immobilienrichtwerte, Umsätze, "
     "Liegenschaftszinssätze und Marktberichte je Gutachterausschussbezirk."),
]


def flatten_boris(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """BORIS-D: indexed by concept plus one record per Land.

    BORIS-D is a viewer over sixteen Länder services and publishes no catalogue of its own, so
    the coverage evidence comes from the official GDI-DE metadata catalogue: how many
    Bodenrichtwerte datasets each Land has registered there. Per-Kreis-per-year entries are
    deliberately NOT indexed as records; a concept query is about the Bodenrichtwert, not about
    one district in one year.
    """
    path = source["folder"] / "raw" / "csw_bodenrichtwerte.xml"
    titles: List[str] = []
    matched = 0
    if path.exists():
        xml = path.read_text(encoding="utf-8", errors="replace")
        titles = re.findall(r"<dc:title>([^<]+)</dc:title>", xml)
        found = re.search(r'matched="(\d+)"', xml)
        matched = int(found.group(1)) if found else len(titles)

    portal = "https://www.bodenrichtwerte-boris.de/boris-d/"
    catalogue_note = (f"Der Geodatenkatalog des Bundes und der Länder führt {matched} Metadatensätze "
                      "zu Bodenrichtwerten (Suche: AnyText like '%bodenrichtwert%' über die "
                      "CSW-Schnittstelle von gdk.gdi-de.org)." if matched else "")

    records: List[Dict[str, Any]] = []
    for key, label, description in BORIS_PRODUCTS:
        records.append(
            make_record(
                source_key="boris_d",
                source_label="BORIS-D Bodenrichtwerte (Gutachterausschüsse der Länder)",
                item_type="regional_indicator",
                item_id=f"boris:{key}",
                variable_name=key,
                label=label,
                dataset_label="BORIS-D Bodenrichtwertinformationssystem",
                theme="Bauen & Wohnen",
                description=join_nonempty([description, catalogue_note]),
                spatial_levels=["Adressen/Koordinaten", "Weitere Gliederungen", "Gemeinden",
                                "Kreise", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "Gemeinden", "LAU", "Kreise", "NUTS3",
                             "Bundesländer", "NUTS1"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=portal,
                indicator_url=portal,
                link_level="portal",
                access_modes=source["access_modes"] or ["interactive map viewer", "machine-readable API"],
                update_frequency=source["update_frequency"] or "jährlich",
                api_hint="BORIS-D bündelt die Länderportale; Abruf je Land über dessen WMS/WFS "
                         "(INSPIRE-Thema Bodennutzung). Nutzungsbedingungen und Entgelte "
                         "unterscheiden sich je Land.",
            )
        )

    # Per-Land service endpoints, resolved from the GDI-DE catalogue by
    # scripts/resolve_boris_services.py. 14 of 16 Laender publish one there; Baden-Wuerttemberg
    # and Berlin do not, and keep the BORIS-D portal link rather than a guessed one.
    services_path = source["folder"] / "raw" / "boris_services.json"
    services: Dict[str, Any] = {}
    if services_path.exists():
        services = json.loads(services_path.read_text(encoding="utf-8")).get("states") or {}

    for state in GERMAN_STATES:
        count = sum(1 for title in titles if state.lower() in title.lower())
        service = services.get(state) or {}
        endpoint = service.get("capabilities") or service.get("portal") or ""
        records.append(
            make_record(
                source_key="boris_d",
                source_label="BORIS-D Bodenrichtwerte (Gutachterausschüsse der Länder)",
                item_type="dataset",
                item_id=f"boris:land:{re.sub(r'[^a-z]+', '_', state.lower()).strip('_')}",
                variable_name=state,
                label=f"Bodenrichtwerte {state}",
                dataset_label="BORIS-D nach Bundesland",
                theme="Bauen & Wohnen",
                description=f"Bodenrichtwerte und Bodenrichtwertzonen für {state}, geführt vom "
                            "zuständigen Gutachterausschuss bzw. der Landesvermessung und über "
                            "BORIS-D gebündelt. "
                            + (f"Im Geodatenkatalog des Bundes und der Länder sind dazu {count} "
                               "Metadatensätze verzeichnet. " if count else "")
                            + (f"Eigener Dienst des Landes: {service.get('title', '')}"
                               + (f" ({service.get('organisation')})." if service.get("organisation") else ".")
                               if endpoint else
                               "Für dieses Land führt der Geodatenkatalog keinen landesweiten "
                               "Dienst; der Zugang läuft über BORIS-D."),
                spatial_levels=["Adressen/Koordinaten", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Adressen/Koordinaten", "Gemeinden", "LAU", "Kreise", "NUTS3",
                             "Bundesländer", "NUTS1"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=endpoint or portal,
                indicator_url=endpoint or portal,
                # A Land with its own service gets a dataset-level link that was probed (all 14
                # answered HTTP 200); the two without keep the portal link.
                link_level="dataset" if endpoint else "portal",
                link_verified=True,
                access_modes=source["access_modes"] or ["interactive map viewer"],
                update_frequency=source["update_frequency"] or "jährlich",
                api_hint=(f"Landesdienst: {endpoint}. " if endpoint else "")
                         + f"Alternativ in BORIS-D das Land {state} wählen. Die Landesdienste "
                         "sind im Geodatenkatalog (gdk.gdi-de.org) mit WMS/WFS-Adresse "
                         "verzeichnet; Nutzungsbedingungen und Entgelte unterscheiden sich je Land.",
            )
        )
    return records


# ---------------------------------------------------------------------------
# Election results (Bundeswahlleiterin)
# ---------------------------------------------------------------------------
ELECTION_SYSTEM_GROUPS: Dict[str, str] = {
    "Wahlberechtigte": "Zahl der Wahlberechtigten im Gebiet. Nenner für die Wahlbeteiligung.",
    "Wählende": "Zahl der Wählenden, absolut und als Wahlbeteiligung in Prozent.",
    "Ungültige": "Ungültige Erst- und Zweitstimmen, absolut und in Prozent.",
    "Gültige": "Gültige Erst- und Zweitstimmen, der Nenner aller Stimmenanteile.",
}

ELECTION_DATASETS: List[Tuple[str, str, str, str, str]] = [
    ("btw2025_kerg2",
     "Wahlkreisergebnisse Bundestagswahl 2025 (kerg2, Langformat)",
     "Endgültiges Ergebnis der Bundestagswahl 2025 für Bund, Länder und alle 299 Wahlkreise: "
     "Wahlberechtigte, Wählende, gültige und ungültige Erst- und Zweitstimmen sowie Stimmen je "
     "Partei, jeweils mit dem Vergleichswert der Vorwahl. Langformat, eine Zeile je Gebiet, "
     "Gruppe und Stimme.",
     "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html",
     "btw25_kerg2.csv"),
    ("btw2025_kerg",
     "Wahlkreisergebnisse Bundestagswahl 2025 (kerg, Breitformat)",
     "Dasselbe Ergebnis in der klassischen breiten Darstellung, eine Zeile je Gebiet und eine "
     "Spalte je Partei und Stimme. Das übliche Format für Wahlkreisanalysen.",
     "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html",
     "btw25_kerg.csv"),
    ("btw_ab1949",
     "Bundestagswahlergebnisse seit 1949 nach Ländern",
     "Wahlberechtigte, Wählende, Stimmabgabe und Sitzverteilung für jede Bundestagswahl seit "
     "1949 nach Ländern. Die Zeitreihe für Langfristvergleiche.",
     "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html",
     "btw_ab49_datenbank_ergebnisse.csv"),
    ("btw_briefwahl",
     "Brief- und Urnenwahl sowie Wahlscheine seit 1957",
     "Aufteilung in Urnen- und Briefwahl und Zahl der Wahlscheine seit 1957. Grundlage für "
     "Analysen des Briefwahlanteils.",
     "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html",
     "btw_ab57_brief_urne.csv"),
    ("europawahl2024",
     "Ergebnisse der Europawahl 2024",
     "Ergebnis der Europawahl 2024 für Bund, Länder, Kreise und Gemeinden: Wahlberechtigte, "
     "Wählende, gültige Stimmen und Stimmen je Partei. Die Gemeindeebene macht sie feiner als "
     "die Bundestagswahlergebnisse.",
     "https://www.bundeswahlleiterin.de/europawahlen/2024/ergebnisse.html",
     "ew24_kerg.csv"),
]


def flatten_wahlergebnisse(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Election results: the result variables come from the 2025 kerg2 file itself.

    The parties are read out of the data rather than typed, and only those that stood nationwide
    (present at Bund level) get their own record; the many single-Land lists would otherwise
    bury everything else in near-identical rows.
    """
    raw = source["folder"] / "raw"
    kerg2 = raw / "btw2025_kerg2.csv"

    parties: List[str] = []
    areas: Dict[str, int] = {}
    if kerg2.exists():
        lines = kerg2.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        start = next((index for index, line in enumerate(lines) if line.startswith("Wahlart;")), None)
        if start is not None:
            header = lines[start].split(";")
            kind = header.index("Gruppenart")
            name = header.index("Gruppenname")
            area = header.index("Gebietsart")
            national: set = set()
            for line in lines[start + 1:]:
                fields = line.split(";")
                if len(fields) <= name:
                    continue
                areas[fields[area]] = areas.get(fields[area], 0) + 1
                if fields[kind] == "Partei" and fields[area] == "Bund":
                    national.add(fields[name])
            parties = sorted(national)

    records: List[Dict[str, Any]] = []
    for group, description in ELECTION_SYSTEM_GROUPS.items():
        records.append(
            make_record(
                source_key="wahlergebnisse",
                source_label="Wahlergebnisse der Bundeswahlleiterin",
                item_type="regional_indicator",
                item_id=f"wahl:system:{group.lower()}",
                variable_name=group,
                label=f"{group} (Wahlergebnis)",
                dataset_label="Bundestags- und Europawahlergebnisse",
                theme="Politik / Wahlen",
                description=description + " Verfügbar für Bund, Länder und Wahlkreise, bei "
                            "Europawahlen zusätzlich für Kreise und Gemeinden.",
                spatial_levels=["Bundestagswahlkreise", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Bundestagswahlkreise", "Gemeinden", "LAU", "Kreise", "NUTS3",
                             "Bundesländer", "NUTS1"],
                year_start=1949,
                year_end=2025,
                years_text="1949-2025",
                source_url=source["url"],
                indicator_url="https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html",
                link_level="dataset",
                access_modes=["direct file download"],
                update_frequency="je Wahl",
                api_hint=f"Gruppenname '{group}' (Gruppenart System-Gruppe) in den kerg2-Dateien "
                         "der Bundeswahlleiterin; im kerg-Breitformat eine eigene Spalte.",
            )
        )

    for party in parties:
        records.append(
            make_record(
                source_key="wahlergebnisse",
                source_label="Wahlergebnisse der Bundeswahlleiterin",
                item_type="regional_indicator",
                item_id="wahl:partei:" + re.sub(r"[^a-z0-9]+", "_", party.lower()).strip("_")[:48],
                variable_name=party,
                label=f"Stimmen für {party} (Wahlergebnis)",
                dataset_label="Bundestags- und Europawahlergebnisse",
                theme="Politik / Wahlen",
                description=f"Erst- und Zweitstimmen für {party}, absolut und als Anteil der "
                            "gültigen Stimmen, für Bund, Länder und alle Wahlkreise, mit dem "
                            "Vergleichswert der Vorwahl. Bundesweit angetreten zur "
                            "Bundestagswahl 2025.",
                spatial_levels=["Bundestagswahlkreise", "Bundesländer"],
                nuts_levels=["Bundestagswahlkreise", "Bundesländer", "NUTS1"],
                year_start=2025,
                year_end=2025,
                years_text="2025 (Zeitreihe je Wahl ab 1949)",
                source_url=source["url"],
                indicator_url="https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html",
                link_level="dataset",
                access_modes=["direct file download"],
                update_frequency="je Wahl",
                api_hint=f"Gruppenname '{party}' (Gruppenart Partei) in btw25_kerg2.csv; "
                         "im kerg-Breitformat je eine Spalte für Erst- und Zweitstimmen.",
            )
        )

    for key, label, description, page, filename in ELECTION_DATASETS:
        records.append(
            make_record(
                source_key="wahlergebnisse",
                source_label="Wahlergebnisse der Bundeswahlleiterin",
                item_type="dataset",
                item_id=f"wahl:datensatz:{key}",
                variable_name=key,
                label=label,
                dataset_label="Bundestags- und Europawahlergebnisse",
                theme="Politik / Wahlen",
                description=description,
                spatial_levels=(["Bundestagswahlkreise", "Gemeinden", "Kreise", "Bundesländer"]
                                if "europawahl" in key else
                                ["Bundestagswahlkreise", "Bundesländer"]),
                nuts_levels=(["Bundestagswahlkreise", "Gemeinden", "LAU", "Kreise", "NUTS3",
                              "Bundesländer", "NUTS1"] if "europawahl" in key else
                             ["Bundestagswahlkreise", "Bundesländer", "NUTS1"]),
                year_start=1949 if "ab1949" in key or "briefwahl" in key else (2024 if "europa" in key else 2025),
                year_end=2025 if "europa" not in key else 2024,
                years_text=("1949-2025" if "ab1949" in key else
                            ("1957-2025" if "briefwahl" in key else
                             ("2024" if "europa" in key else "2025"))),
                source_url=source["url"],
                indicator_url=page,
                link_level="dataset",
                access_modes=["direct file download"],
                update_frequency="je Wahl",
                api_hint=f"CSV {filename}, abrufbar über {page} "
                         "(Datenlizenz Deutschland, Namensnennung 2.0).",
            )
        )
    return records


# ---------------------------------------------------------------------------
# IÖR-Monitor
# ---------------------------------------------------------------------------
# What each indicator category covers, so a record says more than its own name. The indicators
# themselves are NOT hand-written: they are read from the monitor's own public list.
IOER_CATEGORIES: Dict[str, str] = {
    "N": "Nachhaltigkeit: Flächenneuinanspruchnahme und Flächenverbrauch, die Indikatoren hinter "
         "dem 30-Hektar-Ziel der Nachhaltigkeitsstrategie.",
    "S": "Siedlung: Anteile von Siedlungs-, Industrie- und Gewerbeflächen an der Gebietsfläche, "
         "aus Geobasisdaten (ATKIS) berechnet und damit unabhängig von der Flächenerhebung nach "
         "Nutzungsart.",
    "F": "Freiraum: Freiraumanteile, unzerschnittene Freiräume und ihre Entwicklung.",
    "V": "Verkehr: Verkehrsflächen, Straßennetzdichte und Erschließung.",
    "G": "Gebäude: Gebäudebestand, Wohn- und Mischnutzflächen.",
    "B": "Bevölkerung: Einwohnerdichten bezogen auf Siedlungs- und Freiraumflächen.",
    "D": "Zersiedelung: Dispersion und Durchdringung der Landschaft mit Siedlung.",
    "U": "Landschaftsqualität: Hemerobie, naturbetonte Flächen und Landschaftszerschneidung.",
    "L": "Landschafts- und Naturschutz: Anteile geschützter Flächen.",
    "O": "Ökosystemleistungen: Regulations- und Erholungsleistungen der Landschaft.",
    "E": "Energie: Flächen für erneuerbare Energien.",
    "X": "Relief: Hangneigung und Reliefenergie.",
    "M": "Materiallager: im Gebäudebestand gebundene Materialmengen.",
}


def flatten_ioer(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """IÖR-Monitor: all 88 indicators, from the monitor's own public indicator list.

    The list was assumed to be behind the user area; it is not. The "Übersicht der Geodienste"
    section of /indikatoren/ links a public PDF with every indicator, its five-character code and
    its category, and the codes are what address the WMS/WCS/WFS services. The service CALL still
    needs a personal key (an unauthenticated call answers a WMS ServiceException), so the records
    link to the indicator overview page and carry the code and the call pattern instead of a
    per-indicator link that would not open for anyone.
    """
    pdf = source["folder"] / "raw" / "indikatoren_liste.pdf"
    if not pdf.exists():
        return []
    text = _pdf_text(pdf, layout=True)
    if not text:
        return []

    landing = "https://www.ioer-monitor.de/indikatoren/"
    records: List[Dict[str, Any]] = []
    category = ""
    category_letter = ""
    for line in text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^([A-ZÄÖÜ][A-Za-zÄÖÜäöüß/ -]{3,40})\s*\(([A-Z])\)$", stripped)
        if heading:
            category, category_letter = heading.group(1).strip(), heading.group(2)
            continue
        found = re.match(r"^([A-Z][0-9]{2}[A-Z]{2})\s+(.+)$", stripped)
        if not found:
            continue
        code, name = found.group(1), " ".join(found.group(2).split())
        if len(name) < 5:
            continue
        records.append(
            make_record(
                source_key="ioer_monitor",
                source_label="IÖR-Monitor (Leibniz-Institut für ökologische Raumentwicklung)",
                item_type="regional_indicator",
                item_id=f"ioer:{code}",
                variable_name=code,
                label=f"{name} (IÖR-Monitor)",
                dataset_label=f"IÖR-Monitor: {category}" if category else "IÖR-Monitor",
                theme="Flächennutzung & Umwelt",
                description=join_nonempty([
                    name + ".",
                    IOER_CATEGORIES.get(category_letter, ""),
                    "Verfügbar von der Rasterebene (bis 100 m) bis zu Gemeinden, Kreisen und "
                    "Ländern, als Karte, Tabelle und über WMS, WFS und WCS. Der IÖR-Monitor "
                    "berechnet seine Indikatoren aus Geobasisdaten (ATKIS, LBM-DE) und ist damit "
                    "unabhängig von der amtlichen Flächenerhebung nach Nutzungsart.",
                ]),
                spatial_levels=["Rasterzellen", "Gemeinden", "Kreise", "Bundesländer"],
                nuts_levels=["Rasterzellen", "Gemeinden", "LAU", "Kreise", "NUTS3",
                             "Bundesländer", "NUTS1"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url=landing,
                link_level="dataset",
                access_modes=source["access_modes"] or ["interactive map viewer", "machine-readable API"],
                update_frequency=source["update_frequency"] or "jährlich",
                api_hint=f"Indikatorkürzel {code}. Die Geodienste werden je Indikator über "
                         f"monitor.ioer.de/monitor_api/user?id={code}&service=wms|wfs|wcs&key=<Schlüssel> "
                         "abgerufen; der Schlüssel stammt aus dem kostenlosen Nutzerbereich des "
                         "IÖR-Monitors. Nutzungsbedingungen: Namensnennung IÖR.",
            )
        )
    return records


# ---------------------------------------------------------------------------
# FDZ Ruhr (RWI-GEO-GRID, RWI-GEO-RED and the rest of the catalogue)
# ---------------------------------------------------------------------------
def flatten_fdz_ruhr(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One record per FDZ Ruhr dataset, from the harvested da|ra metadata.

    These are scientific-use files on application rather than downloads, which is exactly why
    they belong in a finder: the point is to learn that the dataset exists and what it covers
    before starting an application.
    """
    path = source["folder"] / "raw" / "fdz_datasets.json"
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))

    # The FDZ catalogue also holds evaluation studies from Burkina Faso, Senegal, Rwanda and
    # India. They are real datasets but not German georeferenced data, so they are out of this
    # finder's scope and would only add noise to a concept search.
    OUT_OF_SCOPE = re.compile(
        r"burkina|senegal|rwanda|uganda|kenya|ghana|tanzania|mozambique|zambia|ethiopia|"
        r"india|bangladesh|nepal|indonesia|peru|bolivia|brazil|afrika|africa", re.I)

    records: List[Dict[str, Any]] = []
    skipped = 0
    for entry in document.get("datasets") or []:
        name = entry.get("name") or entry.get("title") or ""
        if not name:
            continue
        if OUT_OF_SCOPE.search(f"{name} {entry.get('title','')} {entry.get('keywords','')} "
                               f"{entry.get('description','')[:400]}"):
            skipped += 1
            continue
        description = re.sub(r"^Beschreibung\s*:\s*", "", entry.get("description") or "").strip()
        german = bool(re.search(r"[äöüß]|\b(der|die|das|und|für|Daten)\b", description))
        keywords = entry.get("keywords") or ""
        doi = entry.get("doi") or ""
        # Grid and geocoded datasets are the georeferenced ones; the rest stay indexed but are
        # labelled by what they actually are.
        georeferenced = bool(re.search(r"grid|geo|immo|raster|1\s?km|koordinat", f"{name} {keywords} {description}", re.I))
        records.append(
            make_record(
                source_key="fdz_ruhr",
                source_label="FDZ Ruhr am RWI (RWI-GEO-GRID, RWI-GEO-RED)",
                item_type="dataset",
                item_id="fdz:" + re.sub(r"[^a-z0-9]+", "_", (doi or name).lower()).strip("_")[:60],
                variable_name=name,
                label=f"{name} (FDZ Ruhr)",
                dataset_label="FDZ Ruhr Scientific-Use-Files",
                theme="Regionalforschung & Immobilienmarkt",
                description=join_nonempty([
                    description[:900] if german else "",
                    f"Schlagworte: {keywords[:300]}" if keywords else "",
                    f"DOI {doi}." if doi else "",
                    "Scientific-Use-File des Forschungsdatenzentrums Ruhr, Zugang auf Antrag "
                    "(Datenweitergabevertrag), für wissenschaftliche Zwecke kostenfrei."
                    + (" Georeferenziert (1-km-Raster bzw. geocodierte Adressen)." if georeferenced else ""),
                ]),
                spatial_levels=(["Rasterzellen", "PLZ", "Gemeinden", "Kreise"] if georeferenced
                                else ["Kreise", "Bundesländer"]),
                nuts_levels=(["Rasterzellen", "PLZ", "Gemeinden", "LAU", "Kreise", "NUTS3"]
                             if georeferenced else ["Kreise", "NUTS3", "Bundesländer", "NUTS1"]),
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=entry.get("period") or f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=entry.get("url") or source["url"],
                indicator_url=entry.get("url") or source["url"],
                link_level="dataset",
                access_modes=["on request / registration needed"],
                update_frequency=source["update_frequency"] or "jährlich",
                api_hint=(f"Metadaten und Antragsweg: {entry.get('url')}. "
                          + (f"Zitation über DOI {doi}." if doi else "")),
            )
        )
    if skipped:
        print(f"[note] fdz ruhr: skipped {skipped} non-German dataset(s) as out of scope")
    return records


FLATTENERS: Dict[str, Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = {
    "openstreetmap-poi-layer-overpass": flatten_osm_poi,
    "wegweiser-kommune-bertelsmann-stiftung": flatten_wegweiser,
    "dwd-climate-data-center-cdc": flatten_dwd,
    "boris-d-bodenrichtwerte": flatten_boris,
    "wahlergebnisse-bundeswahlleiterin": flatten_wahlergebnisse,
    "ioer-monitor-flaechennutzung": flatten_ioer,
    "rwi-geo-grid-rwi-geo-red-fdz-ruhr": flatten_fdz_ruhr,
    "regionalatlas-deutschland": flatten_regionalatlas,
    "datenguide-abgeschaltet": lambda source: (flatten_datenguide_genesis(source)
                                               + flatten_genesis_tables(source, ["regionalstatistik"])),
    "genesis-online-bund": lambda source: flatten_genesis_tables(source, ["destatis"]),
    "zensus-2022": lambda source: flatten_genesis_tables(source, ["zensus"]),
    "strukturdaten-bundestagswahl-2021": flatten_btw21,
    "migration-integration-in-regionen": flatten_migration_regionen,
    "hochschulkompass": flatten_hochschulkompass,
    "laendermonitor-fruehkindliche-bildungssysteme": flatten_laendermonitor,
    "strukturdaten-und-indikatoren-ba": flatten_ba_strukturdaten,
    "deutschlandatlas-erreichbarkeit-von-apotheken": flatten_deutschlandatlas,
    "krankenhausverzeichnis": flatten_gba_qualitaetsbericht,
    "bundes-klinik-atlas": flatten_bundes_klinik_atlas,
    "open-data-oepnv": lambda source: flatten_opendata_oepnv(source) + flatten_transit_formats(source),
    "german-companies": flatten_german_companies,
    "unfallatlas": flatten_unfallatlas,
    "deutsche-bahn-infrastrukturregister": flatten_db_isr,
    "deutsche-bahn-bahnhofsuche": flatten_db_stada,
    "arbeitsmarktstatistik-ba-karte": flatten_ba_glossary,
    "open-data-handelsregister": flatten_offeneregister,
    "destatis-regionale-mobilitaet-und-infektionsgesc": flatten_destatis_mobility,
    "breitband-monitor": lambda source: flatten_breitband(source) + flatten_breitband_raster(source),
    "arbeitsmarktreport-ba": flatten_ba_arbeitsmarktreport,
    "arbeitsmarkt-kommunal-ba": flatten_ba_arbeitsmarkt_kommunal,
}

# Portals that INKAR already covers or that must not produce a portal-level record.
NO_PORTAL_RECORD = {"inkar"}


# Portals whose workbook URL is not the one a researcher should be sent to.
PORTAL_URL_OVERRIDES = {
    # InfraGO support (ticket IIBV31-13354, 2026-08-25): the Infrastrukturregister is readable
    # without any registration through the DB MapCloud viewer. The Infraportal registration the
    # workbook points at is only needed for the operational applications.
    "deutsche-bahn-infrastrukturregister": "https://geoviewer.deutschebahn.com/maps/#/context/ISR/275618",
}


def portal_record(source: Dict[str, Any]) -> Dict[str, Any]:
    """One record per portal, so a concept query still routes to a search UI that has no
    machine-readable catalogue."""
    mapped = map_spatial(source["spatial_levels"])
    topics = [t["topic"] for t in source["topics"]]
    groups = source["topic_groups"]
    note = source["note"]
    discontinued = bool(re.search(r"eingestellt|nicht mehr aktualisiert|abgeschaltet", f"{note} {source['name']}", re.I))
    years = ""
    if source["coverage_start_year"] or source["coverage_end_year"]:
        years = f"{source['coverage_start_year'] or '?'}-{source['coverage_end_year'] or '?'}"

    description = (
        f"Datenportal {source['name']}. Themen: {', '.join(groups) if groups else 'siehe Portal'}. "
        f"Enthaltene Merkmale: {', '.join(topics[:25]) if topics else 'nicht katalogisiert'}. "
        f"Zugang: {', '.join(source['access_modes']) or 'siehe Portal'}. "
        + (f"Hinweis: {note}. " if note else "")
        + ("Dieses Angebot wird nicht mehr aktualisiert, die historischen Daten bleiben zitierbar. " if discontinued else "")
        + "Der Finder verweist auf das Portal; die Daten selbst liegen dort."
    )
    return make_record(
        source_key="geoportal",
        source_label=source["name"],
        item_type="portal",
        item_id=f"portal:{source['slug']}",
        variable_name=source["slug"],
        label=f"{source['name']} (Datenportal)",
        dataset_label="Datenportale",
        theme=groups[0] if groups else "Datenportal",
        description=description,
        aliases=", ".join(topics[:40]),
        spatial_levels=mapped["spatial_levels"],
        nuts_levels=mapped["nuts_levels"],
        year_start=source["coverage_start_year"],
        year_end=source["coverage_end_year"],
        years_text=years,
        source_url=PORTAL_URL_OVERRIDES.get(source["slug"], source["url"]),
        indicator_url=PORTAL_URL_OVERRIDES.get(source["slug"], source["url"]),
        access_modes=source["access_modes"],
        update_frequency=source["update_frequency"],
        status="discontinued" if discontinued else "active",
        link_level="portal",
    )


# ---------------------------------------------------------------------------
# Facet hygiene
# ---------------------------------------------------------------------------
# Destatis writes the same statistic title two ways depending on the instance ("Statistik d.
# Empfänger v. Hilfe z. Lebensunterhalt" in the regional database, spelled out in the federal
# one), so the theme facet showed both. Expanding the abbreviations is what makes the two
# spellings comparable at all.
GERMAN_ABBREVIATIONS: Dict[str, str] = {
    "d.": "der", "des.": "des", "v.": "von", "z.": "zum", "u.": "und", "f.": "für",
    "b.": "bei", "i.": "im", "a.": "an", "m.": "mit", "n.": "nach", "je.": "je",
    "jährl.": "jährliche", "monatl.": "monatliche", "vierteljährl.": "vierteljährliche",
    "öffentl.": "öffentliche", "öffentlich-rechtl.": "öffentlich-rechtlichen",
    "sozialversicherungspfl.": "sozialversicherungspflichtig", "allg.": "allgemeine",
    "einschl.": "einschließlich", "insg.": "insgesamt", "erwerbst.": "erwerbstätige",
    "beschäft.": "beschäftigte", "bev.": "bevölkerung", "krh.": "krankenhaus",
    "verw.": "verwaltung", "wirtsch.": "wirtschaftliche", "landw.": "landwirtschaftliche",
    "gesetzl.": "gesetzliche", "priv.": "private", "stat.": "statistik",
}


def _facet_tokens(value: str) -> List[str]:
    """Comparable token list: abbreviations expanded, separators unified, case folded."""
    # "u.bei" -> "u. bei", but a filename stays one token: splitting "calendar.txt" would make
    # it look like a truncation of "calendar_dates.txt" and merge two different GTFS files.
    text = re.sub(r"(?<![\w-])(?![\w-]+\.(?:txt|csv|xlsx?|json|pdf|html?|xml|zip|gpkg|shp)\b)"
                  r"([a-zäöüß]{1,20}\.)(?=[A-Za-zÄÖÜäöü])", r"\1 ", value or "")
    text = text.replace("&", "/").replace("–", "-")
    tokens: List[str] = []
    for token in re.split(r"[\s/,;]+", text.strip()):
        if not token:
            continue
        expanded = GERMAN_ABBREVIATIONS.get(token.casefold())
        # The trailing dot is kept: it marks a truncation ("Rehabilitationseinr.") that has to
        # match the spelled-out word, which no edit-distance threshold would catch.
        cleaned = (expanded or token).casefold().strip(",;:()")
        tokens.append(cleaned if cleaned != "." else "")
    return [t for t in tokens if t]


def _edit_distance(left: str, right: str, limit: int = 3) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        current = [i]
        for j, b in enumerate(right, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                              previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _same_facet(left: str, right: str) -> bool:
    """True when two facet labels are spelling variants of one thing.

    Deliberately conservative: same number of words, and every word pair agrees on its first
    four characters and is within two edits. That merges "Gebietsstandes"/"Gebietsstands" and
    "Einbürgerungsstatistik"/"Einbürgerungsstatistiken" while keeping
    "Krankenversicherung"/"Rentenversicherung" and "Bevölkerungsstand"/"Bevölkerungsstatistik"
    apart, which a similarity ratio alone does not.
    """
    FILLER = {"der", "die", "das", "des", "den", "dem", "von", "vom", "für", "im", "in", "und"}

    def token_match(x: str, y: str) -> bool:
        if x == y:
            return True
        if x.endswith(".") and y.startswith(x[:-1]):        # "rehabilitationseinr." vs full word
            return True
        if y.endswith(".") and x.startswith(y[:-1]):
            return True
        x, y = x.rstrip("."), y.rstrip(".")
        return x[:4] == y[:4] and _edit_distance(x, y) <= 2

    def compare(a: List[str], b: List[str]) -> bool:
        return bool(a) and len(a) == len(b) and all(token_match(x, y) for x, y in zip(a, b))

    a, b = _facet_tokens(left), _facet_tokens(right)
    if compare(a, b):
        return True
    # Second pass without articles and prepositions: "Fortschreibung des Wohnungsbestandes" and
    # "Fortschreibung Wohnungsbestand" are one statistic written two ways.
    return compare([t for t in a if t not in FILLER], [t for t in b if t not in FILLER])


def unify_facet_values(records: List[Dict[str, Any]], fields: Iterable[str]) -> Dict[str, int]:
    """Collapse spelling variants inside each facet field, keeping the commonest spelling.

    Filters are the user's handle on the corpus, so a facet that lists one thing twice is a
    defect in the data, not something to paper over in the UI.
    """
    merged: Dict[str, int] = {}
    for field in fields:
        counts: Dict[str, int] = {}
        for record in records:
            value = record.get(field)
            if value:
                counts[value] = counts.get(value, 0) + 1
        # Spelled-out first, then commonest: a facet label is read by a person, so
        # "Statistik der Empfänger von Hilfe zum Lebensunterhalt" wins over the abbreviated
        # variant even when Destatis uses the abbreviation more often.
        def rank(value: str) -> Tuple[int, int, int, str]:
            abbreviations = len(re.findall(r"\b[A-Za-zÄÖÜäöüß]{1,20}\.", value))
            return (abbreviations, -counts[value], -len(value), value)

        ordered = sorted(counts, key=rank)
        canonical: Dict[str, str] = {}
        for value in ordered:
            for kept in canonical.values():
                if kept != value and _same_facet(kept, value):
                    canonical[value] = kept
                    break
            else:
                canonical[value] = value
        renames = {k: v for k, v in canonical.items() if k != v}
        if renames:
            merged[field] = len(renames)
            for record in records:
                value = record.get(field)
                if value in renames:
                    record[field] = renames[value]
            print(f"[facet] {field}: merged {len(renames)} spelling variant(s)")
            for old, new in sorted(renames.items())[:8]:
                print(f"          {old!r} -> {new!r}")
        # A portal card is built from the workbook row name while the flattener writes the
        # source's own name, which put both spellings in the source dropdown. The card follows
        # the records.
    return merged


def align_portal_labels(produced: List[Dict[str, Any]]) -> int:
    """Give one source's portal card the source_label that source's own records use.

    The card is built from the workbook row name ("Wahlergebnisse Bundeswahlleiterin") while the
    flattener writes the source's own name ("Wahlergebnisse der Bundeswahlleiterin"), so the
    source dropdown listed the same portal twice. Only spelling variants are aligned; a card for
    a genuinely differently-named portal keeps its name.
    """
    counts: Dict[str, int] = {}
    for record in produced:
        if record.get("source_key") == "geoportal":
            continue
        label = record.get("source_label") or ""
        if label:
            counts[label] = counts.get(label, 0) + 1
    if not counts:
        return 0
    best = max(counts, key=lambda label: counts[label])
    changed = 0

    def same_portal(left: str, right: str) -> bool:
        # A card and its records may differ by an article or a parenthetical suffix
        # ("Hochschulkompass" vs "Hochschulkompass (HRK)"), which is still one portal.
        filler = {"der", "die", "das", "des", "den", "dem", "von", "vom", "für", "im", "in"}
        def core(value: str) -> List[str]:
            without = re.sub(r"\([^)]*\)", " ", value or "")
            return [t for t in _facet_tokens(without) if t not in filler]
        left_core, right_core = core(left), core(right)
        return bool(left_core) and (left_core == right_core or _same_facet(" ".join(left_core), " ".join(right_core)))

    for record in produced:
        if record.get("source_key") != "geoportal":
            continue
        current = record.get("source_label") or ""
        if best != current and same_portal(best, current):
            record["source_label"] = best
            changed += 1
    return changed


# Cases the facet matcher must get right. Kept next to the code because both mistakes are
# silent: a missed merge shows the same statistic twice in the dropdown, and a false merge hides
# a real dataset behind another one's name.
FACET_MATCH_CASES: List[Tuple[str, str, bool]] = [
    ("Statistik d. Empfänger v. Hilfe z. Lebensunterhalt",
     "Statistik der Empfänger von Hilfe zum Lebensunterhalt", True),
    ("Grunddaten der Vorsorge- oder Rehabilitationseinr.",
     "Grunddaten der Vorsorge- oder Rehabilitationseinrichtungen", True),
    ("Fortschreibung Wohngebäude- und Wohnungsbestand",
     "Fortschreibung des Wohngebäude- und Wohnungsbestandes", True),
    ("Einbürgerungsstatistik", "Einbürgerungsstatistiken", True),
    ("Bauen / Wohnen", "Bauen & Wohnen", True),
    ("GTFS calendar.txt", "GTFS calendar_dates.txt", False),
    ("Statistik der gesetzlichen Krankenversicherung",
     "Statistik der gesetzlichen Rentenversicherung", False),
    ("Eckwerte SGB II", "Eckwerte SGB III", False),
    ("Strukturdaten Bundestagswahl 2021", "Strukturdaten Bundestagswahl 2025", False),
    ("Sozialversicherungspflichtig Beschäftigte am Arbeitsort (Stichtag 30.06.)",
     "Sozialversicherungspflichtig Beschäftigte am Wohnort (Stichtag 30.06.)", False),
    ("Erhebung der öffentlichen Abwasserentsorgung",
     "Erhebung der öffentlichen Wasserversorgung", False),
    ("Bevölkerungsstand", "Bevölkerungsstatistik", False),
]


def self_test() -> None:
    failures = []
    for left, right, expected in FACET_MATCH_CASES:
        if _same_facet(left, right) != expected:
            failures.append(f"{left!r} ~ {right!r}: expected {expected}")
    if failures:
        raise SystemExit("facet matcher self-test failed:\n  " + "\n  ".join(failures))
    print(f"facet matcher self-test: {len(FACET_MATCH_CASES)} case(s) ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=[], help="slug(s) to flatten")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true",
                        help="check the facet matcher against its known cases and exit")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    sources = registry_sources()
    slugs = args.only or list(sources)

    records: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    aligned_cards = 0
    for slug in slugs:
        source = sources[slug]
        flattener = FLATTENERS.get(slug)
        produced: List[Dict[str, Any]] = []
        if flattener:
            try:
                produced = flattener(source)
            except Exception as exc:  # keep one broken source from sinking the build
                print(f"[FAIL] {slug}: {type(exc).__name__}: {exc}")
                produced = []
        if not produced and slug not in NO_PORTAL_RECORD:
            produced = [portal_record(source)]
        elif produced and slug not in NO_PORTAL_RECORD and flattener:
            produced.append(portal_record(source))
        aligned_cards += align_portal_labels(produced)
        counts[slug] = len(produced)
        records.extend(produced)

    unify_facet_values(records, ("theme", "dataset_label", "source_label"))
    if aligned_cards:
        print(f"[facet] aligned {aligned_cards} portal card label(s) with their source's records")

    missing_link = [r["item_id"] for r in records if not (r["source_url"] or r["indicator_url"])]
    if missing_link:
        raise SystemExit(f"{len(missing_link)} records have no outward link: {missing_link[:5]}")

    print(json.dumps({"records": len(records), "per_source": counts}, ensure_ascii=False, indent=2))
    if args.dry_run:
        return

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output} ({output.stat().st_size / 1e6:.1f} MB)")

    # A user cannot tell a stale index from a fresh one, so the build stamps itself and the UI
    # shows the date. Written next to the metadata so it travels with it on deploy.
    if not args.only:
        info = output.parent / "geodb_build_info.json"
        info.write_text(json.dumps({
            "built": date.today().isoformat(),
            "records": len(records),
            "sources": len({record["source_key"] for record in records}),
            "per_source": counts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {info}")


if __name__ == "__main__":
    main()
