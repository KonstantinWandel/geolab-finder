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
        if held_by == "regional":
            url = f"https://www.regionalstatistik.de/genesis/online/statistic/{statistic_code}"
            link_ok, level = True, "statistic"
        elif held_by == "federal":
            # Same federal portal as the GENESIS table links, confirmed by hand on 2026-08-25.
            url = f"https://www-genesis.destatis.de/datenbank/online/statistic/{statistic_code}"
            link_ok, level = True, "statistic"
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
    raw = source["folder"] / "raw"
    csv_path = raw / "btw21_strukturdaten.csv"
    text = csv_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    header: List[str] = []
    for line in lines:
        fields = [clean(f) for f in line.split(";")]
        if fields and fields[0].startswith("Spalten-Nr"):
            continue
        if fields and fields[0] == "Land":
            header = fields
            break
    if not header:
        raise RuntimeError("Could not find the header row in btw21_strukturdaten.csv")

    # Descriptions: <h3> indicator heading followed by explanatory text.
    descriptions: Dict[str, str] = {}
    page = (raw / "beschreibung.html").read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"<h3[^>]*>", page)[1:]
    for block in blocks:
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
    for position, column in enumerate(header[3:], start=1):  # skip Land, WK-Nr, WK-Name
        if not column:
            continue
        records.append(
            make_record(
                source_key="btw21_strukturdaten",
                link_level="dataset",
                source_label="Strukturdaten für die Wahlkreise (Bundestagswahl 2021)",
                item_type="regional_indicator",
                item_id=f"btw21:{position:02d}",
                variable_name=f"BTW21-{position:02d}",
                label=column,
                dataset_label="Strukturdaten Bundestagswahl 2021",
                theme="Politik / Wahlkreisstruktur",
                description=describe(column),
                spatial_levels=["Bundestagswahlkreise", "Bundesländer"],
                nuts_levels=["Bundestagswahlkreise", "Bundesländer", "NUTS1"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url="https://www.bundeswahlleiter.de/bundestagswahlen/2021/strukturdaten/beschreibung.html",
                access_modes=source["access_modes"],
                update_frequency=source["update_frequency"],
                api_hint="Spalte in btw21_strukturdaten.csv (Wahlkreisebene, Bundeswahlleiter).",
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
    path = source["folder"] / "raw" / "uebersicht-aller-indikatoren.html"
    page = path.read_text(encoding="utf-8", errors="replace")
    headings = [strip_tags(match) for match in re.findall(r"<h2[^>]*>(.*?)</h2>", page, re.S)]
    indicators = [h for h in headings if "|" in h]

    records: List[Dict[str, Any]] = []
    for heading in dict.fromkeys(indicators):
        parts = [clean(part) for part in heading.split("|")]
        records.append(
            make_record(
                source_key="laendermonitor",
                link_level="dataset",
                source_label="Ländermonitor Frühkindliche Bildungssysteme (Bertelsmann Stiftung)",
                item_type="regional_indicator",
                item_id=f"laendermonitor:{'-'.join(parts).lower()}",
                variable_name=parts[-1],
                label=heading,
                dataset_label=parts[0],
                theme="Kinder und Jugend / Frühkindliche Bildung",
                description=(
                    f"Indikator des Ländermonitors zu {parts[0]}: {' / '.join(parts[1:])}. "
                    "Vergleich der Bundesländer und regionaler Einheiten zur Kindertagesbetreuung."
                ),
                spatial_levels=["Bundesländer", "Kreise"],
                nuts_levels=["Bundesländer", "NUTS1", "Kreise", "NUTS3"],
                year_start=source["coverage_start_year"],
                year_end=source["coverage_end_year"],
                years_text=f"{source['coverage_start_year']}-{source['coverage_end_year']}",
                source_url=source["url"],
                indicator_url=source["url"],
                access_modes=source["access_modes"],
                update_frequency=source["update_frequency"],
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


def flatten_deutschlandatlas(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The Deutschlandatlas ships both halves of a catalogue: the PDF documents every
    indicator (`<name> | Indikatorenkürzel: <code>`, definition, Gebietsstand, Datenbasis,
    methodischer Hinweis) and the XLSX shows which spatial level and reference date each
    indicator is actually published for."""
    raw = source["folder"] / "raw"
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
        records.append(
            make_record(
                source_key="deutschlandatlas",
                link_level="dataset",
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
                indicator_url="https://www.deutschlandatlas.bund.de/DE/Karten/karten_node.html",
                # deutschlandatlas.bund.de answers 400 to every scripted request, so its links
                # are documented but unverifiable from here.
                link_verified=False,
                access_modes=source["access_modes"] or ["direct file download", "interactive map viewer"],
                update_frequency=source["update_frequency"],
                api_hint=(
                    (f"Gebietsstand: {info['gebietsstand']}. " if info.get("gebietsstand") else "")
                    + f"Indikatorenkürzel {code}. Spalte in 'Deutschlandatlas-Daten.xlsx' bzw. den CSV-Dateien "
                    "je Gebietsstand (Gemeinde-, Gemeindeverbands- und Kreisebene); fehlende Werte = -9999."
                ),
            )
        )
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
        for child in root:
            tag = re.sub(r"\{.*?\}", "", child.tag)
            sections[tag] = sections.get(tag, 0) + len(list(child.iter()))

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

    for instance in (instances or list(GENESIS_INSTANCES)):
        config = GENESIS_INSTANCES[instance]
        path = raw / f"genesis_catalogue_{instance}.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
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
            mapped = map_spatial(levels or config["default_levels"])

            period = clean(table.get("Time")) or clean(table.get("Zeitraum"))
            years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", f"{period} {title}")]
            records.append(
                make_record(
                    source_key=config["source_key"],
                    source_label=config["source_label"],
                    item_type="table",
                    item_id=f"{instance}_table:{code}",
                    variable_name=code,
                    label=title,
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
                    dataset_label=sheet,
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


FLATTENERS: Dict[str, Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = {
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
    "open-data-oepnv": flatten_opendata_oepnv,
    "german-companies": flatten_german_companies,
    "unfallatlas": flatten_unfallatlas,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=[], help="slug(s) to flatten")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    sources = registry_sources()
    slugs = args.only or list(sources)

    records: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
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
        counts[slug] = len(produced)
        records.extend(produced)

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


if __name__ == "__main__":
    main()
