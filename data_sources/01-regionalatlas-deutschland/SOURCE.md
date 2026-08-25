# Regionalatlas Deutschland

<!-- Auto-generated stub from Geospatial_Data_Sources.xlsx (row 2).
     Everything below the "Manual notes" line is yours to edit; the generator will
     never overwrite this file once it exists. -->

- **Portal URL:** https://regionalatlas.statistikportal.de/
- **Access:** direct file download, interactive map viewer
- **Spatial levels:** Bundesland, Regierungsbezirke, Kreise & kreisfreie Städte, Gemeinden und Verbandsgemeinden
- **Temporal coverage:** 1998–2023
- **Update frequency:** jährlich
- **Workbook note:** abhängig von Variable
- **Topic groups:** Arbeitsmarkt & Beschäftigung, Bauen / Wohnen, Bevölkerung, Bildung, Flächennutzung, Gender, Gesundheit, Kinder und Jugend, Migration, Nachhaltigkeit, Politik, Soziales, Tourismus, Verkehr / Mobilität, Wirtschaft und Unternehmen

## Topics marked in the workbook

- **Arbeitsmarkt & Beschäftigung**: Beschäftigte nach Wirtschaftsbereichen, Beschäftigtenquote, Arbeitslose (-nquote), Beschäftigte im öffentlichen Bereich, Einkünfte
- **Bauen / Wohnen**: Bautätigkeit und Wohnen
- **Bevölkerung**: Bevölkerungsstand, Bevölkerung nach Geschlecht / Alter, Wanderungen, Durchschnittsalter
- **Bildung**: Schulabgänger*innen, Betreuungsquote
- **Flächennutzung**: nach ALKIS, nach ALB
- **Gender**: Elterngeldbezug, männliche Schulabgänger, Erwerbstätigkeit, Arbeitslosigkeit, Grundsicherung, männliches pädag. Personal
- **Gesundheit**: Krankenhäuser (Bettendichte), Pflege und Personal
- **Kinder und Jugend**: Kinderbetreuung
- **Migration**: AusländerInnen am Arbeitsmarkt
- **Nachhaltigkeit**: Landbewirtschaftung, Bildung, Arbeitslosigkeit junger Menschen, Straßenverkehr, wirtschaftl. Leistungsfähigkeit, Umwelt
- **Soziales**: Verfügbares Einkommen je EW, Einkünfte, Armutsgefährdung, Sozialleistungen
- **Tourismus**: Beherbung
- **Verkehr / Mobilität**: PKW-Dichte, Straßenverkehrsunfälle
- **Politik**: Bundestagswahl, Europawahl
- **Wirtschaft und Unternehmen**: Investitionen, Bruttoentgelte, landwirtschaftl. Betriebe, Gewerbean-/ abmeldungen, Unternehmensinsolvenzen, BIP, BWS

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

The Regionalatlas is an ArcGIS/dojo app, and its whole catalogue is served as static JSON
behind the map. Two copies exist:

- `services.json` (`/app/json/services.json`): 20 themes, 164 indicators, years 1998-2022
- `services_taskrunner.json` (`/taskrunner/services.json`): 21 themes, **217 indicators**,
  years 1998-2026. **Use this one**; the `/app/json/` copy is stale.

Structure: `[{title, children:[{code (TCode), title_short, title_long, years{...geom levels},
attributes:[{code (ICode), title_short, unit, meta}]}]}]`. Every one of the 217 indicators has
a `meta` wiki-text with `===Aussage===` (what it measures), `===Indikatorberechnung===` (formula)
and `===Herkunftsstatistiken===` (source statistics). That is exactly the description material
the finder needs, no enrichment required.

`thesaurus.csv` (`/app/csv/thesaurus.csv`, **Latin-1**, `;`-separated) adds a synonym column per
indicator: `ID;type;code;title_short;title_long;synonyms;theme_code;theme_title` where type is
`OK` (theme), `MK` (indicator group) or `EK` (indicator). Fold the synonyms into the embedding
context; they are hand-curated German search terms.

**Deep-link pattern (per indicator):**
`https://regionalatlas.statistikportal.de/?BL=DE&TCode=<TCode>&ICode=<ICode>&Jhr=<year>`

Indicator values themselves come from Regionalstatistik: the app links out to
`https://www.regionalstatistik.de/genesis/online?operation=table&code=<GENESIS code>`.
