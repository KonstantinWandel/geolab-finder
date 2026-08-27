# OpenStreetMap POI-Layer (Overpass)

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 31).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://wiki.openstreetmap.org/wiki/Map_features
- **Access:** direct file download, web UI / search form only, machine-readable API, interactive map viewer
- **Spatial levels:** Bundesland, Kreise & kreisfreie Städte, Gemeinden und Verbandsgemeinden, PLZ, Adressen / Koordinaten, weitere räumliche Gliederungen
- **Temporal coverage:** 2004–2026
- **Update frequency:** laufend
- **Workbook note:** Overpass-API, freie Abfrage nach Tags; systematischer Ersatz für die Spielplatz- und Arztsuchportale
- **Topic groups:** Bildung, Gesundheit, Kinder und Jugend, Kultur, Nachhaltigkeit, Religion, Sport, Verkehr / Mobilität, Wirtschaft und Unternehmen

## Topics marked in the workbook

- **Bildung**: Anzahl Schulen, Distanz nächste Schule/Hochschule/VHS
- **Gesundheit**: Distanz zum nächsten (Fach-)Arzt, Distanz zur nächsten Apotheke
- **Kinder und Jugend**: Distanz nächster Spielplatz
- **Kultur**: Kinos, Distanz nächstes Theater, Anzahl Gastronomiebetriebe / Bewohner
- **Nachhaltigkeit**: Bildung
- **Religion**: Distanz zum nächsten Gotteshaus
- **Sport**: Sportanlagen / Einwohner
- **Verkehr / Mobilität**: ÖPNV
- **Wirtschaft und Unternehmen**: Anzahl Läden / Bewohner

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
