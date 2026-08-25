# Drop folder: georeferenced data sources for the GeoDB finder

**Put downloaded catalogue files in `<NN>-<source-slug>/raw/`. One folder per portal.**

This is the staging area for folding the 26 external portals listed in
`../Geospatial_Data_Sources.xlsx` into the GeoDB finder at
<https://geodb.geolab.soz.uni-bielefeld.de/>, which serves them alongside INKAR.

## What the finder is for

A researcher types a concept ("childcare coverage in rural districts", "Breitband
Verfügbarkeit Gemeindeebene", "Arztdichte") and gets back a ranked list of
**indicators that exist somewhere in German official/public regional statistics**,
each with a description, its spatial levels, its years, and a link out to the portal
that holds it. We index and describe; we do not host or redistribute the measurements.
The point is discoverability: these catalogues live in dense PDFs, spreadsheet
appendices and JS-only browse UIs that search engines index badly or not at all.

## What to put in `raw/`

Whatever lists **which indicators a portal offers**, as fine-grained as you can get
without downloading the actual measurements:

| Good | Example |
|---|---|
| indicator/variable overview workbook | INKAR's `Indikatorenübersicht (INKAR 2025).xlsx` (the model case) |
| codebook / methods PDF naming the indicators | BA `Strukturdaten und -indikatoren` Methodenteil |
| API catalogue response saved as JSON | GENESIS `catalogue/tables`, offeneregister schema |
| CSV/XLSX of the variable list | Strukturdaten Bundestagswahl 2021 |
| saved HTML of the browse/theme tree | portals with no downloadable list |

Not needed: the measurement values. If a file happens to contain both (a wide CSV of
values whose header row *is* the indicator list), drop it anyway and say so.

Leave files exactly as downloaded, no manual cleaning or renaming of columns. Use
descriptive filenames (`indicator-overview-2025.xlsx`, `api-catalogue-2026-08.json`).
If a portal needs a login or a request form, note that in `SOURCE.md` under
"Manual notes" instead of leaving the folder empty.

## Folder layout

```
data_sources/
  README.md                     this file
  registry/geo_sources.json     the canonical source list, generated from the workbook
  registry/geo_sources.csv      same, for eyeballing in Excel
  NN-<slug>/
    SOURCE.md                   brief: URL, access mode, spatial levels, topics, years
                                (generated once, then hand-edited; never overwritten)
    source_meta.json            machine-readable twin, regenerated from the workbook
    raw/                        >>> your downloads go here <<<
  _TEMPLATE/                    copy this for a portal that is not in the workbook
```

Regenerate the registry and scaffold (idempotent, safe to re-run):

```bash
/home/researcher/miniconda3/envs/geolab-rag/bin/python scripts/build_source_registry.py
```

It asserts the workbook still holds 26 sources, so an edited/replaced workbook fails
loudly instead of quietly producing a partial registry.

## Where to start (priority)

Effort per source is dominated by whether a machine-readable indicator list exists.

**Tier 1: real catalogues, biggest payoff.** These plausibly add hundreds to
thousands of indicator-level records each:

- `01-regionalatlas-deutschland`: GENESIS-backed, has an indicator list per theme
- `21-datenguide-abgeschaltet`: portal is off, but its indicator tree came from
  Regionalstatistik/GENESIS codes, which are still live and enumerable via the API
  (see the `zensus-genesis-api` skill: the token header gotcha is already solved)
- `26-strukturdaten-bundestagswahl-2021`: fixed, well-documented indicator set
- `25-laendermonitor-fruehkindliche-bildungssysteme`: "Übersicht aller Indikatoren"
- `05-strukturdaten-und-indikatoren-ba`, `06-arbeitsmarktreport-ba`,
  `07-arbeitsmarkt-kommunal-ba`: BA publication series with stable indicator tables
- `08-migration-integration-in-regionen`: Destatis regional map, downloadable
- `02-breitband-monitor` / `03-breitbandatlas`: small but very fine spatial grain

**Tier 2: portals that are really a search UI over a register.** There is no
indicator catalogue to index; what we can offer is one well-written record per portal
("find a hospital / a physician / a university by place"), so a concept query still
routes the researcher there. Low effort, low volume, still worth having:
`10`, `11`, `12`, `13`, `14`, `15`, `16`, `18`, `19`, `23`, `24`.

**Tier 3: already done or dead.** `22-inkar` is live in the finder today.
`20-destatis-regionale-mobilitaet` and `11-fachaerztesuche-weisse-liste` are
discontinued; keep them indexed with an explicit "no longer updated" flag rather than
dropping them, since the historical data is still citable.

Several Tier-1 catalogues are plain HTTP downloads I can fetch from here without you
doing anything. Say the word and I will try those first, so your manual work is
limited to the ones behind logins, request forms, or JS-only UIs.

## Current state

**`CHECKLIST.md` in this folder is the tracker**: one entry per source with its state, what has been
downloaded, how many records it contributes, and the next step. It is generated, so it cannot go
stale:

```bash
E=/home/researcher/miniconda3/envs/geolab-rag/bin/python
$E scripts/fetch_sources.py            # fetch what is publicly downloadable
$E scripts/build_geodb_metadata.py     # raw/ -> soep_metadata_output/geodb_metadata.json
$E scripts/build_status_report.py      # -> CHECKLIST.md + the Status_GeoDB sheet in the workbook
```

`build_status_report.py` also appends a blue-marked `Status_GeoDB` sheet to
`../Geospatial_Data_Sources.xlsx`; the untouched original is kept as `*_orig.xlsx`. Per-source state
is edited in that script's `OPEN_ITEMS`, never in the generated files. Its `CANDIDATES` list holds
sources worth adding that are not in the workbook at all.

## What happens after the files land

`scripts/build_geodb_metadata.py` turns `raw/` into `soep_metadata_output/geodb_metadata.json`,
the finder's common record schema. As of 2026-08-25 that is **3,298 records**: Regionalatlas 232,
Regionalstatistik/GENESIS Merkmale 2,756, BA Strukturdaten 68, Bundestagswahl 2021 49,
Migration & Integration 140, Ländermonitor 17, Hochschulkompass 11, plus 25 portal-level records.
Every record carries an outward link, and the build fails if one does not.

Dropping a new file into a `raw/` folder means: re-run the builder, re-embed, redeploy. If the
source has no flattener yet, add one to `FLATTENERS` in that script (and a `FETCH_PLAN` entry in
`fetch_sources.py` if it is downloadable).

See `../CLAUDE.md` for the full pipeline, the record schema, and the rules that go with it.
