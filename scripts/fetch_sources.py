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
import http.cookiejar
import html
import json
import ssl
import time
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
    "deutschlandatlas-erreichbarkeit-von-apotheken": [
        {"name": "karten_index.json",
         "url": "https://www.deutschlandatlas.bund.de/DE/Karten/_node.html",
         "kind": "catalogue", "handler": "deutschlandatlas_maps",
         "note": "Per-indicator map pages. The site answers a 307 to a cookie-check URL, so the "
                 "fetch needs a cookie jar; the PDF and the XLSX still come from a manual "
                 "download because they are not linked from here."},
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
    "openstreetmap-poi-layer-overpass": [
        {"name": "map_features.html", "url": "https://wiki.openstreetmap.org/wiki/Map_features",
         "kind": "documentation", "note": "The tag reference the POI layers are defined against."},
        {"name": "taginfo_counts.json",
         "url": "https://taginfo.geofabrik.de/europe:germany/api/4/tag/stats",
         "kind": "catalogue", "handler": "taginfo_counts",
         "note": "Germany-only object count per POI layer, so each record states a measured "
                 "magnitude. Overpass would answer the same question but every mirror is refused "
                 "at the network level from this host (connection refused, not a timeout)."},
    ],
    "wegweiser-kommune-bertelsmann-stiftung": [
        {"name": "portal.html", "url": "https://www.wegweiser-kommune.de/", "kind": "portal", "note": ""},
        {"name": "open_data.html", "url": "https://www.wegweiser-kommune.de/open-data", "kind": "documentation",
         "note": "Names the OpenAPI spec and the CC0 licence."},
        {"name": "wegweiser_catalogue.json",
         "url": "https://www.wegweiser-kommune.de/data-api/rest",
         "kind": "catalogue", "handler": "wegweiser_api",
         "note": "393 indicators and 38 topics over the documented Data API "
                 "(/openapi?format=JSON). No account, licence CC0. The browse UI loads its tree "
                 "client-side, which is why this looked like an account-only source; it is not."},
    ],
    "dwd-climate-data-center-cdc": [
        {"name": "cdc_tree.json", "url": "https://opendata.dwd.de/climate_environment/CDC",
         "kind": "catalogue", "handler": "dwd_tree",
         "note": "The Apache directory tree IS the DWD catalogue: aggregation level by variable, "
                 "each with a directory link that can be verified."},
    ],
    "boris-d-bodenrichtwerte": [
        {"name": "portal.html", "url": "https://www.bodenrichtwerte-boris.de/", "kind": "portal", "note": ""},
        {"name": "csw_bodenrichtwerte.xml", "url": "https://gdk.gdi-de.org/gdi-de/srv/eng/csw?service=CSW&version=2.0.2&request=GetRecords&typeNames=csw:Record&resultType=results&elementSetName=summary&constraintLanguage=CQL_TEXT&constraint_language_version=1.1.0&outputSchema=http%3A%2F%2Fwww.opengis.net%2Fcat%2Fcsw%2F2.0.2&constraint=AnyText%20like%20%27%25bodenrichtwert%25%27", "kind": "catalogue", "handler": "csw_records",
         "note": "BORIS-D is a viewer over the Laender services and publishes no catalogue of its "
                 "own, so the dataset titles come from the official GDI-DE metadata catalogue "
                 "(Geodatenkatalog.de) instead."},
    ],
    "wahlergebnisse-bundeswahlleiterin": [
        {"name": "btw2025_ergebnisse.html", "url": "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse.html", "kind": "catalogue", "note": ""},
        {"name": "btw2025_kerg2.csv", "url": "https://www.bundeswahlleiterin.de/dam/jcr/f49a47a1-735b-4e9b-b4e1-4c73cad2292e/btw25_kerg2.csv", "kind": "sample",
         "note": "Wahlkreis results 2025 in the long 'kerg2' layout; its header defines the result variables."},
        {"name": "btw_ab49_datenbank_ergebnisse.csv", "url": "https://www.bundeswahlleiterin.de/dam/jcr/24d8e745-920d-431a-893a-12805bc7ef40/btw_ab49_datenbank_ergebnisse.csv", "kind": "sample",
         "note": "Results database for every Bundestag election since 1949."},
        {"name": "europawahl2024_ergebnisse.html", "url": "https://www.bundeswahlleiterin.de/europawahlen/2024/ergebnisse.html", "kind": "catalogue", "note": ""},
    ],
    "ioer-monitor-flaechennutzung": [
        {"name": "portal.html", "url": "https://www.ioer-monitor.de/", "kind": "portal", "note": ""},
        {"name": "indikatoren.html", "url": "https://www.ioer-monitor.de/indikatoren/", "kind": "catalogue",
         "note": "The section 'Übersicht der Geodienste' links the public indicator list below."},
        {"name": "indikatoren_liste.pdf",
         "url": "https://www.ioer-monitor.de/fileadmin/user_upload/monitor/pdf/Indikatoren_IOER-Monitor.pdf",
         "kind": "catalogue",
         "note": "All 88 indicators with their five-character code and category. The codes address "
                 "the WMS/WCS/WFS services directly, but the service call needs a personal key, so "
                 "the records link at dataset level and carry the code."},
    ],
    "rwi-geo-grid-rwi-geo-red-fdz-ruhr": [
        {"name": "portal.html", "url": "https://fdz.rwi-essen.de/", "kind": "portal", "note": ""},
        {"name": "fdz_datasets.json", "url": "https://fdz.rwi-essen.de/", "kind": "catalogue",
         "handler": "fdz_datasets",
         "note": "The portal lists every dataset only as a 'Details' link, so titles, DOIs, "
                 "keywords and abstracts are harvested from the da|ra detail pages."},
    ],
    "deutsche-bahn-bahnhofsuche": [
        {"name": "portal.html", "url": "https://www.bahnhof.de/bahnhof-de", "kind": "portal", "note": ""},
        {
            "name": "stada_stations.json",
            "url": "https://apis.deutschebahn.com/db-api-marketplace/apis/station-data/v2/stations?limit=10000",
            "kind": "catalogue",
            "handler": "db_stada",
            "note": "StaDa station data, 5,408 stations with category, price category, accessibility, "
                    "facilities, Aufgabentraeger and WGS84 coordinates. Needs BOTH marketplace "
                    "credentials in ~/.config/secrets/db_stada.txt (clientid= and key=): the key "
                    "alone answers 401 'Invalid client id or secret'.",
        },
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
            "name": "btw2025_strukturdaten.csv",
            "url": "https://www.bundeswahlleiterin.de/dam/jcr/181f9e38-38db-4f64-991c-8141dfa0f2cb/btw2025_strukturdaten.csv",
            "kind": "sample",
            "note": "Strukturdaten for the 2025 constituencies. Same layout as 2021: a 'Spalten-Nr' "
                    "header row followed by one column per indicator.",
        },
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
        "'Anderes / Sonstige'. RESOLVED 2026-08-25 anyway: the viewer's GeoServer is public, so no "
        "registration was needed. StaDa (row 16) covers the stations themselves."
    ),
}


def fetch_db_stada(url: str, target: Path) -> Dict[str, Any]:
    """DB API Marketplace needs two headers, `DB-Client-Id` and `DB-Api-Key`. Sending only the
    key (or the same value as both) answers 401 'Invalid client id or secret', which reads like a
    wrong key rather than a missing one."""
    secret = Path.home() / "kwandel" / ".config" / "secrets" / "db_stada.txt"
    if not secret.exists():
        raise OSError(f"missing {secret}")
    values = dict(
        line.split("=", 1) for line in secret.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    client_id = values.get("clientid", "").strip()
    api_key = values.get("key", "").strip()
    if not client_id or not api_key:
        raise OSError(f"{secret} needs both clientid= and key=")
    started = time.time()
    request = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "DB-Client-Id": client_id, "DB-Api-Key": api_key,
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = response.read()
        status = response.status
        content_type = response.headers.get("Content-Type", "")
    document = json.loads(payload.decode("utf-8"))
    if len(document.get("result") or []) < document.get("total", 0):
        raise OSError(f"StaDa returned {len(document.get('result') or [])} of {document.get('total')} stations")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {
        "status": status, "bytes": len(payload), "content_type": content_type,
        "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
        "stations": document.get("total"),
    }


# POI layers worth indexing, chosen for the questions the workbook actually asks (distance to
# the nearest playground, pharmacy, school, place of worship, stop). Each layer lists the OSM
# tags it is made of, the Overpass selector a user would run, and a German label. Counts come
# from taginfo, so every record states a measured magnitude for Germany.
OSM_POI_LAYERS: List[Tuple[str, List[Tuple[str, str]], str, str]] = [
    ("playground", [("leisure", "playground")], '["leisure"="playground"]', "Spielplätze"),
    ("pharmacy", [("amenity", "pharmacy")], '["amenity"="pharmacy"]', "Apotheken"),
    ("doctors", [("amenity", "doctors")], '["amenity"="doctors"]', "Arztpraxen"),
    ("dentist", [("amenity", "dentist")], '["amenity"="dentist"]', "Zahnarztpraxen"),
    ("hospital", [("amenity", "hospital")], '["amenity"="hospital"]', "Krankenhäuser"),
    ("clinic", [("amenity", "clinic")], '["amenity"="clinic"]', "Kliniken und Ambulanzen"),
    ("school", [("amenity", "school")], '["amenity"="school"]', "Schulen"),
    ("kindergarten", [("amenity", "kindergarten")], '["amenity"="kindergarten"]',
     "Kindergärten und Kitas"),
    ("university", [("amenity", "university"), ("amenity", "college")],
     '["amenity"~"^(university|college)$"]', "Hochschulen"),
    ("library", [("amenity", "library")], '["amenity"="library"]', "Bibliotheken"),
    ("place_of_worship", [("amenity", "place_of_worship")], '["amenity"="place_of_worship"]',
     "Gotteshäuser"),
    ("cinema", [("amenity", "cinema")], '["amenity"="cinema"]', "Kinos"),
    ("theatre", [("amenity", "theatre")], '["amenity"="theatre"]', "Theater"),
    ("restaurant", [("amenity", "restaurant"), ("amenity", "cafe"), ("amenity", "fast_food"),
                    ("amenity", "pub"), ("amenity", "bar")],
     '["amenity"~"^(restaurant|cafe|fast_food|pub|bar)$"]', "Gastronomiebetriebe"),
    ("supermarket", [("shop", "supermarket")], '["shop"="supermarket"]', "Supermärkte"),
    ("bank", [("amenity", "bank")], '["amenity"="bank"]', "Bankfilialen"),
    ("post_office", [("amenity", "post_office")], '["amenity"="post_office"]', "Postfilialen"),
    ("social_facility", [("amenity", "social_facility")], '["amenity"="social_facility"]',
     "Soziale Einrichtungen (u. a. Pflegeheime, Tafeln, Beratungsstellen)"),
    ("community_centre", [("amenity", "community_centre")], '["amenity"="community_centre"]',
     "Bürger- und Gemeinschaftshäuser"),
    ("bus_stop", [("highway", "bus_stop")], '["highway"="bus_stop"]', "Bushaltestellen"),
    ("railway_station", [("railway", "station"), ("railway", "halt")],
     '["railway"~"^(station|halt)$"]', "Bahnhöfe und Haltepunkte"),
    ("sports", [("leisure", "sports_centre"), ("leisure", "pitch"), ("leisure", "fitness_centre"),
                ("leisure", "swimming_pool")],
     '["leisure"~"^(sports_centre|pitch|fitness_centre|swimming_pool)$"]', "Sportanlagen"),
    ("park", [("leisure", "park"), ("leisure", "garden")], '["leisure"~"^(park|garden)$"]',
     "Parks und Grünflächen"),
    ("charging_station", [("amenity", "charging_station")], '["amenity"="charging_station"]',
     "Ladesäulen für E-Autos"),
    ("police", [("amenity", "police"), ("amenity", "fire_station")],
     '["amenity"~"^(police|fire_station)$"]', "Polizei- und Feuerwachen"),
    ("fuel", [("amenity", "fuel")], '["amenity"="fuel"]', "Tankstellen"),
]

# Germany-only taginfo instance. Overpass would give the same counts, but every Overpass mirror
# is refused at the network level from this host, and taginfo is a documented JSON API that is
# reachable, so the counts come from there and the Overpass query stays in the record as the
# recipe a user runs themselves.
TAGINFO_GERMANY = "https://taginfo.geofabrik.de/europe:germany/api/4/tag/stats"


def fetch_taginfo_counts(url: str, target: Path) -> Dict[str, Any]:
    """Count each POI layer in Germany from taginfo, summing over the tags a layer is made of."""
    started = time.time()
    layers: Dict[str, Any] = {}
    data_until = ""
    for key, tags, selector, label in OSM_POI_LAYERS:
        per_tag: Dict[str, int] = {}
        for tag_key, tag_value in tags:
            query = f"{url}?key={urllib.parse.quote(tag_key)}&value={urllib.parse.quote(tag_value)}"
            request = urllib.request.Request(query, headers={"User-Agent": UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                    document = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
                per_tag[f"{tag_key}={tag_value}"] = -1
                print(f"       taginfo {tag_key}={tag_value}: FAILED {exc}")
                continue
            data_until = document.get("data_until") or data_until
            total = next((row.get("count", 0) for row in document.get("data", [])
                          if row.get("type") == "all"), 0)
            per_tag[f"{tag_key}={tag_value}"] = int(total)
        counted = [value for value in per_tag.values() if value >= 0]
        layers[key] = {"label": label, "selector": selector, "tags": per_tag,
                       "total": sum(counted) if counted else None}
        print(f"       taginfo {key}: {layers[key]['total']}")
    payload = json.dumps({"source": url, "area": "europe:germany", "data_until": data_until,
                          "counted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "layers": layers}, ensure_ascii=False, indent=1).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"status": 200, "bytes": len(payload), "content_type": "application/json",
            "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
            "layers": len(layers)}


def fetch_dwd_tree(url: str, target: Path) -> Dict[str, Any]:
    """Walk the DWD CDC directory listing two levels deep and record the real product tree.

    opendata.dwd.de is a plain Apache index, so the tree IS the catalogue: which variable exists
    at which aggregation, with a directory link that can be verified.
    """
    started = time.time()
    tree: Dict[str, Dict[str, List[str]]] = {}

    def listing(path: str) -> List[str]:
        request = urllib.request.Request(path, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
        return [name for name in re.findall(r'href="([A-Za-z0-9_.\-]+/)"', body)
                if not name.startswith("..")]

    for branch in ("grids_germany", "observations_germany/climate"):
        base = f"{url.rstrip('/')}/{branch}/"
        tree[branch] = {}
        for aggregation in listing(base):
            try:
                tree[branch][aggregation.strip("/")] = [v.strip("/") for v in listing(base + aggregation)]
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                tree[branch][aggregation.strip("/")] = [f"__error__ {exc}"]
    payload = json.dumps({"root": url, "tree": tree,
                          "listed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                         ensure_ascii=False, indent=1).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    branches = sum(len(v) for v in tree.values())
    return {"status": 200, "bytes": len(payload), "content_type": "application/json",
            "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
            "aggregations": branches}


def fetch_csw_records(url: str, target: Path) -> Dict[str, Any]:
    """Page through a GDI-DE CSW GetRecords query and keep the Dublin Core summaries.

    Geodatenkatalog.de is the official German spatial metadata catalogue, and for sources whose
    own portal is a JS app (BORIS-D) it is the only machine-readable route to the dataset titles.
    """
    started = time.time()
    records: List[str] = []
    matched = 0
    for start in range(1, 402, 100):
        page = f"{url}&startPosition={start}&maxRecords=100"
        request = urllib.request.Request(page, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
        if not matched:
            found = re.search(r'numberOfRecordsMatched="(\d+)"', body)
            matched = int(found.group(1)) if found else 0
        chunk = re.findall(r"<csw:SummaryRecord[ >].*?</csw:SummaryRecord>", body, re.S)
        if not chunk:
            break
        records.extend(chunk)
        if len(records) >= matched:
            break
    payload = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<records matched=\"%d\">\n%s\n</records>\n"
               % (matched, "\n".join(records))).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"status": 200, "bytes": len(payload), "content_type": "application/xml",
            "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
            "records": len(records), "matched": matched}


def fetch_fdz_datasets(url: str, target: Path) -> Dict[str, Any]:
    """Harvest the FDZ Ruhr dataset catalogue from its da|ra detail pages.

    The portal lists only "Details" as link text, so the titles, DOIs, keywords and abstracts
    have to come from the detail pages themselves. One page per dataset, so the catalogue is
    complete rather than a hand-picked subset.
    """
    started = time.time()

    def page(target_url: str) -> str:
        request = urllib.request.Request(target_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read().decode("utf-8", errors="replace")

    index = page(url)
    paths = sorted({match for match in re.findall(r'href="(/doi-detail/[^"]+\.html)"', index)})
    base = "https://fdz.rwi-essen.de"

    def field(body: str, name: str) -> str:
        found = re.search(rf"<strong>{re.escape(name)}</strong>\s*:?\s*(.*?)</p>", body, re.S)
        if not found:
            return ""
        text = re.sub(r"<[^>]+>", " ", found.group(1))
        return " ".join(html.unescape(text).split())

    datasets: List[Dict[str, Any]] = []
    for path in paths:
        try:
            body = page(base + path)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            print(f"       fdz {path}: FAILED {exc}")
            continue
        heading = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
        section = re.search(r"Beschreibung</h2>(.*?)(?:<h2|\Z)", body, re.S)
        description = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", section.group(1))).split()) if section else ""
        keywords = re.search(r"Schlagworte</h2>(.*?)(?:<h2|\Z)", body, re.S)
        datasets.append({
            "url": base + path,
            "name": " ".join(html.unescape(re.sub(r"<[^>]+>", "", heading.group(1))).split()) if heading else "",
            "title": field(body, "Titel"),
            "doi": field(body, "DOI"),
            "language": field(body, "Sprache"),
            "access": field(body, "Verfügbarkeit") or field(body, "Zugangsbedingungen"),
            "period": field(body, "Zeitraum") or field(body, "Zeitliche Abdeckung"),
            "geography": field(body, "Geographische Abdeckung") or field(body, "Raum"),
            "keywords": " ".join(html.unescape(re.sub(r"<[^>]+>", " ", keywords.group(1))).split()) if keywords else "",
            "description": description[:2000],
        })
    payload = json.dumps({"index": url, "datasets": datasets,
                          "harvested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                         ensure_ascii=False, indent=1).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"status": 200, "bytes": len(payload), "content_type": "application/json",
            "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
            "datasets": len(datasets)}


def fetch_deutschlandatlas_maps(url: str, target: Path) -> Dict[str, Any]:
    """The Deutschlandatlas map index, with the per-indicator map URLs.

    This host was previously recorded here as answering 400 to every scripted request. That was
    wrong: it answers a 307 to a cookie-check URL, and a client that keeps the cookie and follows
    the redirect gets the page. urllib does that with an HTTPCookieProcessor; without one the
    redirect loops back and the site looks broken.
    """
    started = time.time()
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent", UA),
        ("Accept", "text/html,application/xhtml+xml"),
        ("Accept-Language", "de-DE,de;q=0.9"),
    ]
    with opener.open(url, timeout=TIMEOUT) as response:
        body = response.read().decode("utf-8", errors="replace")
        status = response.status

    maps: List[Dict[str, str]] = []
    seen: set = set()
    for href, inner in re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        # The page links its maps RELATIVE and without a leading slash
        # ("DE/Karten/Wo-wir-leben/003/_node.html"), so anchoring on "/DE/Karten/" finds nothing.
        href = " ".join(href.split())
        if "DE/Karten/" not in href or "#" in href:
            continue
        if href.rstrip("/").endswith("Karten/_node.html"):
            continue
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inner)).replace("\u00ad", "").split())
        if not title or title.startswith("Zur "):
            continue
        absolute = urllib.parse.urljoin("https://www.deutschlandatlas.bund.de/", href.lstrip("/"))
        theme = href.split("DE/Karten/")[-1].split("/")[0].replace("-", " ")
        if absolute in seen:
            continue
        seen.add(absolute)
        maps.append({"title": title, "url": absolute, "theme": theme})

    payload = json.dumps({"index": url, "maps": maps,
                          "harvested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                         ensure_ascii=False, indent=1).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"status": status, "bytes": len(payload), "content_type": "application/json",
            "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
            "maps": len(maps)}


def fetch_wegweiser_api(url: str, target: Path) -> Dict[str, Any]:
    """Wegweiser Kommune's documented Data API: the whole indicator catalogue in two calls.

    The portal's own browse UI renders its indicator tree client-side, so the source looked like
    it needed an account. It does not: /open-data documents an OpenAPI spec, the data is CC0, and
    `rest/indicator/list?max=...` returns every indicator with its explanation, calculation
    formula, source, unit, years and the finest region type it is published for. The default
    `max` is 10, which is what makes an unparameterised call look like a stub.
    """
    started = time.time()

    def get(path: str) -> Any:
        request = urllib.request.Request(f"{url.rstrip('/')}/{path}", headers={
            "User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    indicators = get("indicator/list?max=2000")
    topics = get("topic/list?max=2000")
    payload = json.dumps({
        "api": url,
        "licence": "CC0 1.0 (Bertelsmann Stiftung, Wegweiser Kommune)",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indicators": indicators,
        "topics": [{k: v for k, v in topic.items() if k != "indicators"} for topic in topics],
    }, ensure_ascii=False, indent=1).encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return {"status": 200, "bytes": len(payload), "content_type": "application/json",
            "sha256": sha256_of(target), "seconds": round(time.time() - started, 2),
            "indicators": len(indicators), "topics": len(topics)}


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
                elif artifact.get("handler") == "deutschlandatlas_maps":
                    result = fetch_deutschlandatlas_maps(artifact["url"], target)
                elif artifact.get("handler") == "wegweiser_api":
                    result = fetch_wegweiser_api(artifact["url"], target)
                elif artifact.get("handler") == "taginfo_counts":
                    result = fetch_taginfo_counts(artifact["url"], target)
                elif artifact.get("handler") == "dwd_tree":
                    result = fetch_dwd_tree(artifact["url"], target)
                elif artifact.get("handler") == "fdz_datasets":
                    result = fetch_fdz_datasets(artifact["url"], target)
                elif artifact.get("handler") == "csw_records":
                    result = fetch_csw_records(artifact["url"], target)
                elif artifact.get("handler") == "db_stada":
                    result = fetch_db_stada(artifact["url"], target)
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
