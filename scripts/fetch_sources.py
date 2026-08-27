#!/usr/bin/env python3
"""Fetch the publicly downloadable indicator catalogues for the GeoDB source list.

One entry per artifact in FETCH_PLAN, keyed by the source slug from
`data_sources/registry/geo_sources.json`. Files land in
`data_sources/<NN>-<slug>/raw/` next to a `FETCH_LOG.json` recording url, HTTP status,
byte count, sha256 and fetch time, so every downstream record traces to a retrieval.

Sources that cannot be fetched from a script (registration, API key, request form,
JS-only UI, or a server that refuses non-browser clients) are listed in MANUAL with the
reason, and are reported by `--report` rather than silently skipped.

Run:
  python scripts/fetch_sources.py                 # fetch everything still missing
  python scripts/fetch_sources.py --only regionalatlas-deutschland --force
  python scripts/fetch_sources.py --report        # what is here, what is missing, why
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_SOURCES = REPO_ROOT / "data_sources"
REGISTRY = DATA_SOURCES / "registry" / "geo_sources.json"

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
TIMEOUT = 90

# kind: what the artifact is for the indexer.
#   catalogue  = an actual list of indicators/variables (the good case)
#   thesaurus  = synonyms / alternative wording per indicator
#   sample     = one representative data file whose header row names the indicators
#   portal     = a saved portal page, used for a portal-level record only
#   registry   = an entity register (rows are places/institutions, not indicators)
FETCH_PLAN: Dict[str, List[Dict[str, str]]] = {
    "regionalatlas-deutschland": [
        {
            "name": "services.json",
            "url": "https://regionalatlas.statistikportal.de/app/json/services.json",
            "kind": "catalogue",
            "note": "Theme tree: TCode/ICode, short+long indicator titles, years, geometry levels.",
        },
        {
            "name": "services_taskrunner.json",
            "url": "https://regionalatlas.statistikportal.de/taskrunner/services.json",
            "kind": "catalogue",
            "note": "Second, larger services.json served by the taskrunner path; compare before use.",
        },
        {
            "name": "thesaurus.csv",
            "url": "https://regionalatlas.statistikportal.de/app/csv/thesaurus.csv",
            "kind": "thesaurus",
            "note": "ID;type(OK/MK/EK);code;short title;long title;synonyms;theme code;theme title. Latin-1.",
        },
    ],
    "breitband-monitor": [
        {
            "name": "portal.html",
            "url": "http://www.breitband-monitor.de/",
            "kind": "portal",
            "note": "HTTPS fails (expired/broken chain per the workbook); plain HTTP serves the page.",
        },
    ],
    "breitbandatlas": [
        {
            "name": "gigabitgrundbuch.html",
            "url": "https://gigabitgrundbuch.bund.de/",
            "kind": "portal",
            "note": "The bmvi.de Breitbandatlas link in the workbook is dead; this is the successor portal.",
        },
    ],
    "arbeitsmarktstatistik-ba-karte": [
        {
            "name": "portal.html",
            "url": "https://statistik.arbeitsagentur.de/DE/Navigation/Statistiken/Statistiken-nach-Regionen/Politische-Gebietsstruktur-Nav.html",
            "kind": "portal",
            "note": "",
        },
        {
            "name": "ba_glossar.html",
            "url": "https://statistik.arbeitsagentur.de/DE/Navigation/Grundlagen/Definitionen/Glossar/Glossar-Nav.html",
            "kind": "catalogue",
            "note": "BA glossary: definitions of the labour-market concepts behind every BA indicator.",
        },
        {
            "name": "ba_gesamtglossar.pdf",
            "url": "https://statistik.arbeitsagentur.de/DE/Statischer-Content/Grundlagen/Definitionen/"
                   "Glossare/Generische-Publikationen/Gesamtglossar.pdf?__blob=publicationFile&v=53",
            "kind": "catalogue",
            "note": "The BA's own glossary: the authoritative definition of every labour-market "
                    "concept behind its statistics, which is what its map and its booklets measure.",
        },
        {
            "name": "ba_api.html",
            "url": "https://statistik.arbeitsagentur.de/DE/Navigation/Service/API/API-Start-Nav.html",
            "kind": "portal",
            "note": "BA's own API landing page; check whether it exposes a machine-readable catalogue.",
        },
    ],
    "strukturdaten-und-indikatoren-ba": [
        {
            "name": "heftsuche.html",
            "url": "https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html?nn=15024&topic_f=zdf-sdi&dateOfRevision=201006-202106",
            "kind": "portal",
            "note": "Search page listing the regional Strukturdaten booklets.",
        },
        {
            "name": "sdi-071-0-202106.xlsx",
            "url": "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/202106/iiia4/zdf-sdi/sdi-071-0-202106-xlsx.xlsx?__blob=publicationFile&v=1",
            "kind": "sample",
            "note": "One representative booklet; its sheets enumerate the indicator set shared by all regions.",
        },
    ],
    "arbeitsmarktreport-ba": [
        {
            "name": "heftsuche.html",
            "url": "https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html?nn=24280&topic_f=amr-amr",
            "kind": "portal",
            "note": "",
        },
        {
            "name": "amr-01-0-202607.xlsx",
            "url": "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/202607/ama/amr-amr/amr-01-0-202607-xlsx.xlsx?__blob=publicationFile&v=1",
            "kind": "sample",
            "note": "Representative Arbeitsmarktreport booklet.",
        },
    ],
    "arbeitsmarkt-kommunal-ba": [
        {
            "name": "heftsuche.html",
            "url": "https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html?nn=24280&topic_f=amk",
            "kind": "portal",
            "note": "Search page; the booklets themselves are linked per region from here.",
        },
    ],
    "migration-integration-in-regionen": [
        {
            "name": "portal.html",
            "url": "https://service.destatis.de/DE/karten/migration_integration_regionen.html",
            "kind": "portal",
            "note": "",
        },
        {
            "name": "migration_integration_regionen.zip",
            "url": "https://service.destatis.de/DE/karten/data/migration_integration_regionen.zip",
            "kind": "catalogue",
            "note": "Data bundle behind the map; contains the indicator definitions and the district values.",
        },
    ],
    "krankenhausatlas-deutschland": [
        {"name": "portal.html", "url": "https://krankenhausatlas.statistikportal.de/", "kind": "portal", "note": ""},
    ],
    "krankenhausverzeichnis": [
        {"name": "portal.html", "url": "https://www.deutsches-krankenhaus-verzeichnis.de/app/suche", "kind": "portal", "note": ""},
    ],
    "arztsuche-bundesaerztekammer": [
        {"name": "portal.html", "url": "https://www.bundesaerztekammer.de/service/arztsuche/", "kind": "portal", "note": ""},
    ],
    "hochschulkompass": [
        {"name": "portal.html", "url": "https://www.hochschulkompass.de/hochschulen/hochschulsuche.html", "kind": "portal", "note": ""},
    ],
    "deutsche-bahn-infrastrukturregister": [
        {"name": "portal.html", "url": "https://geovdbn.deutschebahn.com/isr", "kind": "portal", "note": ""},
        {
            "name": "isr_wms_capabilities.xml",
            "url": "https://geoviewer.deutschebahn.com/geoviewer-geoserver/ows"
                   "?service=WMS&version=1.3.0&request=GetCapabilities",
            "kind": "catalogue",
            "note": "The ISR viewer is a MapStore2 app over a public GeoServer. No login: 66 ISR "
                    "layers with titles and abstracts (Streckenklasse, Elektrifizierung, ETCS, "
                    "Gleisanzahl, Betriebsstellen, Tunnel, Brücken, Bahnübergänge, ...).",
        },
        {
            "name": "isr_wfs_capabilities.xml",
            "url": "https://geoviewer.deutschebahn.com/geoviewer-geoserver/ows"
                   "?service=WFS&version=2.0.0&request=GetCapabilities",
            "kind": "catalogue",
            "note": "28 ISR feature types, downloadable as GML/GeoJSON through WFS without a login.",
        },
        {
            "name": "isr_wfs_attributes.json",
            "url": "https://geoviewer.deutschebahn.com/geoviewer-geoserver/ows",
            "kind": "catalogue",
            "handler": "isr_wfs_attributes",
            "note": "DescribeFeatureType per ISR feature type, i.e. the attribute list per layer.",
        },
    ],
    "deutsche-bahn-bahnhofsuche": [
        {"name": "portal.html", "url": "https://www.bahnhof.de/bahnhof-de", "kind": "portal", "note": ""},
    ],
    "open-data-oepnv": [
        {"name": "portal.html", "url": "https://www.opendata-oepnv.de/ht/de/willkommen", "kind": "portal", "note": "Downloading a dataset needs a free account; the catalogue itself is public."},
        {
            "name": "gtfs_reference.md",
            "url": "https://raw.githubusercontent.com/google/transit/master/gtfs/spec/en/reference.md",
            "kind": "catalogue",
            "note": "The GTFS specification: every file and field of the format the nationwide and "
                    "per-Verbund timetable datasets are delivered in. Indexed so that a question "
                    "like 'which field carries step-free access' finds an answer.",
        },
        {
            "name": "netex_pi_profile.pdf",
            "url": "https://cms.opendata-oepnv.de/fileadmin/Dokumentationen_etc/DELFI/"
                   "prCEN_TS_16614-PI_Profile_FV__E_-2019_-_Final_Draft.pdf",
            "kind": "catalogue",
            "note": "The NeTEx passenger-information profile that DELFI references, public, 188 pages.",
        },
        {
            "name": "datensaetze.html",
            "url": "https://www.opendata-oepnv.de/ht/de/datensaetze",
            "kind": "catalogue",
            "note": "The public dataset catalogue: German dataset names (Deutschlandweite Sollfahrplandaten "
                    "(GTFS/NeTEX), Deutschlandweite Haltestellendaten, Soll-Fahrplandaten/Haltestellen/Liniendaten "
                    "per Verbund) with a deep link per dataset.",
        },
    ],
    "spielplatztreff-suchmaschine-fuer-spielplaetze": [
        {"name": "portal.html", "url": "https://www.spielplatztreff.de/", "kind": "portal", "note": ""},
    ],
    "spielplatzkarte": [
        {"name": "portal.html", "url": "https://spielplatznet.de/karte.htm", "kind": "portal", "note": ""},
    ],
    "destatis-regionale-mobilitaet-und-infektionsgesc": [
        {
            "name": "portal.html",
            "url": "https://www.destatis.de/DE/Service/EXSTAT/Datensaetze/mobilitaetsindikatoren-mobilfunkdaten.html",
            "kind": "portal",
            "note": "Experimental statistic, discontinued after 2022; page documents the indicators.",
        },
    ],
    "datenguide-abgeschaltet": [
        {
            "name": "datenguide-metadata.tar.gz",
            "url": "https://codeload.github.com/datenguide/metadata/tar.gz/refs/heads/master",
            "kind": "catalogue",
            "note": "The Datenguide portal is gone; its curated metadata on the Regionalstatistik "
                    "statistics/measures/attributes survives in this repo and is the real catalogue.",
        },
        {"name": "portal.html", "url": "https://datengui.de/statistiken", "kind": "portal", "note": "Now a stub page."},
        {
            "name": "genesapi-data",
            "url": "https://codeload.github.com/datenguide/genesapi-data/tar.gz/refs/heads/master",
            "kind": "catalogue",
            "handler": "genesapi_keys",
            "note": "GENESIS/Regionalstatistik 'Merkmale' dictionary: one JSON per key (de + en label) "
                    "plus the table specs. Extracted from a ~100 MB repo tarball that is then discarded; "
                    "only keys/ and src/*.yaml are kept.",
        },
    ],
    "open-data-handelsregister": [
        {"name": "portal.html", "url": "https://offeneregister.de/", "kind": "portal", "note": "Full company dump is multi-GB; not needed for metadata search."},
        {"name": "daten.html", "url": "https://offeneregister.de/daten/", "kind": "portal", "note": ""},
    ],
    "laendermonitor-fruehkindliche-bildungssysteme": [
        {
            "name": "Methodik_KiTa.pdf",
            "url": "https://www.laendermonitor.de/fileadmin/files/laendermonitor/methodiktexte/aktuell/Methodik_KiTa.pdf",
            "kind": "catalogue",
            "note": "Methodik document: the per-indicator definitions behind the overview page.",
        },
        {
            "name": "Methodik_KiTa_Personal_braucht_Prioritaet.pdf",
            "url": "https://www.laendermonitor.de/fileadmin/files/laendermonitor/methodiktexte/aktuell/Methodik_KiTa_Personal_braucht_Prioritaet.pdf",
            "kind": "catalogue",
            "note": "Methodik document: the per-indicator definitions behind the overview page.",
        },
        {
            "name": "Methodik_Kindertagespflege.pdf",
            "url": "https://www.laendermonitor.de/fileadmin/files/laendermonitor/methodiktexte/aktuell/Methodik_Kindertagespflege.pdf",
            "kind": "catalogue",
            "note": "Methodik document: the per-indicator definitions behind the overview page.",
        },
        {
            "name": "Methodik_Schulkindbetreuung.pdf",
            "url": "https://www.laendermonitor.de/fileadmin/files/laendermonitor/methodiktexte/aktuell/Methodik_Schulkindbetreuung.pdf",
            "kind": "catalogue",
            "note": "Methodik document: the per-indicator definitions behind the overview page.",
        },
        {
            "name": "uebersicht-aller-indikatoren.html",
            "url": "https://www.laendermonitor.de/de/vergleich-bundeslaender-daten/uebersicht-aller-indikatoren-1/bundeslaender-1",
            "kind": "catalogue",
            "note": "Server-rendered indicator overview; the indicator names are in the HTML headings.",
        },
    ],
    "strukturdaten-bundestagswahl-2021": [
        {
            "name": "btw21_strukturdaten.csv",
            "url": "https://www.bundeswahlleiter.de/dam/jcr/b1d3fc4f-17eb-455f-a01c-a0bf32135c5d/btw21_strukturdaten.csv",
            "kind": "catalogue",
            "note": "Header row is the indicator list; rows are constituencies.",
        },
        {
            "name": "beschreibung.html",
            "url": "https://www.bundeswahlleiter.de/bundestagswahlen/2021/strukturdaten/beschreibung.html",
            "kind": "catalogue",
            "note": "Per-indicator definitions, sources and reference dates for the Strukturdaten set.",
        },
    ],
    "inkar": [
        {"name": "portal.html", "url": "https://www.inkar.de/", "kind": "portal", "insecure": "1",
         "note": "Indicator workbook already indexed; see soep_metadata_output/. inkar.de serves an "
                 "incomplete certificate chain, so this one artifact skips verification."},
    ],
}

# Sources a script cannot reach from this host. `data_sources/CHECKLIST.md` (generated by
# scripts/build_status_report.py) is the canonical per-source tracker; this dict only keeps
# the acquisition reason, so `--report` still explains why a folder is empty.
MANUAL: Dict[str, str] = {
    "deutschlandatlas-erreichbarkeit-von-apotheken": (
        "RESOLVED 2026-08-25 by a manual download (Indikatoren_Deutschlandatlas.pdf + "
        "Deutschlandatlas-Daten.xlsx). www.deutschlandatlas.bund.de still answers 400 to every "
        "scripted request regardless of headers, so refreshes need a browser."
    ),
    "bundes-klinik-atlas": (
        "RESOLVED 2026-08-25: Weisse Liste is discontinued and does not complete a TLS handshake "
        "from this host. The Bundes-Klinik-Atlas open-data export (bundes-klinik-atlas.de/open-data/) "
        "replaces it and was downloaded manually."
    ),
    "german-companies": (
        "RESOLVED 2026-08-25: RapidAPI key supplied in raw/key_german_companies.txt (git-ignored; "
        "belongs in ~/.config/secrets/). The API answers via curl; a live sample response is saved "
        "as raw/api_response_sample.json. urllib times out against this host, curl does not."
    ),
    "krankenhausverzeichnis": (
        "RESOLVED 2026-08-25: the G-BA Qualitätsberichte archives (xml_2008 ... xml_2024.zip, "
        "~1.7 GB uncompressed per year) were downloaded manually. Only the schema is indexed; the "
        "per-hospital XML is never extracted in full."
    ),
    "open-data-oepnv": (
        "PARTIAL: the API description was supplied manually (raw/description_api.txt, public key "
        "included). The per-Verbund dataset catalogue still needs a free opendata-oepnv account."
    ),
    "deutsche-bahn-infrastrukturregister": (
        "OPEN: the ISR viewer requires a company registration (Unternehmen, Art des Unternehmens "
        "EVU/ZB | EIU | Anderes, Hinweise zur Registrierung). For a university researcher that is "
        "'Anderes / Sonstige'. Without it, DB's StaDa station dataset and OSM railway data are the "
        "systematic alternatives."
    ),
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_dirs() -> Dict[str, Path]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    mapping: Dict[str, Path] = {}
    for position, record in enumerate(registry["sources"], start=1):
        mapping[record["slug"]] = DATA_SOURCES / f"{position:02d}-{record['slug']}"
    return mapping


def fetch_one(url: str, target: Path, insecure: bool = False) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        },
    )
    started = time.time()
    # Some federal portals ship an incomplete certificate chain (inkar.de). Verification
    # is skipped only where the plan says so explicitly, never as a global default.
    context = ssl._create_unverified_context() if insecure else None
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
        payload = response.read()
        content_type = response.headers.get("Content-Type", "")
        status = response.status
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "status": status,
        "bytes": len(payload),
        "content_type": content_type,
        "sha256": sha256_of(target),
        "seconds": round(time.time() - started, 2),
    }


def fetch_genesapi_keys(url: str, target_dir: Path) -> Dict[str, Any]:
    """The datenguide/genesapi-data repo is ~100 MB, almost all of it downloaded GENESIS
    CSVs we do not want. Stream the tarball to a temp file, keep only the metadata
    (`keys/*.json` = the Merkmale dictionary, `src/*.yaml` = the table specs), and drop
    the archive again."""
    import shutil
    import tarfile
    import tempfile

    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    started = time.time()
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            shutil.copyfileobj(response, tmp)
            status = response.status
        archive_path = Path(tmp.name)

    digest = sha256_of(archive_path)
    archive_bytes = archive_path.stat().st_size
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    kept = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = Path(member.name).parts[1:]  # strip the repo-name root folder
            if not parts:
                continue
            keep = (parts[0] == "keys" and parts[-1].endswith(".json")) or (
                parts[0] == "src" and parts[-1].endswith(".yaml")
            )
            if not keep:
                continue
            destination = target_dir.joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            destination.write_bytes(extracted.read())
            kept += 1
    archive_path.unlink(missing_ok=True)

    return {
        "status": status,
        "bytes": archive_bytes,
        "content_type": "application/gzip (extracted)",
        "sha256": digest,
        "files_kept": kept,
        "seconds": round(time.time() - started, 2),
    }


def fetch_isr_attributes(url: str, target: Path) -> Dict[str, Any]:
    """Ask the ISR GeoServer what each of its feature types contains.

    WFS DescribeFeatureType returns the attribute list per layer, which is what turns "there is
    a layer called ISR_V_GEO_STRECKENABSCHNITTE" into something a researcher can judge."""
    import xml.etree.ElementTree as ET

    started = time.time()
    caps_url = f"{url}?service=WFS&version=2.0.0&request=GetCapabilities"
    request = urllib.request.Request(caps_url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        caps = response.read().decode("utf-8", "replace")
    names = sorted({name for name in re.findall(r"<(?:wfs:)?Name>([^<]+)</(?:wfs:)?Name>", caps)
                    if name.startswith("ISR:")})

    out: Dict[str, Any] = {"endpoint": url, "layers": {}}
    for position, name in enumerate(names, start=1):
        describe = (f"{url}?service=WFS&version=2.0.0&request=DescribeFeatureType"
                    f"&typeNames={urllib.parse.quote(name)}")
        try:
            with urllib.request.urlopen(urllib.request.Request(describe, headers={"User-Agent": UA}),
                                        timeout=TIMEOUT) as response:
                body = response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            out["layers"][name] = {"error": str(exc)[:200]}
            continue
        fields = [
            {"name": match.group(1), "type": match.group(2).split(":")[-1]}
            for match in re.finditer(r'<xsd:element[^>]*name="([^"]+)"[^>]*type="([^"]+)"', body)
        ]
        out["layers"][name] = {"fields": fields}
        time.sleep(0.2)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": 200,
        "bytes": target.stat().st_size,
        "content_type": "application/json (DescribeFeatureType)",
        "sha256": sha256_of(target),
        "layers": len(out["layers"]),
        "seconds": round(time.time() - started, 2),
    }


def load_log(folder: Path) -> Dict[str, Any]:
    path = folder / "raw" / "FETCH_LOG.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"artifacts": {}}


def save_log(folder: Path, log: Dict[str, Any]) -> None:
    path = folder / "raw" / "FETCH_LOG.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def report(dirs: Dict[str, Path]) -> None:
    for slug, folder in dirs.items():
        raw = folder / "raw"
        files = sorted(p.name for p in raw.glob("*") if p.name not in {".gitkeep", "FETCH_LOG.json"}) if raw.exists() else []
        planned = len(FETCH_PLAN.get(slug, []))
        flag = "MANUAL" if slug in MANUAL else ("ok" if files else "empty")
        print(f"{flag:>7}  {slug:<50} planned={planned:<2} present={len(files):<2} {', '.join(files[:4])}")
    print("\nNeeds a human:")
    for slug, reason in MANUAL.items():
        print(f"  - {slug}: {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=[], help="slug(s) to fetch")
    parser.add_argument("--force", action="store_true", help="re-download artifacts already present")
    parser.add_argument("--report", action="store_true", help="print status and exit")
    args = parser.parse_args()

    dirs = source_dirs()
    if args.report:
        report(dirs)
        return

    slugs = args.only or list(FETCH_PLAN)
    summary = {"fetched": 0, "skipped": 0, "failed": 0}
    for slug in slugs:
        plan = FETCH_PLAN.get(slug)
        if not plan:
            print(f"[skip] {slug}: nothing planned (see MANUAL or add a FETCH_PLAN entry)")
            continue
        folder = dirs[slug]
        log = load_log(folder)
        for artifact in plan:
            target = folder / "raw" / artifact["name"]
            if target.exists() and not args.force:
                summary["skipped"] += 1
                print(f"[have] {slug}/{artifact['name']}")
                continue
            try:
                if artifact.get("handler") == "genesapi_keys":
                    result = fetch_genesapi_keys(artifact["url"], target)
                elif artifact.get("handler") == "isr_wfs_attributes":
                    result = fetch_isr_attributes(artifact["url"], target)
                else:
                    result = fetch_one(artifact["url"], target, insecure=bool(artifact.get("insecure")))
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                summary["failed"] += 1
                print(f"[FAIL] {slug}/{artifact['name']}: {exc}")
                log["artifacts"][artifact["name"]] = {
                    "url": artifact["url"], "kind": artifact["kind"], "note": artifact["note"],
                    "error": str(exc), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                save_log(folder, log)
                continue
            summary["fetched"] += 1
            log["artifacts"][artifact["name"]] = {
                "url": artifact["url"], "kind": artifact["kind"], "note": artifact["note"],
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **result,
            }
            save_log(folder, log)
            print(f"[ok]   {slug}/{artifact['name']}  {result['bytes']} bytes  {result['content_type']}")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
