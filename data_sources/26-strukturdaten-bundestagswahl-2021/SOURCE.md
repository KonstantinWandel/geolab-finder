# Strukturdaten Bundestagswahl 2021

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 27).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://www.bundeswahlleiter.de/bundestagswahlen/2021/strukturdaten/bund-99.html
- **Access:** on request / registration needed
- **Spatial levels:** Bundesland, weitere räumliche Gliederungen
- **Temporal coverage:** 2018–2021
- **Update frequency:** vierjährig
- **Workbook note:** abhängig von Variable
- **Topic groups:** Arbeitsmarkt & Beschäftigung, Bevölkerung, Bildung, Flächennutzung, Kinder und Jugend, Soziales, Verkehr / Mobilität, Wirtschaft und Unternehmen

## Topics marked in the workbook

- **Arbeitsmarkt & Beschäftigung**: Beschäftigte, Beschäftigte nach Wirtschaftsbereichen, Arbeitslose (-nquote)
- **Bevölkerung**: Bevölkerungsstand, Bevölkerung nach Geschlecht / Alter, Geburten und Sterbefälle
- **Bildung**: Abschlüsse, Schulabgänger*innen
- **Flächennutzung**: Bodennutzung
- **Kinder und Jugend**: Kinderbetreuung
- **Soziales**: Sozialleistungen
- **Verkehr / Mobilität**: PKW-Dichte
- **Wirtschaft und Unternehmen**: Unternehmen

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

- `btw21_strukturdaten.csv` (UTF-8 with BOM, `;`-separated, 7 comment lines then a column-number
  row then the header row): **48 indicators** by constituency, e.g. "Bevölkerungsdichte am
  31.12.2019 (EW je km²)", plus the BA-sourced labour-market columns 35-48.
- `beschreibung.html`: per-indicator definitions, source and reference date. Pair the two:
  the CSV header gives the indicator names, this page gives the descriptions.

Spatial level is the Bundestag constituency (Wahlkreis), which is a level INKAR does not carry.
