# Hochschulkompass

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 15).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://www.hochschulkompass.de/hochschulen/hochschulsuche.html
- **Access:** web UI / search form only, on request / registration needed
- **Spatial levels:** not stated
- **Temporal coverage:** not stated
- **Update frequency:** n/a
- **Workbook note:** keine Angabe , vermutlich laufend
- **Topic groups:** Bildung

## Topics marked in the workbook

- **Bildung**: Distanz nächste Schule/Hochschule/VHS

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

## Fetched 2026-08-25 (automated / manual)

`hs_liste.txt` was downloaded by Konstantin. It is **tab-separated, Latin-1 (not UTF-8), 390
institutions**, header row: `Hs-Nr., Hochschulkurzname, Hochschulname, Adressname, Hochschultyp,
Trägerschaft, Bundesland, Anzahl Studierende, Gründungsjahr, Promotionsrecht, Habilitationsrecht,
Straße, Postleitzahl, Ort, Postfach, PLZ (Postanschrift), Ort (Postanschrift), Telefonvorwahl,
Telefon, Fax, Home Page, Mitglied HRK`.

This is an entity register, not an indicator table: rows are institutions, georeferenced by
street address and postcode. Index it as a small set of attribute-level records (institution
count, students per institution, type, sponsorship, founding year, doctoral rights, location),
so that "Hochschulstandorte" or "Studierende je Hochschule" routes here.
