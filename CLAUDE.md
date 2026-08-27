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

State as of 2026-08-27 (evening): **live at <https://geodb.geolab.soz.uni-bielefeld.de/> with
11,567 rows** (10,907 GeoDB records + 660 INKAR) from **36 workbook rows, 30 of which carry real
records**. Largest: Regionalstatistik/GENESIS 3,305, GENESIS-Online Bund 3,026, Zensus 2022 1,440,
Gigabit-Grundbuch 632, DB ISR 415, BA-Glossar 313, BA Arbeitsmarktreport 288, GTFS/NeTEx 246,
Regionalatlas 232, Migration & Integration 141, DWD Klimadaten 137, Strukturdaten BTW 2021+2025 98,
Deutschlandatlas 86, Open Data ÖPNV 78, BA Strukturdaten 68, G-BA 52, Bundes-Klinik-Atlas 42,
Wahlergebnisse 38, DB StaDa 37, BA Arbeitsmarkt kommunal 34, FDZ Ruhr 28, OSM POI-Layer 26,
Unfallatlas 26, BORIS-D 21, Ländermonitor 18, offeneregister 13, Hochschulkompass 12, IÖR-Monitor 7,
Destatis Mobilität 6, Wegweiser Kommune 4. Tracker: 25 done, 6 partial, 5 open.
Retrieval gate 2026-08-27: **58 queries, hit@1 53, hit@3 57, hit@10 58, no misses.**

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

**Link health is audited, not assumed.** `scripts/check_geodb_links.py` samples records per source,
fetches the outward link, and compares the response against what that host returns for a
deliberately invalid code. That is what separates "the table opened" from "the portal home page
opened". Current result: **no broken links**; the only non-ok verdicts are the client-rendered
portals (Regionalatlas, federal GENESIS, Zensus) plus deutschlandatlas.bund.de, which refuses
scripted requests. Those records carry `link_verified: false`, the UI marks them with an asterisk,
and the checklist counts them. Note that Regionalatlas belongs in that group too: it is a
dojo/ArcGIS app that reads TCode/ICode client-side, so its "indicator" links cannot be verified
from here either, and an earlier claim that they were is wrong.

**Every record carries `link_level`** (how precisely the link lands) and `link_verified` (whether
that was probed). Improving the portal share and the unverified share is the quality lever.

**Crawl instances in parallel, never within one instance.** Regionalstatistik, federal GENESIS and
Zensus are separate hosts with separate tokens and separate rate limits, so three concurrent
`fetch_genesis_catalogue.py` processes are fine and each writes its own file. Inside one instance
stay sequential: the services cap parallel requests (Destatis says 3, Regionalstatistik 10) and
kill long-running ones. Runtimes measured here: regionalstatistik 129 statistics / 866 tables in
about 20 min, federal 331 / 3,026 in about 50 min, Zensus 12 / 1,440 in about 20 min.

**Adding a source that is not in the workbook means adding a workbook row**, not a special case:
`build_source_registry.py` asserts the expected count (`EXPECTED_SOURCES`, currently 29) and
derives folder numbering from row order, so Unfallatlas, GENESIS-Bund and Zensus each got a blue
row in `Tabelle1` and their own `data_sources/<NN>-<slug>/` folder. **Reordering sources reorders
the records, which silently invalidates the embedding cache** (it matches on row count only), so
always re-embed after adding or moving a source, never only after changing content.

**`data_sources/CHECKLIST.md` is the per-source tracker** and is generated, never hand-edited:
`scripts/build_status_report.py` reads the registry, each `raw/` folder, the built metadata and a
live link check, then writes both the checklist and a blue-marked `Status_GeoDB` sheet appended to
`Geospatial_Data_Sources.xlsx` (untouched original kept as `Geospatial_Data_Sources_orig.xlsx`;
both workbooks are git-ignored, the public facts live in `registry/geo_sources.json` instead).
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
- **deutschlandatlas.bund.de answers 400 to every scripted request** regardless of user-agent
  and accept headers. It needs a browser; do not burn time on header permutations.
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
        sudo rsync -a --delete ~/geodb_stage/site_inkar/ /opt/geolab/sites/inkar/ ;
        sudo chown -R geolab:geolab /opt/geolab/sites/inkar ;
        sudo systemctl restart geolab-inkar geolab-soep'
```

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

Capacity: 4 vCPU, 15 GB RAM, CPU only. A single query takes about 5 s; five simultaneous queries
take about 17 s each. Staggered classroom use is fine. More vCPUs or a small GPU is the only real
lever if it needs to be snappy under burst.

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
