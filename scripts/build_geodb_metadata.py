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
from typing import Any, Callable, Dict, Iterable, List, Optional

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
             "portal": "Der Link öffnet das Portal; dort muss weitergesucht werden."}.get(link_level, ""),
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

    records: List[Dict[str, Any]] = []
    for code, payload in sorted(german.items()):
        name = clean(payload.get("name"))
        if not name:
            continue
        description = clean(payload.get("description"))
        # The Destatis definition text repeats the term and a copyright line; keep the
        # substance, drop the trailing copyright.
        description = re.sub(r"©\s*Statistisches Bundesamt[^\n]*", "", description).strip()
        english_name = clean(english.get(code, {}).get("name"))

        # The Regionalstatistik portal is a JSF app: query parameters like
        # ?operation=merkmal&code=... are ignored and land on the homepage. The one
        # pattern that really deep-links is /genesis/online/statistic/<5-digit code>,
        # and the Destatis definition text names the statistics that use the key
        # ("Erläuterung für folgende Statistik(en): 12612 Statistik der Geburten").
        statistics = re.findall(r"(\d{5})\s+([^\n]{4,80})", description.split("Statistik(en):", 1)[1]) \
            if "Statistik(en):" in description else []
        statistic_code = statistics[0][0] if statistics else ""
        statistic_names = "; ".join(f"{c} {n.strip()}" for c, n in statistics[:4])
        url = (
            f"https://www.regionalstatistik.de/genesis/online/statistic/{statistic_code}"
            if statistic_code
            else "https://www.regionalstatistik.de/genesis/online"
        )
        records.append(
            make_record(
                source_key="regionalstatistik",
                source_label="Regionalstatistik / GENESIS (Merkmalskatalog, via Datenguide)",
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
                link_level="statistic" if statistic_code else "portal",
                access_modes=["machine-readable API", "web UI / search form only"],
                update_frequency=source["update_frequency"],
                api_hint=(
                    f"GENESIS-Merkmal {code}"
                    + (f"; erhoben in Statistik {statistic_names}." if statistic_names else ".")
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

def flatten_genesis_tables(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Table-level records for the Regionaldatenbank (regionalstatistik.de), enumerated
    over the GENESIS REST API by `scripts/fetch_genesis_catalogue.py`.

    This is the finest linkable unit the portal offers: `?operation=table&code=<code>`
    opens exactly that table, and the regional depth is spelled out in the table title
    ("... regionale Tiefe: Kreise und krfr. Städte")."""
    path = source["folder"] / "raw" / "genesis_catalogue_regionalstatistik.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    tables = payload.get("tables") or []

    depth_map = [
        ("gemeinde", "Gemeinden und Verbandsgemeinden"),
        ("kreis", "Kreise & kreisfreie Städte"),
        ("krfr", "Kreise & kreisfreie Städte"),
        ("regierungsbezirk", "Regierungsbezirke"),
        ("bundesl", "Bundesland"),
        ("länder", "Bundesland"),
        ("laender", "Bundesland"),
    ]

    records: List[Dict[str, Any]] = []
    for table in tables:
        code = clean(table.get("Code"))
        # Catalogue titles carry hard line breaks ("... Stichtag 31.12. -\nregionale Tiefe: ...").
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
        levels = sorted({level for needle, level in depth_map if needle in lowered})
        mapped = map_spatial(levels or ["Kreise & kreisfreie Städte"])

        period = clean(table.get("Time")) or clean(table.get("Zeitraum"))
        years = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", f"{period} {title}")]
        records.append(
            make_record(
                source_key="regionalstatistik",
                source_label="Regionalstatistik / GENESIS (Merkmalskatalog, via Datenguide)",
                item_type="table",
                item_id=f"genesis_table:{code}",
                variable_name=code,
                label=title,
                dataset_label="GENESIS-Tabelle",
                theme=statistic_name or "Regionalstatistik",
                description=join_nonempty([
                    title,
                    f"Tabelle der Statistik {statistic_code} {statistic_name}." if statistic_name else "",
                    f"Regionale Tiefe: {depth_text}." if depth_text else "",
                    f"Zeitraum: {period}." if period else "",
                    "Abrufbar in der Regionaldatenbank Deutschland; Download als CSV/XLSX nach kostenfreier "
                    "Anmeldung oder über die GENESIS-Webservice-API.",
                ]),
                stats_summary=f"{statistic_code} {statistic_name}".strip(),
                spatial_levels=mapped["spatial_levels"],
                nuts_levels=mapped["nuts_levels"],
                year_start=min(years) if years else None,
                year_end=max(years) if years else None,
                years_text=period,
                source_url="https://www.regionalstatistik.de/genesis/online",
                indicator_url=f"https://www.regionalstatistik.de/genesis/online?operation=table&code={code}",
                link_level="table",
                access_modes=["machine-readable API", "web UI / search form only", "direct file download"],
                update_frequency=source["update_frequency"],
                api_hint=(
                    f"GENESIS-Tabelle {code} (Statistik {statistic_code}). Über die Regionalstatistik-"
                    "Webservice-API: POST /genesisws/rest/2020/data/tablefile mit dem Token im HTTP-Header "
                    "`username` (nicht als Parameter, sonst Gastzugang)."
                ),
            )
        )
    return records

FLATTENERS: Dict[str, Callable[[Dict[str, Any]], List[Dict[str, Any]]]] = {
    "regionalatlas-deutschland": flatten_regionalatlas,
    "datenguide-abgeschaltet": lambda source: flatten_datenguide_genesis(source) + flatten_genesis_tables(source),
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
}

# Portals that INKAR already covers or that must not produce a portal-level record.
NO_PORTAL_RECORD = {"inkar"}


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
        source_url=source["url"],
        indicator_url=source["url"],
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
