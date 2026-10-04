# GESIS Public Metadata

GESIS is an additional source in `registry/additional_sources.json`, not an edit to
the predecessor's workbook. The public catalogue is harvested before geographic
eligibility is applied. This is not a curated list of study IDs.

## Scope And Access

- Archive study metadata: `https://dbkapps.gesis.org/dbkoai/`, German and English
  DDI 2.5 `ListRecords` to exhausted resumption tokens. Broken provider DDI conversions
  fall back to da|ra and then Dublin Core; deleted records are retained in the audit.
- Dataset and variable metadata: the provider's complete GESIS KG 2.0.0 RDF export,
  DOI [10.7802/2969](https://data.gesis.org/sharing/#!Detail/10.7802/2969), with counts
  and deterministic distributed samples checked against
  `https://data.gesis.org/gesiskg/sparql`. RDF is parsed by pyoxigraph, not regular expressions.
  The sample comparison requires equality of every field used by the GeoDB builder.
  The report also records full-triple differences: `hasFulltext` is serialized as
  boolean `true`/`false` in RDF versus `1`/`0` by the API. This non-core field is not
  used for geographic selection or data-access claims.
- Vitrine's twelve documented search indices were probed, not bypassed. They currently
  return a provider challenge. `VITRINE_ACCESS_REPORT.json` records the evidence.
  In particular, external partner catalogues exposed through Vitrine are **not** claimed
  as harvested by the archive/KG route.
- Only public catalogue metadata is downloaded. No respondent records, survey data
  files, identifying geocodes, restricted research data or archive accounts are accessed.

The KG metadata export is **CC-BY-4.0**; display and CSV records carry its citation:
Biswas, D., Gupta, E., Yu, R., & Zapilko, B. (2025). GESIS Knowledge Graph, Version 2.0.0.
DBK/SDN public study metadata is CC0 1.0. If sources are merged, the KG attribution
is retained. Metadata licences do **not** grant access to or a licence for the research
data; provider access conditions are separately preserved per record.

## Geographic Selection

`scripts/gesis_regions.py` distinguishes four kinds of discoverable metadata:

- `regional_dataset`: evidence of regional aggregate observations.
- `regional_study`: regional scope or mixed individual/context files, not an aggregate-data claim.
- `regional_dataset_variable`: actual provider variable in an evidenced aggregate dataset.
- `survey_geography_variable`: a geographic/context field of individual data, not a regional indicator.

National country coverage alone is insufficient. A parent abstract cannot make every
questionnaire item geographic. Collection methods and individual analysis units override
aggregate mentions in mixed studies. Abstract-only aggregate evidence must be adjacent
to a geographic level. Variable names and labels come from the RDF, not an LLM.
The geographic label must describe a primary location/context field or an explicit
identifier; a behaviour, intention, attachment question, response-time field or
weight that merely mentions a region does not qualify. Retrieval text also names
the observation type explicitly, so a survey location field is not described to
the reranker as an aggregate statistic. Display retains original substantive text
and access/licensing notes; repeated legal boilerplate is not used for embeddings.

KG variable resource IRIs return 404 as browser pages; they are retained in
`metadata_resource_uri` for provenance. The outward link opens the containing study
and is labelled `dataset`, not an exact-variable landing page. Where no study is
assigned, the public SPARQL response for the exact resource is the fallback.

Historical constituencies remain historical. A Kreis is **not** automatically NUTS3;
only explicit provider NUTS notation enters that facet. There is no automatic AGS/NUTS
crosswalk or claim that a study can be mapped on current boundaries. All GESIS records
are `metadata_only=true`, `observation_data_available=false`, `map_ready=false`.

Rule 1.6 also recognises documented grid-cell, geospatial and georeferenced scopes.
That does not turn an individual study into an aggregate dataset. Geography fields
use the discovery theme `Geografie / Kontext`, with original study topics retained
separately. Compact retrieval documents keep collection-year ranges and observation
units; the complete collection periods and original questions remain in metadata.

These are rule-based discovery candidates, not an expert certification of each study.
Review the recorded `geographic_evidence` and the provider's codebook before analysis.

## Reproduce

Use full-path project interpreters; the RDF dependency is pinned in `environment.yml`
and the workspace's `conda_envs_export/geo.*` files.

```bash
G=/home/researcher/miniconda3/envs/geo/bin/python
W=/home/researcher/miniconda3/envs/webshot/bin/python
E=/home/researcher/miniconda3/envs/geolab-rag/bin/python

$G scripts/harvest_gesis.py --stage oai
$W scripts/fetch_gesis_bulk.py
$G scripts/import_gesis_bulk.py
$G scripts/build_gesis_metadata.py
$G -m unittest discover -s scripts -p 'test*gesis*.py'
```

Raw HTTP responses have URL, date and SHA-256 sidecars. The provider's bulk-file MD5
and local SHA-256 are both checked. Import failures never replace the verified
SQLite archive. Use a **new folder/snapshot for a new upstream release**, not stale
HTTP caches. The SPARQL-only harvester remains available as a resumable fallback;
it counts subject triples and stays below the endpoint's 10,000-row response cap.

The normal multi-source builder consumes only a complete, checksum-verified regional
snapshot through `flatten_gesis`; it does not silently trigger a catalogue harvest
on every routine refresh. Missing/partial snapshots must be reviewed, not presented
as complete catalogue coverage.

For this **first addition**, `prepare_gesis_index.py` appends GESIS to a snapshot of
the live index and embeds only the new documents with the exact production e5 model
and 512-token context. Existing source records and vectors, and the separate INKAR
cache, are preserved. `validate_gesis_update.py` runs the broad before/after gates,
checks every added variable against the source RDF, and exercises diverse GESIS
queries and filters. `deploy_gesis_index.py` requires passing reports, checks the
live baseline hashes against concurrent changes, backs up the four index files,
and rolls back on failed startup/search verification. It restarts **only** GeoDB.

GeoDB now preserves the global dense head and adds one best candidate per otherwise
unrepresented provider, bounded at twice the fixed pool. This prevents a large
archive's repeated fields from filling every candidate slot. A single explicit
alphanumeric code can add exact matches, but ordinary words/sentences cannot. There
is no named-query override or dataset-authority boost in this GeoDB change. Provider
resource URIs prevent study-local variable codes from collapsing across studies.
SOEP retains its previous path: `SOEP_SHARED_CHECK_REPORT.json` checks all ranked
identities and scores, not just whether one expected hit survived.

The tested four GeoDB files also replace the checksum-matching local baseline under
`soep_metadata_output/`; `output/gesis-index/baseline/` retains the original. Frontend
builds derive their counts from that directory, or `GEOLAB_METADATA_ROOT` for an
isolated candidate. The deployed frontend preserves previous hashed assets so open
browser tabs do not break. `publish_gesis_frontend.py` checks the tested build hash,
backs up the webroot and switches the index HTML last without restarting services.

Later GESIS refreshes replace that source in a newly captured baseline, then repeat
the same evaluation process. The first-addition script intentionally refuses an
already-GESIS baseline, rather than accumulating duplicate snapshots.

## Canonical Records

Never repeat a guessed count. The committed reports are the measured source of truth:

- `BULK_DOWNLOAD_REPORT.json`: release, checksums and bytes.
- `BULK_VALIDATION_REPORT.json`: API/export counts and sample comparisons.
- `HARVEST_REPORT.json`: stage completion, exhausted OAI pages and scope limits.
- `REGIONAL_REPORT.json`: studies/variables considered, selected kinds, SHA-256.
- `INDEX_REPORT.json`: model, appended rows, unchanged baseline and candidate hashes.
- `QA_REPORT.json`: broad regression results and source-grounding checks.
- `UNIT_TEST_REPORT.json`: pipeline checks in `geo` and shared retrieval checks in
  `geolab-rag`; those environments intentionally have different dependencies.
- `DEPLOYMENT_REPORT.json`: live verification, backup and unchanged site-root hashes.
- `SOEP_SHARED_CHECK_REPORT.json`: paired full-output equality for the shared change.
- `FRONTEND_CHECK_REPORT.json`: live DE/EN desktop/mobile source filtering, selected
  CSV/JSON provenance/licence/access exports, layout and default-off telemetry.
- `FRONTEND_DEPLOYMENT_REPORT.json`: build hash, backup, retained bundles and other
  apps' unchanged HTML hashes. Website counts/attribution have a separate report in
  `../geolab_regiohub/GESIS_PUBLICATION_REPORT.json`.
- `EXISTING_GEODB_AUDIT_REPORT.json`: wider provider checks and two confirmed legacy
  metadata issues. It distinguishes provider challenges, unresolved timeouts and
  source-wide boilerplate from proven record-level defects; those legacy records
  were not silently rewritten in the first GESIS addition.

## Quality Limits

The passing positive gate means no previously found case became a miss within the
tested top ten. It does not mean every first result improved: smoke hit@1 decreased
from 55/58 to 53/58. The hard gate improved from 30/31 to 31/31 at ten and 27/31 to
29/31 at three. All ten additional GESIS cases passed, but their regex expectations
are not an independent expert measurement-comparability assessment. The unchanged
weak-match threshold catches 18/28 old negative controls versus 20/28 before; some
controls may also need re-review now that the catalogue contains international surveys.
Do not retune the threshold on this same gate and call it held-out validation.

For subsequent changes, retain these cases and add externally reviewed negatives,
aggregate-versus-individual contrasts and exact provider-variable judgements. The
candidate pool change keeps the same embedder/reranker and production settings.

The SQLite/RDF/download files, generated metadata and embeddings stay local and
git-ignored. They contain public metadata, but are large and reproducible.
