# Migration & Integration in Regionen

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 9).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://service.destatis.de/DE/karten/migration_integration_regionen.html
- **Access:** direct file download, interactive map viewer
- **Spatial levels:** Kreise & kreisfreie Städte
- **Temporal coverage:** 2022–2022
- **Update frequency:** n/a
- **Workbook note:** Stand 31.12.2022
- **Topic groups:** Migration

## Topics marked in the workbook

- **Migration**: nach Alter, nach Geschlecht, nach Staatsangehörigkeit, Schutzsuchende, Integrationskurse, AusländerInnen am Arbeitsmarkt

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

`migration_integration_regionen.zip` contains exactly the split we want:

- `migrationintegrationregionen_beschreibung.xlsx`: the indicator descriptions (the catalogue)
- `migration_integration_regionen_daten.csv`: the district-level values (not indexed)

Single reference date 31.12.2022, district level (Kreise).
