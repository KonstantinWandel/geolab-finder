# Strukturdaten und -indikatoren - BA

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 6).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://statistik.arbeitsagentur.de/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html?nn=15024&topic_f=zdf-sdi&dateOfRevision=201006-202106
- **Access:** direct file download
- **Spatial levels:** Bundesland, weitere räumliche Gliederungen
- **Temporal coverage:** 2010–2021
- **Update frequency:** halbjährlich
- **Workbook note:** none
- **Topic groups:** Arbeitsmarkt & Beschäftigung, Bevölkerung, Bildung, Soziales, Wirtschaft und Unternehmen

## Topics marked in the workbook

- **Arbeitsmarkt & Beschäftigung**: Beschäftigte nach Wirtschaftsbereichen, Arbeitslose (-nquote), Unterbeschäftigungsquote
- **Bevölkerung**: Bevölkerungsstand, Bevölkerung nach Geschlecht / Alter, Wanderungen
- **Bildung**: Berufsausbildungsstellen, Bewerber Berufsausbildungsstellen
- **Soziales**: Sozialleistungen
- **Wirtschaft und Unternehmen**: BIP

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

`sdi-071-0-202106.xlsx` is one representative regional booklet. Its sheets are the catalogue:
`Strukturdaten`, `Strukturindikatoren`, `Glossar Strukturdaten`, `Meth. Hinw. Strukturindikatoren`.
The indicator set is identical across regions, so one booklet defines the whole series and the
per-region files are values we do not index.

**BA download URL pattern** (works without a session, strip the `;jsessionid=...`):
`https://statistik.arbeitsagentur.de/Statistikdaten/Detail/<YYYYMM>/<unit>/<topic>/<file>-xlsx.xlsx?__blob=publicationFile&v=1`
The search form at `Einzelheftsuche_Formular.html?...&topic_f=<topic>` lists the current files.
