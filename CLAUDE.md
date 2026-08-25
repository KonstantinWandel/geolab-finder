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

State as of 2026-08-25: **live at <https://geodb.geolab.soz.uni-bielefeld.de/> with 4,119 rows**
(3,459 GeoDB records + 660 INKAR). By source: Regionalstatistik/GENESIS Merkmale 2,756,
Regionalatlas 232, Migration & Integration 140, Deutschlandatlas 86, BA Strukturdaten 68,
Bundestagswahl 2021 49, Bundes-Klinik-Atlas 41, Ländermonitor 17, G-BA Qualitätsberichte 16,
German Company Data 12, Hochschulkompass 11, Open Data ÖPNV 6, plus 25 portal-level records.
Adding a source means: a `FETCH_PLAN` entry, a flattener, rebuild, re-embed, redeploy.

**`data_sources/CHECKLIST.md` is the per-source tracker** and is generated, never hand-edited:
`scripts/build_status_report.py` reads the registry, each `raw/` folder, the built metadata and a
live link check, then writes both the checklist and a blue-marked `Status_GeoDB` sheet appended to
`Geospatial_Data_Sources.xlsx` (the untouched original is kept as `Geospatial_Data_Sources_orig.xlsx`).
Per-source state lives in that script's `OPEN_ITEMS`; candidate sources not yet in the workbook
live in its `CANDIDATES`. Change the script, re-run it, never edit the outputs.

`scripts/eval_geodb_search.py` is the retrieval smoke test: 28 concept queries with an expected hit,
reporting hit@1/@3/@10. Baseline 2026-08-25 with e5-large-instruct + bge-reranker-base:
**hit@1 27/28, hit@3 28/28, no misses**. Run it after any change to the model, the document
construction, or the record set, and compare against that baseline before deploying.

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
- **The Regionalstatistik portal cannot be deep-linked by query parameter.** It is a JSF app:
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
