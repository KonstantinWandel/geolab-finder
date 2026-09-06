# Gesundheitsberichterstattung des Bundes (GBE) und Versorgungsatlas

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 45).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://www.gbe-bund.de/
- **Access:** direct file download, web UI / search form only, interactive map viewer
- **Spatial levels:** Bundesland, Kreise & kreisfreie Städte, weitere räumliche Gliederungen
- **Temporal coverage:** 1990–2026
- **Update frequency:** laufend
- **Workbook note:** Gesundheitsindikatoren von Sterblichkeit über Krankheiten bis zu Ausgaben und Personal, überwiegend auf Landesebene; der Versorgungsatlas des Zi ergänzt kleinräumige Analysen der ambulanten Versorgung
- **Topic groups:** Gesundheit, Soziales

## Topics marked in the workbook

- **Gesundheit**: Lebenserwartung, Krankenhäuser (Bettendichte), Pflege und Personal, Behandlungen und Todesursachen, Einwohner je Arzt
- **Soziales**

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
