# Marktstammdatenregister (Bundesnetzagentur)

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 41).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://www.marktstammdatenregister.de/MaStR
- **Access:** direct file download, web UI / search form only, machine-readable API, interactive map viewer
- **Spatial levels:** Bundesland, Kreise & kreisfreie Städte, Gemeinden und Verbandsgemeinden, PLZ, Adressen / Koordinaten
- **Temporal coverage:** 2019–2026
- **Update frequency:** täglich
- **Workbook note:** Amtliches Register aller Strom- und Gaserzeugungsanlagen mit Adresse, Koordinaten, Leistung und Inbetriebnahme; vollständiger Datenexport frei
- **Topic groups:** Nachhaltigkeit, Ver- und Entsorgung, Wirtschaft und Unternehmen

## Topics marked in the workbook

- **Nachhaltigkeit**: Umwelt
- **Ver- und Entsorgung**
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
