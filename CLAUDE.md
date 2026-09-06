# GeoLAB metadata finders (this repo = the GeoDB / INKAR finder)

Project-specific guide. Workspace-wide rules live in `~/kwandel/CLAUDE.md` and apply here too.

## What this is, in one paragraph

Semantic search over research-data **metadata**, so a researcher can type a plain-language
concept ("childcare coverage in rural districts", "Arztdichte", "net labour income") and get a
ranked list of variables or regional indicators that exist somewhere in German survey and
official statistics, each with a description, its spatial levels, its years, and a **link out to
the portal that holds it**. We index descriptions and route people onward. We never host,
redistribute, or serve the measurements themselves. The reason this is worth building: these
catalogues live in dense PDFs, spreadsheet appendices and JS-only browse UIs that search engines
index badly or not at all, so a dataset that would answer someone's question is effectively
invisible to them.

Two finders, one codebase, selected by `GEOLAB_APP_MODE`:

- `soep`: SOEP-Core survey variables (~22k), live at <https://soep-faiss.geolab.soz.uni-bielefeld.de/>
- `inkar`: INKAR 2025 regional indicators, live at <https://geodb.geolab.soz.uni-bielefeld.de/>

## Current goal: many sources, not just INKAR

The `inkar` mode is being generalised into a **GeoDB finder over many German georeferenced data
sources**. The 26 candidate portals are catalogued in `Geospatial_Data_Sources.xlsx` (a coverage
matrix: portal by spatial level by topic; the portal URLs are Excel hyperlinks on the name cells,
invisible to pandas, so read them with openpyxl).

The pipeline, end to end (all four steps are committed scripts):

```bash
E=/home/researcher/miniconda3/envs/geolab-rag/bin/python
$E scripts/build_source_registry.py        # workbook  -> data_sources/ registry + per-source briefs
$E scripts/fetch_sources.py                # portals   -> data_sources/<NN>-<slug>/raw/ + FETCH_LOG.json
$E scripts/build_geodb_metadata.py         # raw/      -> soep_metadata_output/geodb_metadata.json
cd backend && GEOLAB_APP_MODE=inkar SOEP_RAG_DEVICE=cuda \
  INKAR_METADATA_ROOT=$PWD/../soep_metadata_output $E -c \
  "from app.services.soep_rag_advisor import SOEPRagAdvisorService as S; print(S().build_and_save_embeddings(64))"
```

`build_geodb_metadata.py` holds one flattener per source in `FLATTENERS` plus a `portal_record`
fallback, and emits the finder's common schema directly, so the backend only needs the
pass-through `_normalise_geodb_row`. The schema is defined by example in `_normalise_inkar_row`:
`source_key`, `source_label`, `item_type`, `item_id`, `variable_name`, `label`, `dataset_label`,
`theme`, `spatial_levels`, `nuts_levels`, `year_start`/`year_end`, `available_years_text`,
`search_description`, `source_url`, `indicator_url`, `api_hint`, `embedding_context`.

State as of 2026-09-06: **live at <https://geodb.geolab.soz.uni-bielefeld.de/> with 12,299 rows**
(11,639 GeoDB records + 660 INKAR) from **43 workbook rows, 38 of which carry real records**.
Tracker: **29 done, 2 partial, 5 open**. Largest: Regionalstatistik/GENESIS 3,306,
GENESIS-Online Bund 3,027, Zensus 2022 1,441, Gigabit-Grundbuch 633, DB ISR 416,
Wegweiser Kommune 393, BA-Glossar 314, BA Arbeitsmarktreport 289, Open Data ÖPNV 324,
Regionalatlas 233, Migration & Integration 141, DWD Klimadaten 137, Strukturdaten BTW 99,
IÖR-Monitor 92, Deutschlandatlas 87, BA Strukturdaten 69, G-BA 52, Bundes-Klinik-Atlas 42,
Wahlergebnisse 39, DB StaDa 38, BA Arbeitsmarkt kommunal 34, FDZ Ruhr 29, OSM POI-Layer 27,
Unfallatlas 26, BORIS-D 22, Ländermonitor 18, offeneregister 14, Hochschulkompass 12,
Destatis Mobilität 7.

**Link precision is the quality number to watch**, and it moved most on 2026-08-29: 5,332 records
open the exact table, 2,821 the dataset, 2,272 the statistic, 737 the indicator itself, and only
**180 land on a portal** where the reader still has to search. It was 1,630 portal-level in the
morning; `scripts/resolve_merkmal_statistics.py` resolved 1,429 of the 1,596 Regionalstatistik
Merkmale that had no statistic code in their definition text, by asking
`catalogue/statistics2variable` once per Merkmal.

Retrieval gates 2026-08-29 (both run on CPU with the production reranker settings):
GeoDB **58 queries, hit@1 55, hit@3 58, hit@10 58, no misses**; SOEP **59 queries, hit@1 49,
hit@3 55, hit@10 59, no misses**. The SOEP gate (`scripts/eval_soep_search.py`) is new: the finder
had none, so no change to it could be told apart from a regression.

**Both finders are bilingual.** `frontend/src/i18n.js` holds the German and English interface text
and a `makeTranslator(lang)` helper; German is the default whenever the browser asks for it, and
the choice sits next to the theme picker and persists per browser. Product names and everything
that comes out of the DATA (record labels, source labels, themes) are deliberately NOT translated:
those strings are what the portals themselves call the thing, and renaming them would break the
link between what the finder shows and what the source calls it. Add a UI string to both `en` and
`de`; a missing key falls back to English and then to the key, so a half-translated build is
visible rather than blank.

**The facet dropdowns are part of the data, so duplicates are fixed in the build.** Destatis writes
the same statistic title two ways depending on the instance ("Statistik d. Empfänger v. Hilfe z.
Lebensunterhalt" regionally, spelled out federally), which listed one statistic twice in the theme
filter. `unify_facet_values()` merges spelling variants (abbreviation expansion, separator
unification, truncation like "Rehabilitationseinr.", article drop) and keeps the spelled-out
spelling; `align_portal_labels()` gives a portal card the name its own source's records use. Both
mistakes are silent and point in opposite directions, so the matcher has a self-test:
`build_geodb_metadata.py --self-test` asserts that "Kranken-" and "Rentenversicherung", SGB II and
III, 2021 and 2025, and `calendar.txt` and `calendar_dates.txt` stay apart. Run it after touching
the matcher.

**A facet must describe the rows a user can actually get back.** The SOEP dataset dropdown listed
all 622 datasets while the raw questionnaire files were hidden by default, so 547 of the options
filtered every hit away. `/api/soep/filter-options` now takes `include_raw` and the UI passes its
checkbox state. Same class of bug as the `dataset_scope` one: correct API, wrong scope.

**Two acquisition traps worth remembering.**
1. *DB API Marketplace needs two headers.* `DB-Client-Id` AND `DB-Api-Key`. Sending only the key
   (or the same value twice) answers `401 Invalid client id or secret`, which reads like a wrong
   key rather than a missing second one.
2. *Overpass is unreachable from this pod.* Every mirror (overpass-api.de, kumi.systems,
   private.coffee) answers **connection refused** at the TCP level, on IPv4 and IPv6, so it is an
   egress block, not a rate limit or a bad user agent. `taginfo.geofabrik.de/europe:germany` gives
   the same per-tag counts for Germany over a documented JSON API and IS reachable, so the counts
   come from there and the Overpass query stays in the record as the recipe a user runs themselves.

**Geodatenkatalog.de (GDI-DE) is a working CSW catalogue and the fallback for JS-only portals.**
`gdk.gdi-de.org/gdi-de/srv/eng/csw?service=CSW&request=GetRecords...&constraint=AnyText%20like%20%27%25bodenrichtwert%25%27`
returns Dublin Core summaries (1,962 matches for Bodenrichtwerte, 89,580 for Fläche). It is how
BORIS-D coverage was evidenced without any portal of its own. Note the element name carries
attributes (`<csw:SummaryRecord xmlns...>`), so a regex for `<csw:SummaryRecord>` silently matches
nothing.

**A two-column PDF needs word coordinates, not a character offset.** The BA Gesamtglossar is a
term/definition table whose column boundary MOVES between pages (measured at columns 23, 26 and 30)
and whose long terms wrap onto further lines. A fixed `line[:30]` split produced 1,131 records of
which 768 were fragments ("verm", "rese", "01.1"): plausible-looking rows, no error, and the labels
are exactly what the embedding sees. `pdftotext -bbox-layout` gives per-word x/y, so the column
split is measured per page from the two dominant line-x clusters. Two further traps behind it:
`-bbox-layout` blocks are NOT table cells (they merge greedily down a column, so a block-level parse
silently glued three rows' terms together), and a wrapped term is only recognisable lexically, since
gap size alone is ambiguous: it sits one line-height below (~12pt vs ~15pt+ between rows) AND
continues the line above it (trailing hyphen, lowercase start, dangling preposition, unclosed
bracket). Sanity-check any PDF flattener by printing labels and asking whether each reads as a term.

**Two bugs worth remembering, both invisible to API-level testing.**

1. *The UI sent the deployment mode as the source filter.* `dataset_scope: isAll ? snapshot : mode`
   in the request builder hard-filtered every GeoDB query to `source_key="inkar"`, so 20 of 21
   sources were unreachable through the browser while every API call I made by hand worked. Test
   the payload the UI actually sends, not just the endpoint.
2. *Half the statistic-level links pointed at the wrong database.* The statistic codes mined from
   the Destatis definition text are not all carried by the REGIONAL database: of 965, only 429
   exist there, 468 are federal-only and 68 in neither. They are now resolved against the
   enumerated catalogues and linked to whichever instance holds them.

**Seven sources added on 2026-09-06**, the gaps a keyword pass over the whole index had shown:
Geobasisdaten des BKG (70 products, and the first geometries in the index: VG250/VG1000/VG5000,
NUTS, the INSPIRE grid, CLC5 land cover), the FDZ of the statistical offices (75 datasets) and the
FDZ of the BA at the IAB (34 products), the Marktstammdatenregister (31 entity types read from the
XSD schemas that ship with its export documentation), the UBA air quality interface (12 components
plus the 500-station register), the Polizeiliche Kriminalstatistik (13 published parts) and
Mobilität in Deutschland (the four waves, the BASt table tool and the microdata route). All of
them are dataset-level links that resolve; `check_geodb_links.py` reports ok for each.

Two things learned there. The BKG shop is client-rendered and its robots.txt asks GPTBot to stay
out, while its open **data server** is a plain directory listing with no robots.txt: the catalogue
was taken from the data server with an honest user agent and the shop was left alone. And the
workbook comment for the UBA row originally promised the Umgebungslärm mapping, which no record
covers because that mapping belongs to the sixteen Länder; the comment was corrected rather than
left to overstate what the index holds.

**Where the links land, after the pass of 2026-09-05** (11,376 records): 5,332 open the table,
2,713 the dataset or file that contains the record, 1,668 the statistic that contains it, **1,470
the exact indicator** and 193 a portal to search from. The pass moved 642 records up to indicator
level and 22 off the portal, and it is worth knowing which sources still sit at portal level and
why: INKAR (660, in the other index, see above), 193 GeoDB records made up of one card per source
plus the Merkmale that exist in neither GENESIS instance, and five workbook rows that are search
masks without an export (playgrounds and physicians, where OpenStreetMap is the systematic
alternative and is indexed).

Sources checked in that pass and left alone, so nobody re-does the work: the DB Infrastrukturregister
viewer is MapStore2 and takes no layer parameter, the Unfallatlas and the G-BA search are
client-rendered shells, and the three BA report series already link one address per series, which
is the level those records describe. The BA glossary moved from one address for all 313 terms to
its 24 letter pages, Breitband from the portal front door to the download page (with the exact
file, sheet and column in `api_hint`), BORIS-D from 14 to 16 Länder (Baden-Württemberg and Berlin
publish outside the national catalogue and were verified by hand), and Migration/Integration got
the 18 of its 140 columns that the Destatis map offers as a view of its own.

**The facet audit earns its place after every batch of new sources (2026-09-06).** Adding seven
sources broke three things that no link check would have caught, because the links were fine and
the facets were not:

- `map_spatial` takes a **list** of workbook level labels. The MiD flattener handed it a single
  string, so it iterated over the characters, matched nothing, and all seven records came out with
  only the "Weitere Gliederungen" that is appended afterwards. Every one of them was invisible to
  the level filter.
- The 70 BKG products carried **no year at all**, because the product code names the Gebietsstand
  day (_0101, _1231) and not the year. The directory listing has the date, so the fetcher keeps it
  now and the year comes from the code where it has one (clc5_2018) and from the folder otherwise.
- The PKS records stopped at Bundesländer although the statistic is published for districts, and
  the audit found eleven records whose own text says Kreise.

`scripts/audit_geodb_facets.py` reported all three. Its output needs reading rather than obeying:
most of what it flags is a record whose prose mentions a level it is not published at, which is
correct as it stands. Grid cells are the sharpest example: a statistical grid and an elevation
model belong in the Rasterzellen facet, a raster map does not, and only the first two got it.

The filter path itself was checked against the running service the same day: every facet offers
the new sources, source, level, year, theme and combinations all hold, and a record without a year
is not dropped by a year range, which matters for the 3,105 records (glossary terms, data formats,
GENESIS Merkmale) that have no reference year by nature.

**Link health is audited, not assumed.** `scripts/check_geodb_links.py` samples records per source,
fetches the outward link, and compares the response against what that host returns for a
deliberately invalid code. That is what separates "the table opened" from "the portal home page
opened". Current result: **no broken links**; the only non-ok verdicts are the client-rendered
portals (Regionalatlas, federal GENESIS, Zensus). deutschlandatlas.bund.de used to be in that
group and no longer is: with a cookie jar its map pages verify normally (a real map answers 200
with about 124 KB, a bogus code 404 with 96 KB). Records whose link cannot be probed carry
`link_verified: false`, the UI marks them with an asterisk, and the checklist counts them.
Regionalatlas belongs in that group: it is a dojo/ArcGIS app that reads TCode/ICode client-side,
so its "indicator" links cannot be verified from here, and an earlier claim that they were is
wrong.

**A portal with no catalogue is often a portal whose own viewer has one (IÖR, 2026-09-05).** The
IÖR-Monitor was indexed at portal level: 88 indicators read out of a PDF, all 88 pointing at the
same overview page, on the reasoning that the documented API (`monitor_api/user?id=...&service=wms`)
needs a personal key. The key is needed to CALL the geodata services, and for nothing else. The map
viewer at monitor.ioer.de keeps its entire state in the query string and talks to an
unauthenticated endpoint: `POST backend/query.php` with
`values={"format":{"id":"gebiete"},"query":"getAllIndicators"}` returns every indicator with unit,
years, spatial levels and description text, and `?ind=<code>&raumgl=<level>` opens exactly that
indicator. So the source went from 88 identical links to 91 indicator-level ones, with real units
and per-indicator years and levels. Three things generalise:

- **Read the app, not the documentation.** The parameter names came from the viewer's own JS
  (`frontend/src/menu_indikatorauswahl.js` declares `paramter: 'ind'`), and the catalogue endpoint
  from `RequestManager.js`. A portal that renders client-side has to fetch its own metadata from
  somewhere, and that somewhere is usually open.
- **Name no year in a deep link when the app defaults to the newest.** The viewer picks the newest
  year an indicator has when the link carries none, so the links do not age between refreshes.
- **A field can be true in one catalogue and meaningless in another.** The raster catalogue marks
  all seven area levels for every indicator, but the six indicators that exist only there render an
  empty map at `&raumgl=krs`. Which catalogue an indicator appears in decides its link and its
  levels; `spatial_extends` is only believed on the area side. Checked in a browser, not assumed.

**Three ways a link check lied in one afternoon (2026-09-05).** The question was simple: which of
2,439 GENESIS Merkmale have a page of their own, so their record can link to the Merkmal instead of
to the statistic that contains it. Getting an answer that survived checking took three attempts,
and every wrong answer looked like a good one.

1. **Six parallel fetches of the portal page** reported 2,268 hits. The Regionalstatistik portal
   keeps the current selection in server-side state, so concurrent requests from one client bleed
   into each other and each answer is a perfectly normal page for the wrong code. A browser sample
   of fifteen found twelve empty.
2. **Sequential fetches, deciding by the absence of the "keine Objekte" phrase**, reported 1,704.
   Absence of a failure is not evidence of success: over a long run the portal also returns error
   and session pages, and after about 1,700 requests it began doing so. The truth anchors added
   after attempt 1 caught this at the end of the run, when they came back 5/10.
3. **The documented API** (`catalogue/variables?selection=<CODE>` on the Regionaldatenbank, with
   the token) answers the same question in six minutes: **624**. It agrees with every one of the
   ten hand-checked codes, and it puts no load on the public UI, which attempts 1 and 2 had been
   hammering with about 6,500 requests.

What to carry: **a positive has to be positive evidence** (the page names the code and carries a
non-empty Inhalt line), **hold every probe against a small hand-verified truth set before and
after the run** (`TRUTH` in `scripts/resolve_merkmal_pages.py`, which aborts rather than produce a
plausible lie), and **when a service has an interface for the question, ask it there** instead of
reading its HTML. A stateless service is still fine to probe in parallel: the IÖR link check runs
five browsers at once because monitor.ioer.de holds no per-client state.

The same API call also showed the labels had drifted. These Merkmale come from a 2020 Datenguide
snapshot, and 116 of the 624 read differently in the database today, a few in substance: BEV012 is
"Sterbefälle je 1 000 Einwohner" now rather than Wanderungssaldo, and two rates changed their
denominator from 10.000 to 1.000 Einwohner. The records now carry the live wording and keep the old
one as an alias. One eval query then "regressed" because its pattern `pendl` no longer matched the
official "Einpendelnde über Gemeindegrenze"; the answer was right and the test had aged.

Also worth remembering: **a build that reads a file another job is still writing gets a partial
answer without an error.** The first rebuild after starting the resolver picked up its half-written
output and produced link counts that were neither the old nor the new state.

**INKAR is linked through an endpoint of ours, because it has no address of its own (2026-09-06).**
The project has its own arrangement with the BBSR and its scope is not written down; Konstantin
decided to build the deep links anyway rather than wait months for that to be settled, so this is a
decision on the record, not a cleared permission. Treat it as such: no series of automated requests
against the application, no scraping, and nothing written to their server beyond what a reader
actually asks for.

The mechanics follow from that. inkar.de keeps no state in its address (its table and map windows
read the selection from the window that opened them), and the one thing a URL carries is the id of
a query **stored on the BBSR server**. Writing all 660 up front would leave 660 rows there for
indicators nobody may ever open, so the records link to
`geodb.geolab.soz.uni-bielefeld.de/api/inkar/open/<M_ID>` instead: that endpoint creates one stored
query the first time an indicator is opened, remembers it, and redirects. 654 of 660 indicators are
reachable this way; the six left are the ZOM classification variables, which the wizard does not
offer as indicators.

Three details worth keeping:

- **INKAR uses two identifiers and they are not interchangeable.** The workbook's `M_ID` is what the
  application's time selection calls `indicator`; its catalogue uses `Gruppe`, a different number
  (1101 vs 12 for Arbeitslosenquote). Only 11 of 660 coincide. Mixing them up produces a query that
  saves happily and then loads forever, because `Table/GetDataTable` answers 400.
  `scripts/fetch_inkar_wizard_catalogue.py` joins the two catalogues by name within a theme block,
  which is unambiguous because our four workbook sheets have exactly the sizes of the
  application's four area groups (413 / 109 / 89 / 43).
- **The query shape came from the application, not from guessing.** Driving the wizard once in a
  browser and reading `getSelections()` before it closes itself is what settled the field names
  (`visited`, the id in `TimeCollection.indicator`) after a hand-built version had failed silently.
- **It is reversible in one command.** `scripts/inkar_permalinks_admin.py --delete-all` removes
  every query we created; `GEOLAB_INKAR_PERMALINKS=0` turns the endpoint off and every link falls
  back to the portal. The weekly health check samples the stored queries, because if the BBSR ever
  purges them our links would fail silently otherwise (the redirect still answers, the target is
  gone). A missing one is not an outage: the next click recreates it.

**A portal with no catalogue is often a portal whose own viewer has one (IÖR, 2026-09-05).** The
IÖR-Monitor was indexed at portal level: 88 indicators read out of a PDF, all 88 pointing at the
same overview page, on the reasoning that the documented API (`monitor_api/user?id=...&service=wms`)
needs a personal key. The key is needed to CALL the geodata services, and for nothing else. The map
viewer at monitor.ioer.de keeps its entire state in the query string and talks to an
unauthenticated endpoint: `POST backend/query.php` with
`values={"format":{"id":"gebiete"},"query":"getAllIndicators"}` returns every indicator with unit,
years, spatial levels and description text, and `?ind=<code>&raumgl=<level>` opens exactly that
indicator. So the source went from 88 identical links to 91 indicator-level ones, with real units
and per-indicator years and levels. Three things generalise:

- **Read the app, not the documentation.** The parameter names came from the viewer's own JS
  (`frontend/src/menu_indikatorauswahl.js` declares `paramter: 'ind'`), and the catalogue endpoint
  from `RequestManager.js`. A portal that renders client-side has to fetch its own metadata from
  somewhere, and that somewhere is usually open.
- **Name no year in a deep link when the app defaults to the newest.** The viewer picks the newest
  year an indicator has when the link carries none, so the links do not age between refreshes.
- **A field can be true in one catalogue and meaningless in another.** The raster catalogue marks
  all seven area levels for every indicator, but the six indicators that exist only there render an
  empty map at `&raumgl=krs`. Which catalogue an indicator appears in decides its link and its
  levels; `spatial_extends` is only believed on the area side. Checked in a browser, not assumed.

**Three ways a link check lied in one afternoon (2026-09-05).** The question was simple: which of
2,439 GENESIS Merkmale have a page of their own, so their record can link to the Merkmal instead of
to the statistic that contains it. Getting an answer that survived checking took three attempts,
and every wrong answer looked like a good one.

1. **Six parallel fetches of the portal page** reported 2,268 hits. The Regionalstatistik portal
   keeps the current selection in server-side state, so concurrent requests from one client bleed
   into each other and each answer is a perfectly normal page for the wrong code. A browser sample
   of fifteen found twelve empty.
2. **Sequential fetches, deciding by the absence of the "keine Objekte" phrase**, reported 1,704.
   Absence of a failure is not evidence of success: over a long run the portal also returns error
   and session pages, and after about 1,700 requests it began doing so. The truth anchors added
   after attempt 1 caught this at the end of the run, when they came back 5/10.
3. **The documented API** (`catalogue/variables?selection=<CODE>` on the Regionaldatenbank, with
   the token) answers the same question in six minutes: **624**. It agrees with every one of the
   ten hand-checked codes, and it puts no load on the public UI, which attempts 1 and 2 had been
   hammering with about 6,500 requests.

What to carry: **a positive has to be positive evidence** (the page names the code and carries a
non-empty Inhalt line), **hold every probe against a small hand-verified truth set before and
after the run** (`TRUTH` in `scripts/resolve_merkmal_pages.py`, which aborts rather than produce a
plausible lie), and **when a service has an interface for the question, ask it there** instead of
reading its HTML. A stateless service is still fine to probe in parallel: the IÖR link check runs
five browsers at once because monitor.ioer.de holds no per-client state.

The same API call also showed the labels had drifted. These Merkmale come from a 2020 Datenguide
snapshot, and 116 of the 624 read differently in the database today, a few in substance: BEV012 is
"Sterbefälle je 1 000 Einwohner" now rather than Wanderungssaldo, and two rates changed their
denominator from 10.000 to 1.000 Einwohner. The records now carry the live wording and keep the old
one as an alias. One eval query then "regressed" because its pattern `pendl` no longer matched the
official "Einpendelnde über Gemeindegrenze"; the answer was right and the test had aged.

Also worth remembering: **a build that reads a file another job is still writing gets a partial
answer without an error.** The first rebuild after starting the resolver picked up its half-written
output and produced link counts that were neither the old nor the new state.

**INKAR is a special case with an agreement behind it, so ask before acting on it.** The project
has its own arrangement with the BBSR over INKAR, and its scope is not written down here because it
is not yet known: Konstantin is checking with his boss what it does and does not allow (open as of
2026-09-05). Until that answer exists, treat INKAR as read-only in the strongest sense: **do not
write anything to a BBSR server** (no stored queries via `Main/SaveQuery`, which is what a
per-indicator link would require), do not run series of automated requests against the application,
and do not scrape it. Reading the public catalogues, the workbook, the WMS and the CSW is not
affected and is what the current records are built from. When the answer comes, it may well widen
what is possible, including a supported way to link single indicators, so this is worth revisiting
rather than closing.

**And sometimes the app really has no address for its content (INKAR, 2026-09-05).** The same
search was run against INKAR, the largest portal-level block in either index at 660 indicators, and
the answer is no. `www.inkar.de` is an ASP.NET application: its table and map windows read the
selection from the window that opened them, and the start page reads exactly one thing from its
address, the id of a query stored on the BBSR server (`location.hash` -> `Main/GetUserQuery/<id>`).
The BBSR's own map viewer at bbsr-geodienste.de reads no URL parameters at all. A per-indicator link
would therefore mean writing 660 stored queries into a federal agency's database. `Main/SaveQuery`
does accept an anonymous POST (one probe was created, opened from a clean browser and deleted again),
so it is possible; it is a decision for Konstantin and for the BBSR, not a technical question, and
nothing of the sort was done.

What the search did turn up is that about 80 of the 660 indicators are published as WMS layers and
as metadata records that all resolve in the national Geodatenkatalog, one page per indicator.
`scripts/fetch_inkar_geodienste.py` collects them, and the builder attaches the layer name and the
catalogue page to the matching records. They keep inkar.de as their link, because that is where the
numbers are; the addresses ride along in `api_hint`, and every INKAR record now also carries the
theme path so the reader knows where to look in the wizard. The embedding text is untouched by all
of this, which is why the INKAR vectors did not need rebuilding.

Because monitor.ioer.de answers the same 4.7 KB shell for any query string, `check_geodb_links.py`
reports these as `shell` (correctly: it cannot judge them). `scripts/check_ioer_links.py` is what
verifies them, by reading the map header the app writes once the indicator has loaded; all 91
passed on 2026-09-05 and `refresh_all.sh` runs it as step 3c.

**Every record carries `link_level`** (how precisely the link lands) and `link_verified` (whether
that was probed). Improving the portal share and the unverified share is the quality lever.

**Crawl instances in parallel, never within one instance.** Regionalstatistik, federal GENESIS and
Zensus are separate hosts with separate tokens and separate rate limits, so three concurrent
`fetch_genesis_catalogue.py` processes are fine and each writes its own file. Inside one instance
stay sequential: the services cap parallel requests (Destatis says 3, Regionalstatistik 10) and
kill long-running ones. Runtimes measured here: regionalstatistik 129 statistics / 866 tables in
about 20 min, federal 331 / 3,026 in about 50 min, Zensus 12 / 1,440 in about 20 min.

**Adding a source that is not in the workbook means adding a workbook row**, not a special case:
`build_source_registry.py` asserts the expected count (`EXPECTED_SOURCES`, currently 36) and
derives folder numbering from row order, so Unfallatlas, GENESIS-Bund and Zensus each got a blue
row in `Tabelle1` and their own `data_sources/<NN>-<slug>/` folder. **Reordering sources reorders
the records, which silently invalidates the embedding cache** (it matches on row count only), so
always re-embed after adding or moving a source, never only after changing content.

**`data_sources/CHECKLIST.md` is the per-source tracker** and is generated, never hand-edited:
`scripts/build_status_report.py` reads the registry, each `raw/` folder, the built metadata and a
live link check, then writes the checklist, a blue-marked English `Status_GeoDB` sheet appended to
`Geospatial_Data_Sources.xlsx`, the German handoff table (CSV/PDF/PNG) and a dated German copy of
the whole workbook in `deliverables_geodb_datenquellen/` (`..._GeoDB_Stand_<date>.xlsx`, one
German `Stand_GeoDB` sheet instead of the English one). The copy is what gets handed over; the
working file keeps moving, and the untouched original stays as `Geospatial_Data_Sources_orig.xlsx`;
all three workbooks are git-ignored, the public facts live in `registry/geo_sources.json` instead.
The German table render needs `LD_LIBRARY_PATH` pointing at the rstats env, otherwise TinyTeX dies
on `libfontconfig.so.1: cannot open shared object file`, which reads like a broken LaTeX install.
Per-source state lives in that script's `OPEN_ITEMS`, candidate new sources in its `CANDIDATES`.

`scripts/eval_geodb_search.py` is the retrieval smoke test: 28 concept queries with an expected hit,
reporting hit@1/@3/@10. Baseline 2026-08-25 with e5-large-instruct + bge-reranker-base:
**hit@1 52/58, hit@3 57/58, hit@10 58/58, no misses** (2026-08-27, on the widened 58-query set
that includes English phrasing and cases where an indicator must beat a portal card; the earlier
28-query set scored 27/28). Run it after any change to the model, the document construction, or
the record set, and compare against that baseline before deploying.

Acquisition is scripted: `scripts/fetch_sources.py` holds a `FETCH_PLAN` (one entry per
artifact, keyed by slug) and a `MANUAL` dict naming the sources a script cannot reach and why.
It writes provenance (url, status, bytes, sha256, timestamp) into each `raw/FETCH_LOG.json`, and
`--report` prints what is present against what is planned. Add a source by adding a plan entry,
never by curling by hand.

What acquisition turned up (2026-08-25), worth knowing before re-deriving it:

- **Regionalatlas serves its whole catalogue as static JSON.** `/taskrunner/services.json`
  (21 themes, 217 indicators, years to 2026) is current; `/app/json/services.json` is a stale
  copy. Each indicator carries a `meta` wiki-text with Aussage, Indikatorberechnung and
  Herkunftsstatistiken, so no LLM enrichment is needed. `/app/csv/thesaurus.csv` (Latin-1) adds
  hand-curated German synonyms per indicator. Per-indicator deep link:
  `?BL=DE&TCode=<TCode>&ICode=<ICode>&Jhr=<year>`.
- **Datenguide's metadata outlived the portal.** `github.com/datenguide/genesapi-data` holds
  5,514 JSON files covering ~2,757 GENESIS/Regionalstatistik Merkmale in German and English,
  many with the full Destatis definition. The repo is ~65 MB of mostly CSV, so the fetcher keeps
  only `keys/` and `src/*.yaml` and discards the archive.
- **BA files are directly linkable** at
  `/Statistikdaten/Detail/<YYYYMM>/<unit>/<topic>/<file>-xlsx.xlsx?__blob=publicationFile&v=1`
  once the `;jsessionid=...` is stripped. One booklet defines the indicator set for a whole
  series, so there is no reason to download per-region files.
- **inkar.de serves an incomplete certificate chain**, so that one artifact is fetched with
  verification off, declared per-artifact in the plan and never as a global default.
- **deutschlandatlas.bund.de needs a cookie jar, not a browser.** It answers **307 to a
  cookie-check URL** and serves the page to any client that keeps the cookie and follows the
  redirect (`urllib.request.HTTPCookieProcessor`, or `curl -L -c jar -b jar`). Without one it
  looks like a hard failure, and this file recorded it for two days as "400 to every scripted
  request", which is wrong. The consequence was real: 86 Deutschlandatlas records sat at
  dataset level and the map index at `/DE/Karten/_node.html` (122 map pages) went unread. When a
  federal portal looks unreachable, check the redirect chain and the cookies before concluding
  a browser is required.
- **The G-BA and Klinik-Atlas data are indexed by schema, not by row.** The Qualitätsberichte
  archives are ~1.7 GB uncompressed per year, one XML per hospital; the flattener reads the section
  structure out of the largest report in the newest archive and never extracts the rest. The same
  logic applies to any register: index what the register *records*, not its rows.
- **GENESIS tokens are per instance, and `Bearer` silently degrades to guest.** Regionalstatistik
  (`www.regionalstatistik.de/genesisws/rest/2020/`) and the federal GENESIS
  (`genesis.destatis.de/genesisWS/rest/2020/`) need separate registrations; a token from one
  answers `Bitte geben Sie Ihr Passwort ein` on the other. `Authorization: Bearer <token>` returns
  HTTP 200 from `helloworld/logincheck` on both, but as `"Username":"GAST"`, and every catalogue
  call then 401s. Only the `username` header with an empty `password` authenticates, and any
  enumerator must assert `Username != GAST` before writing a file.
  `scripts/fetch_genesis_catalogue.py` does this. Tokens live in `~/kwandel/.config/secrets/`.
- **Table code is the finest linkable unit in Regionalstatistik.** `?operation=table&code=<code>`
  opens exactly that table (verify against a deliberately bogus code: 25 KB vs 8.5 KB). The newer
  `/datenbank/online/...` SPA paths return a 3 KB shell, so keep the `/genesis/online?operation=`
  form. The regional depth is written into the table title ("regionale Tiefe: Kreise und krfr.
  Städte"), which is how the flattener tags spatial levels.
- **The Regionalstatistik portal cannot be deep-linked by query parameter for anything else.** It is a JSF app:
  `?operation=merkmal&code=BEV001` and every variant of it silently return the homepage. The one
  pattern that works is `/genesis/online/statistic/<5-digit statistic code>`, and the statistic
  code has to be mined out of the Destatis definition text ("Erläuterung für folgende
  Statistik(en): 12612 ..."). 965 of the 2,756 Merkmale get a real deep link that way; the rest
  link to the portal entry with the code in `api_hint`. Verify a link pattern by comparing the
  response against a deliberately bogus code before trusting it.

Design decisions already taken:

- Every record carries a **working outward link** and a licence-safe description. A record without
  a link is not shippable; the link is the product, and `build_geodb_metadata.py` fails the build
  if any record lacks one.
- Portals that are only a search UI over a register (physician search, station finder, playground
  map) still get **one well-written portal-level record** each, so a concept query routes there.
  Volume is not the goal; coverage of the concept space is.
- Discontinued portals stay indexed with an explicit "no longer updated" flag, because the
  historical data remains citable.
- `Geospatial_Data_Sources.xlsx` is the input, never the served artifact. Everything downstream
  comes from `scripts/build_source_registry.py`, which asserts the expected source count so a
  changed workbook fails loudly rather than producing a partial registry.

## Refreshing the index, and the "as of" date

`SOEP_RAG_CACHE_DIR` must be set outside the container. The service defaults its cache to
`/app/cache`, which exists only in the deploy image, so a script that loads the advisor on this box
dies with `PermissionError: /app` at `load()`. `refresh_all.sh` sets it; any new script that calls
`SOEPRagAdvisorService().load()` has to as well.

`bash scripts/refresh_all.sh` is the whole chain in one command: fetch what is public, rebuild,
re-embed on the GPU, run the retrieval gate, deploy, regenerate the tracker. `--no-deploy` stops
before the VM. The build writes `soep_metadata_output/geodb_build_info.json`, the advisor exposes
it as `index_built`, and the UI prints "index as of <date>", so a stale index is visible to a user
rather than only to us.

**The refresh is a manually started Claude session (decided 2026-08-27).** Konstantin wants the
refresh to be a session that reasons about what changed rather than a blind cron job: check each
source for a new edition, re-fetch, rebuild, re-embed, run the gate, deploy, regenerate the
tracker. It is started by hand; nothing is scheduled. The mechanics below are still why.

**Scheduling it automatically is the unsolved part, and not for want of trying.** This box is a pod: `/etc/cron.d`
is wiped on restart and there is no user systemd, so a cron entry here does not survive. The real
options are running the script by hand after a source publishes, a scheduled Claude session, or a
systemd timer on the geolab VM at the cost of embedding on 4 CPU cores instead of the H200.

## Why SOEP needs no LLM enrichment any more

The old corpus had German-only labels, so generated English text was the only way to make an
English query work. v41 ships an official label in both languages for ~100% of variables, a topic
path for 63,110 and the real survey question wording for 44,912. Measured on 2026-08-27: of the
23,855 variables visible by default, **1,971 have no topic, no question text and no value labels**,
and inspection shows those are mostly self-describing identifiers ("Geburtsmonat" / "Month Of
Birth", "Jahr/Erhebungsjahr"). Generating prose for them would add words, not information, and
would risk inventing meaning for a variable whose label is already the authoritative wording. So
enrichment was dropped rather than run.

## Unattended follow-up work

Long jobs run detached and finish themselves. Two conventions make that safe:

- **The crawler is resumable and asserts its auth** (`scripts/resolve_zensus_levels.py`,
  `scripts/fetch_genesis_catalogue.py`): an existing output file is loaded first and only the
  missing keys are fetched, and a run that authenticated as GAST refuses to write anything.
- **The follow-up is gated, backed up and reversible** (`scripts/autopilot_zensus_followup.py`):
  it waits for the crawler to exit, measures retrieval on the current index, rebuilds and
  re-embeds, measures again, and **refuses to deploy if hit@1 dropped by more than 2** or if the
  record count moved by more than a quarter. It copies what it overwrites into
  `/opt/geolab/backups/autopilot_<stamp>/` and rolls back if the health check fails. Outcome in
  `logs/autopilot_result.json`, narrative in `logs/autopilot.log`.

Start them with `setsid ... </dev/null >>logs/<name>.log 2>&1 &` and verify with
`ps -o pid,ppid,sid,tty -p <pid>`: own SID, no TTY, ancestor chain reaching pid 1. A job whose
parent is the agent dies when the session does.

**A waiting process must log a heartbeat.** The first autopilot logged only its start line and
then slept in a two-minute poll loop. It died mid-wait on 2026-08-25, and because nothing was
written after the start line there was no last-seen time and no traceback: impossible to tell a
kill from a still-running sleep, and the box had not restarted (17 days up) while the crawler it
was waiting for survived. It now logs every fifth poll and rewrites `logs/autopilot_alive.json`
on every one, so a later session can see when it last breathed. The work itself was not lost,
because the crawler's output was complete and every following step is idempotent, which is the
other half of the pattern: make the long job resumable and the follow-up re-runnable, then a
silent death costs a re-run rather than the work.

## Deploying a metadata update

```bash
# 1. rebuild + re-embed locally (GPU), 2. stage, 3. install, 4. restart, 5. verify
rsync -az soep_metadata_output/{geodb_metadata.json,geodb_rag_embeddings.npy,inkar_rag_embeddings.npy} \
      backend/app/services/soep_rag_advisor.py vm:~/geodb_stage/
rsync -az --delete frontend/dist-inkar/ vm:~/geodb_stage/site_inkar/
ssh vm 'sudo install -o geolab -g geolab -m 664 ~/geodb_stage/<file> /opt/geolab/app/destatis-rag/soep_metadata_output/ ;
        # Everything but the bundles is replaced; the bundles are only ever added to.
        sudo rsync -a --delete --exclude "assets/**" ~/geodb_stage/site_inkar/ /opt/geolab/sites/inkar/ ;
        sudo rsync -a ~/geodb_stage/site_inkar/assets/ /opt/geolab/sites/inkar/assets/ ;
        sudo chown -R geolab:geolab /opt/geolab/sites/inkar ;
        sudo systemctl restart geolab-inkar geolab-soep'
```

**Never delete the old bundles.** They are a few hundred kilobytes each and they are what a browser
still holding an older `index.html` asks for. Deleting them turned every such visitor into a white
screen: `try_files` rewrote the missing bundle to `index.html`, the `@bundles` header applied to the
request path whether or not the file existed, so the browser stored an HTML document under the
bundle's address with `immutable, max-age=1y` and never asked again. Caddy now answers 404 for a
missing file under `/assets/` and marks only files that actually exist as immutable (the `file`
matcher, which needs `root` set at site level, not inside the `handle` blocks), and
`health_check.py` checks both directions weekly. Fixed and verified 2026-09-05; the old bundles of
both finders were restored from `/opt/geolab/backups/` at the same time, and an old document boots
and searches again.

`soep_rag_advisor.py` is **shared by both services** on the VM, so a backend change restarts the
SOEP finder too; check `soep-faiss.geolab.soz.uni-bielefeld.de` after every deploy, not only geodb.
Back up what you overwrite first (`/opt/geolab/backups/pre_geodb_20260825/` is the pre-GeoDB state:
the old advisor, the old `inkar_rag_embeddings.npy`, and the old inkar site).

## Serving the multi-source index

- `GEOLAB_ENABLE_GEODB=1` (default) loads `geodb_metadata.json` in the `inkar` and `all` modes;
  `GEODB_RAG_METADATA_PATH` overrides the path. The embedding cache is
  `geodb_rag_embeddings.npy`, matched by row count like every other cache (see the footgun below).
- The source dropdown is now **derived from the loaded rows**, so a new source appears by itself.
  Portal-level records all share `source_key="geoportal"` while keeping the portal's own name in
  `source_label`, which is why `get_filter_options` needs a fixed label for that one key.
- The UI's default `dataset_scope` in `inkar` mode is `all`, not `inkar`. Setting it back to the
  mode name would silently hide every new source behind the INKAR filter.
- Ranking is untouched: `_authority_delta` only applies its SOEP dataset prior to SOEP rows, and
  `_dedup_key` gives non-SOEP sources a `(source_key, code, label)` identity, because codes are
  only unique within a source (`AI0104` exists in both Regionalatlas and the GENESIS catalogue).

## The hard gate, and what it found (2026-08-29)

`scripts/eval_geodb_search.py` is a smoke test: most of its queries share a word with the label
they are meant to find. `scripts/eval_geodb_hard.py` is built so keyword overlap cannot decide
the case: concept-only questions, lay phrasing, English question against a German record, two
neighbouring concepts where naming the wrong one counts as a failure, constraints checked against
the record's own fields, bare code lookups, and five negative controls the index genuinely cannot
answer. Run it against the deployment, which is what a user meets:

    python scripts/eval_geodb_hard.py --api https://geodb.geolab.soz.uni-bielefeld.de/api

First run: 31 graded queries, hit@1 19, hit@3 28, hit@10 29, median 0.96 s. Three findings, in
order of how much they matter:

1. **The score cannot express "I have nothing".** All five impossible questions still produced a
   confident-looking top hit ("Anteil der Haushalte mit einem Balkon" -> "Eigentümerquote", fused
   score 0.83, higher than several correct answers). The cross-encoder score looked like the fix:
   on four hand-picked keyword queries it separated real from impossible by three orders of
   magnitude. Over all 36 queries it does not: conversational but perfectly answerable questions
   ("gibt es hier genug Kita-Plätze", correct hit at rank 1) score 0.0008, below every impossible
   one. So there is no usable abstention threshold in the current signals, and a "no good match"
   banner cannot be built from them without producing false alarms on exactly the phrasing the
   finder is for. Do not ship a threshold on the strength of a handful of easy queries.

2. **Grid records are not tagged as grid.** The Breitband raster rows say "(Gitterzelle)" in the
   label but carry `spatial_levels = [Weitere Gliederungen, Gemeinden, Kreise]`, so the spatial
   filter cannot reach them and "Breitbanddaten als Rasterzellen" fails the constraint even
   though the right record is rank 1. The fix belongs in the builder, not the ranker.

3. **Bare code lookup is luck.** `AI1401` lands on its record, `INT251` does not, though both
   codes sit in the indexed text and both records exist. The lexical signal only reweights
   candidates the dense stage already retrieved, so a code that the embedding does not place near
   its record is unreachable. An exact `variable_name` match pinned to rank 1 would settle it.

A note on writing cases for this file: two of the first cases passed for the wrong reason
("wie grün ist die Gemeinde" was answered with the Green party's vote share and accepted on the
word "grün"). Give a case a `reject` pattern whenever a pun or a neighbouring concept could
satisfy it.

**Where the three findings stand (2026-08-29).**

*Finding 1, the missing "I have nothing":* the negative set was grown from 5 to 27 queries, each
screened against the live index first (four candidates were thrown out because the finder answers
them: public toilets per station, sleep duration, screen time and housework are all in the index).
On five negatives the margin between the top hit and the median of the list looked decisive; on 27
it is merely useful, and the honest table at the deployment's own top_k of 12 is:

| threshold | answerable kept | impossible caught | false alarms |
|---|---|---|---|
| 0.005 | 29/31 | 12/27 | 6.5% |
| 0.015 | 26/31 | 18/27 | 16.1% |
| 0.050 | 21/31 | 23/27 | 32.3% |

Shipped at **0.015 as a note, never a filter**: nothing is hidden and nothing is reordered, and the
five answerable queries that trip it ("gibt es hier genug Kita-Plätze", "ist die Gegend eher arm
oder reich") genuinely have a flat field, so the sentence is true even when it is a false alarm.
The absolute cross-encoder score remains useless for this, for the reason below. `eval_geodb_hard.py`
reports the margin table on every run, so a ranking change that flattens the field shows up.

*Finding 3, bare code lookup, ended up narrow, in `_soep_code_rows`.* The wide version was worse
than the problem: a sentence containing a word which happens to also be a code pulled that record
up ("Wie funktioniert der Abruf der Daten" -> the record named `ABRUF`). What ships is gated three
ways, and all three matter: SOEP deployment only (GeoDB codes are internal to the statistical
offices and nobody types them), one-word query only (a code inside a sentence is a word), and the
token must not be a word of the corpus (so "Bevölkerung" keeps going through normal ranking). It
earns its place because the failure it removes is the bad kind: of twelve real SOEP codes typed
bare, seven landed and five returned a DIFFERENT variable one character away (`ple0179` "Wie oft
Fleisch" -> `plb0179` "Altersteilzeit"; `plh0182` -> `plh0162`), which reads as an answer. All
twelve now land on their own record.

*Finding 2 was fixed, and the audit that followed it lives in `scripts/audit_geodb_facets.py`.*
It looks for records whose own text names a spatial level their facets do not carry. Read its
output with the boilerplate in mind: 1,934 raw hits, of which only the 169 breitband raster rows
were real. Zensus and the breitband municipal workbook repeat a source-level sentence ("je nach
Merkmal bis auf Gitterzellenebene", "zusätzlich liegen Rasterdaten vor") on every record, which
says nothing about the individual row.

What the audit did turn up, and what was done with it:
  * 33 Zensus tables had no spatial level at all, because `resolve_zensus_levels.py` only looked at
    `Structure.Columns` and `Structure.Rows` while those tables carry GEOBL1/GEODL1 deeper in the
    structure. The resolver now walks the whole structure; 1,440 of 1,440 tables are resolved and
    the only records left without a level are the three portal cards, which have none by nature.
  * 3,086 records carry no year (2,440 Regionalstatistik Merkmale, 313 BA glossary entries, 246
    transit format descriptions). Left as is: for a glossary term or a data-format description
    there is no year, and `_passes_filters` only applies a year filter to rows that have both
    bounds, so nothing is silently dropped.
  * 15 sources carry one hard-coded level combination for every record. Left as is: some are simply
    true (`migration_integration` is Kreis-only), and for the BA glossary the levels describe where
    the defined statistic is published, which is what a user filtering by level wants to find.
  * Zensus grid tables are not indexed as their own records. Open, and a bigger job: the regional
    level sits in the table code, so it needs its own fetch pass. The raster rows now carry the
`Rasterzellen` level, which already existed for `ioer_monitor`, `dwd_cdc` and `fdz_ruhr` and was
missing only here (169 breitband rows changed, no other record touched, row count unchanged; the
embeddings had to be recomputed because `spatial_levels` are part of the embedded document and the
cache is matched by row count, so a stale vector would have been reused silently). Codes now reach
their record through `_exact_code_rows`: a query token that matches a `variable_name` exactly is
fetched directly and joins the candidate set, where the existing exact-code prior ranks it.

What counts as a code is decided by the data. The first rule required a digit and left `pglabnet`,
`sumkids` and every other digit-free SOEP name broken, so a token is now treated as a code when it
matches a `variable_name` AND never appears inside any record's label. "pglabnet" is in no label
and is pinned; "bevölkerung" is in thousands and keeps going through normal ranking. Building that
vocabulary costs 0.36 s once for the 125k-row SOEP corpus, the name index 0.56 s, both lazy.

After both fixes, on the deployment: hit@1 21 (was 19), hit@3 30 (was 28), hit@10 31 (was 29), no
misses at all (was two), negative controls unchanged. The standard gate went from 55 to 56 of 58
at rank 1 with no misses.

## Two ways in, always: the deep link and the source's entry page

A deep link into a statistical portal is the first thing that rots. The portal gets rebuilt, the
query string changes, and a perfectly good record turns into a dead end; the entry page of the same
source changes far more slowly. So every record carries a `portal_url` beside its own link, set in
one place in `build_geodb_metadata.py` (after the flattener runs, from the registry's `url`), and
the UI shows it as a quiet "Portal der Quelle" next to the main link. 9,838 of 11,377 records have
one; the rest are records whose own link already IS the entry page, where a second identical link
would be noise.

`PORTAL_OVERRIDES` exists because the registry records the address a source was catalogued under,
which is not always where a reader should be sent:
  * the Regionaldatenbank metadata came from the Datenguide project, so 3,138 records would have
    pointed at `datengui.de`, which is switched off,
  * the Deutschlandatlas was catalogued on one of its map pages rather than its entry page,
  * `breitband-monitor.de` no longer serves a valid certificate at all (SNI mismatch, confirmed in
    a real browser), and the Gigabit-Grundbuch is where that data lives now.

Check the fallbacks the way they were checked here: **in a browser, not with urllib**. Of the 19
distinct entry pages, plain `urlopen` flagged three, and two of those three (GENESIS-Online, the
Deutschlandatlas) are perfectly fine in Chromium and only refuse scripted requests. A link checker
that reports those as dead teaches people to ignore it.

## Handing a query over from the project site

The finder reads `?q=...` on load, asks it once, and strips the parameter from the address bar
(`SOEPRagAdvisor.jsx`). That is what lets a search box on the GeoLAB site drop a visitor straight
into a finished result list instead of an empty input, and it needs no JavaScript on the sending
side: a plain `<form method="get" action="https://geodb.geolab.soz.uni-bielefeld.de/">` with an
input named `q` is enough. The site's own navbar magnifier is Quarto's page search (33 sections of
site text) and never reaches the index, which is exactly the confusion the box removes.

A landing page carrying such a box is staged, unlisted, at
`https://geodb.geolab.soz.uni-bielefeld.de/preview-home.html`; its source is
`geolab_regiohub/_preview/` (regenerate with `_preview/make_preview.py`). The site build ignores
`_preview/`, so it cannot publish itself by accident.

Frontends are built with the `nodejs` env, which is not on PATH by default:
`PATH=$HOME/miniconda3/envs/nodejs/bin:$PATH VITE_APP_MODE=inkar VITE_PAGE_TITLE="GeoDB Geodata
Index" node node_modules/.bin/vite build --outDir dist-inkar --emptyOutDir` (and `soep` /
`dist-soep` / "SOEP Variable Finder" for the other). The live sites before the handover are kept
in `/opt/geolab/backups/pre_qhandover_20260829/`.

## Branding

The site is a Universität Bielefeld / Leibniz-Gemeinschaft project and says so: page title
"GeoDB Geodata Index", Uni Bielefeld favicon (`frontend/public/brand/`), and both logos in a
footer strip. The two SVGs were rebuilt with `fill="currentColor"` so they stay legible in the
dark theme; they are served from the site itself, never hotlinked. Header wording is "GeoDB",
never "INKAR", since INKAR is now one source among many.

## Repository layout

```
backend/app/main.py                       FastAPI routes (/api/soep/advice is the real one)
backend/app/services/soep_rag_advisor.py  THE service: load, embed, retrieve, rerank, fuse, filter
backend/app/services/search.py            legacy Destatis-table search, off by default
frontend/                                 React/Vite UI; VITE_APP_MODE picks the mode
scripts/build_inkar_metadata_index.py     INKAR workbook -> records + embeddings + FAISS
scripts/build_source_registry.py          Geospatial_Data_Sources.xlsx -> data_sources/ registry
data_sources/                             drop folder for the new sources (see its README)
soep_metadata_output/                     metadata JSON + .npy embeddings + .faiss (git-ignored)
deploy/                                   container stacks; the VM runs systemd instead
```

## Sibling repo: keep the two in sync

The same code is published twice, scoped to one finder each, with separate Zenodo DOIs:

- this checkout, `/home/researcher/kwandel/destatis-rag`, pushes to `KonstantinWandel/geolab-finder`
- `/home/researcher/kwandel/soep-variable-finder` pushes to `KonstantinWandel/soep-variable-finder`

A backend change belongs in both, as two commits with the same content. Check the other checkout
before assuming a fix is shipped. GitHub token is in `~/.config/gh/hosts.yml`; push with the token
in the URL and never print it.

## Production deployment (the geolab VM, not this box)

`ssh vm` (129.70.40.104, user `kwandel`). No Docker there; systemd runs uvicorn directly.

- code + data: `/opt/geolab/app/destatis-rag`, venv `/opt/geolab/.venv`, HF cache `/opt/geolab/hf_cache`
- embedding cache: `/opt/geolab/cache` (`SOEP_RAG_CACHE_DIR`)
- built frontends: `/opt/geolab/sites/{soep,inkar,germaparl}`, served by Caddy (`/etc/caddy/Caddyfile`)
- services: `geolab-soep` on 127.0.0.1:18001, `geolab-inkar` on 127.0.0.1:18002
- model overrides live in systemd drop-ins, e.g. `/etc/systemd/system/geolab-inkar.service.d/e5.conf`
- `/opt/geolab/CLAUDE.md` on the VM holds the deployment notes, including the open TLS item
  (the cert is Let's Encrypt staging and `*.soz` does not cover the `.geolab.soz` names)

Capacity: 4 vCPU, 15 GB RAM, CPU only.

**Query latency, measured and tuned 2026-08-29: about 1.7 s for a new query and 1.15 s for a
repeat, down from 6.7 s (GeoDB) and 8.4 s (SOEP).** Profile a query before optimising it: the
first two guesses here were both wrong. The dense product, the obvious suspect, is 1 ms for GeoDB
and 24 ms for SOEP. What the time actually went on:

1. *The cross-encoder, and its cost scales with document length.* 16 real documents rerank in
   12.9 s untruncated, 4.6 s at 800 characters, 2.1 s at 400, 1.2 s at 256. Documents here are
   median 510 characters with a p90 of 2,895, so a few long ones set the pace for every query.
   The rerank document is now cut to `SOEP_RAG_RERANK_DOC_CHARS` (480), front-loaded so name,
   label and theme survive whole and only the description is trimmed.
2. *A per-query filter pass that also COPIED the embedding matrix.* `_search` rebuilt a Python
   row list over all 125,496 SOEP rows and then fancy-indexed the embeddings, about 100 MB copied
   per request under the default filters. Both are cached per filter signature.
3. *`OMP_NUM_THREADS=2` on the SOEP unit only*, left from when three services shared the box.
   That one line made every SOEP model stage twice as slow as the identical GeoDB stage.

**int8 helps the reranker and HURTS the bi-encoder.** Dynamic quantisation gives 1.80x on the
cross-encoder (2,463 -> 1,366 ms for 16 documents) with no measurable precision cost on either
gate, and 0.47x on the query encoder (454 -> 959 ms), because a single ~30-token sequence is too
small for the quantised GEMMs to pay for their overhead. Quantise only the ENCODER submodule
(`model.roberta` / `model.bert`): replacing the whole module breaks sentence-transformers' call
path, which then hands the tokenised batch in positionally and dies inside
`create_position_ids_from_input_ids`. int8 scores are not faithful (correlation 0.85 to fp32, the
top-5 order changes) and not deterministic between runs, which is why it has to be judged on the
gates and not on score correlation.

**The rerank width and depth were swept against both gates**, 8-16 candidates by 320-480
characters: hit@10 never moved, hit@1 and hit@3 moved by at most 1, and no configuration produced
a miss. 10 candidates at 480 characters is best-or-tied on both and about 40% cheaper than 16.
Query vectors are cached (256 entries), which is what makes a repeat 500 ms faster.

Next lever if it needs to be faster still: ONNX Runtime for the cross-encoder, worth roughly
1.5-2.5x on that stage, at the cost of installing onnxruntime plus optimum on the VM and
exporting the model. Not done: it is a live service and the current numbers are usable.

## Keeping this running: MAINTENANCE.md is the operator's document

`MAINTENANCE.md` (German, for a student assistant or whoever inherits this) holds the routines:
what runs by itself, how to read the weekly report, and what to do when a source address, a
service, or the certificate goes wrong. This file stays the technical inside view. When the two
disagree, one of them is out of date and needs fixing, not working around.

The weekly report runs on the **VM**, not here: `scripts/health_check.py`, installed by
`scripts/install_health_check.sh`, Mondays 05:30 via cron, writing
`/home/kwandel/health/repo/state/latest.json` plus one line per run in `logs/health.log`. lovelace
is a pod, so no schedule survives here; the VM is a real machine. Sections: a real query against
both finders (not `/health`, which stays green with a missing index), the 36 source entry pages in
a browser, a rotating sample of about 420 deep links, index age, certificate, disk and backup.
`bash ~/kwandel/bin/geolab_alarm.sh` brings a non-green report to the person at login.

Two rules for anything that touches it. **Self-healing must not hide its cause**: the report turns
yellow after a repair, never green, because a service that needs restarting every week is broken
even when every restart works. **Acknowledged exceptions are dated**: an address that answers but
cannot be checked from a data centre goes in `data_sources/registry/known_url_issues.json` with a
reason and a review date, so an exception cannot quietly become permanent.

## A source address is corrected in ONE place, and it is not the registry file

`data_sources/registry/geo_sources.json` is GENERATED from `Geospatial_Data_Sources.xlsx` by
`scripts/build_source_registry.py`. It says "canonical, committed" at the top of that script, which
is how four corrected addresses and eight maintenance notes came to be typed straight into the JSON
by hand. They survived exactly until the next regeneration, which reverted every one of them
silently and took the reasoning with it. Found on 2026-09-03 by regenerating and diffing.

So all of it now lives in `SOURCE_FIXES` in `build_source_registry.py`, keyed by slug: `url` (the
workbook's own address moves to `url_former`), `maintenance_note` (internal, never shown), and
`note` (which IS shown, it lands in the portal record's description as "Hinweis: ..."). Regeneration
reproduces the repairs. `PORTAL_OVERRIDES` and `PORTAL_URL_OVERRIDES` in
`build_geodb_metadata.py` are both empty on purpose: an override there reached the portal record
only, while the source card, the attribution page, the deliverables and the address check all read
the registry and went on showing the wrong address.

Corollary for any generated artifact in this repo: fix the generator, never its output. If you
catch yourself editing a file some script writes, that edit has a half-life of one run.

## Caddy reads the certificate file once, at start

TLS for both finders is an externally deployed wildcard certificate at
`/etc/ssl/geolab.soz.uni-bielefeld.de/fullchain.cer`, referenced by an explicit `tls` directive in
the Caddyfile. Caddy therefore does **no** ACME renewal here, and it reads that file only when it
starts. The file was renewed on 2026-08-06; Caddy kept serving the June certificate and would have
served an expired one from 2026-09-06, blocking both sites in every browser, on a Sunday. Found on
2026-09-03 by the first run of the new health check, three days before it would have broken.

`caddy-cert-reload.path` on the VM now reloads Caddy whenever that file changes (a 15 s delay
covers a deployer writing key and chain separately), and `health_check.py` compares the served
certificate against the file weekly and reloads if they differ. When debugging TLS here, check
those two before suspecting ACME: there is no ACME. A remaining lifetime shorter than the file's is
a missing reload, not a failed renewal.

## The services' tuning lives in systemd drop-ins, not in the unit file

`systemctl cat geolab-inkar` prints the unit followed by everything in
`/etc/systemd/system/geolab-inkar.service.d/`, and on this VM that directory carries the decisions:
`e5.conf` (the embedding model the indexes were actually built with), `onnx.conf` and `int8.conf`
(the quantised reranker), `rerank.conf` (candidates and document characters, swept against both
gates), `threads.conf`. Each file carries the measurement that justified it.

**Never remove that directory to undo an experiment.** On 2026-09-05 a one-line thread experiment
was reverted with `rm -rf` on the whole `.service.d`, which also deleted the embedding-model
override: the finder restarted on `bge-m3` while its index is built with `e5-large-instruct`, was
briefly 502 while it downloaded the wrong model, and would have answered with nonsense once it came
up. Put an experiment in its own file and delete only that file. If the directory is lost, the twin
service still has its copies and
`soep_metadata_output/*_embeddings.npy.meta.json` names the model the index was built with, which is
the authority on what the service must load.

## Hard-won rules

**The embedding cache is matched by ROW COUNT only, never by model.** `_load_cached_embeddings`
accepts any `.npy` whose first dimension matches the number of rows. An e5 cache read by a
bge-configured service (or the reverse) loads silently and returns nonsense rankings. Whenever the
bi-encoder changes, rebuild **every** source's `.npy` and delete stale copies in both
`soep_metadata_output/` and the VM's `/opt/geolab/cache`. Adding a source changes the row count of
that source's cache only, so the other sources' caches stay valid.

**e5 needs an instruction prefix on queries and raw documents.** The default bi-encoder is
`intfloat/multilingual-e5-large-instruct`, chosen by an A/B on this corpus (it is the only model
that surfaces the adult gender-role battery for the terse query "Geschlechterrollen": dense rank 2
against 203 for bge-m3). `_format_query` adds the prefix, gated on "e5" appearing in the model
name. Leaderboard rank did not predict our corpus; re-run the A/B before swapping again.

**The reranker must be multilingual.** An English-only reranker rewards the chatty enriched
English descriptions and buries terse German-labelled canonical items. The code default is
`BAAI/bge-reranker-v2-m3`; **production overrides it to `bge-reranker-base` with
`SOEP_RAG_RERANK_CANDIDATES=16`** in the systemd units, because e5 already puts the gold item in
the top window and the heavier reranker only costs latency on 4 CPU cores. Keep that override when
touching the units.

**Retrieval-only by design.** `/api/execute`, `/api/soep` (raw aggregation) and the local LLM are
disabled deliberately. Do not re-enable them to "make the answer nicer". The public services must
not become a data-access path, and the licence position depends on it.

**Committed scripts resolve paths from `__file__`, never from the agent scratchpad.** Applies to
every flattener under `scripts/`. Downloaded catalogue files live in `data_sources/<NN>-<slug>/raw/`
and are git-ignored; the briefs and the registry are committed.

**Never commit data.** Metadata JSON, `.npy`, `.faiss`, `.parquet`, `.csv`, raw drops, and any
`.env`/auth file are git-ignored. INKAR is BBSR-licensed and SOEP metadata is covered by the data
use agreement, so the repos stay code-only.

## Environments

`/home/researcher/miniconda3/envs/geolab-rag/bin/python` on this box (faiss, sentence-transformers,
torch, pandas, openpyxl). Use its full path; do not run bare `python3` and do not install into
`base`. If you add a package, export the env afterwards per the workspace rule.
