# RWI-GEO-GRID / RWI-GEO-RED (FDZ Ruhr)

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 37).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://fdz.rwi-essen.de/
- **Access:** on request / registration needed
- **Spatial levels:** Bundesland, Kreise & kreisfreie Städte, Gemeinden und Verbandsgemeinden, PLZ, Adressen / Koordinaten, weitere räumliche Gliederungen
- **Temporal coverage:** 2005–2024
- **Update frequency:** jährlich
- **Workbook note:** 1-km-Raster mit sozioökonomischen Merkmalen und geocodierte Immobilienanzeigen; Scientific-Use-Files auf Antrag
- **Topic groups:** Bauen / Wohnen, Bevölkerung, Soziales

## Topics marked in the workbook

- **Bauen / Wohnen**: Mietpreise, Wohnfläche je Wohnung / Einwohner
- **Bevölkerung**: Bevölkerungsstand
- **Soziales**: Einkünfte, Armutsgefährdung

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
