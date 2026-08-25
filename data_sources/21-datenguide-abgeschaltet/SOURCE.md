# Datenguide (abgeschaltet)

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 22).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://datengui.de/statistiken
- **Access:** web UI / search form only, machine-readable API
- **Spatial levels:** Bundesland, Kreise & kreisfreie Städte
- **Temporal coverage:** 1995–2022
- **Update frequency:** n/a
- **Workbook note:** abhängig von Variable
- **Topic groups:** Arbeitsmarkt & Beschäftigung, Bevölkerung, Finanzen, Gesundheit, Kinder und Jugend, Migration, Politik, Soziales, Verkehr / Mobilität, Wirtschaft und Unternehmen

## Topics marked in the workbook

- **Arbeitsmarkt & Beschäftigung**: Beschäftigte, Arbeitslose (-nquote), Ein-/Auspendler
- **Bevölkerung**: Bevölkerungsstand, Bevölkerung nach Geschlecht / Alter, Wanderungen, Geburten und Sterbefälle, Durchschnittsalter
- **Finanzen**: Insolvenzen
- **Gesundheit**: Krankenhäuser (Bettendichte), Pflege und Personal
- **Kinder und Jugend**: Kinderbetreuung
- **Migration**: nach Alter, nach Staatsangehörigkeit
- **Soziales**: Sozialleistungen
- **Verkehr / Mobilität**: Straßenverkehrsunfälle
- **Politik**: Bundestagswahl, Europawahl, Landtagswahl, Wahlberechtigte
- **Wirtschaft und Unternehmen**: landwirtschaftl. Betriebe, Gewerbean-/ abmeldungen, Unternehmensinsolvenzen

## What to drop in `raw/`

Anything that lists **what indicators this portal offers**, at the finest granularity
you can get without downloading the actual data:

- an indicator/variable overview (`.xlsx`, `.csv`, `.pdf` codebook, `.json`)
- an API catalogue response (e.g. the list-of-tables endpoint saved as `.json`)
- a saved copy of the portal's indicator/theme browse page (`.html`) if there is no
  downloadable list
- the metadata/documentation PDF that names and defines the indicators

Not needed: the measurement values themselves. The finder indexes *descriptions* and
sends the researcher to this portal.

Name files descriptively (`indicator-overview-2025.xlsx`, `api-catalogue-2026-08.json`)
and leave them as downloaded, no manual cleaning.

## Manual notes

- Provider / publisher:
- Licence / terms of use:
- Identifier scheme (indicator codes?):
- Deep-link pattern to a single indicator (if any):
- Status:

## Fetched 2026-08-25 (automated)

The Datenguide portal is a stub now (`portal.html` is a placeholder "Datenportal" page), but the
project's curated metadata survives on GitHub and is the real prize here.

`genesapi-data/` holds the extract of `github.com/datenguide/genesapi-data`:

- `keys/`: **5,514 JSON files**, one per GENESIS/Regionalstatistik *Merkmal* per language
  (~2,757 keys x de/en). Each is `{code, lang, name, description, type}`, and a large share
  carry the full Destatis definition text (Begriffsinhalt, Erläuterungen, which statistics use
  the key). Example: `BEV001` = "Lebendgeborene" with the PStV-based definition.
- `src/`: 18 YAML table specs mapping GENESIS table codes to their key columns.

The repo tarball is ~65 MB and almost all of it is downloaded GENESIS CSVs; the fetcher streams
it, keeps `keys/` and `src/*.yaml`, and discards the archive (see `fetch_genesapi_keys`).

This is a variable-level catalogue for the whole of Regionalstatistik, so it also covers what a
live GENESIS/Regionalstatistik crawl would give (see the `zensus-genesis-api` skill for the API
route and its token gotcha, if we later want current table lists rather than this snapshot).
Link out to `https://www.regionalstatistik.de/genesis/online` per statistic.
