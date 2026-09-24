# GeoDB

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21134145.svg)](https://doi.org/10.5281/zenodo.21134145)

GeoDB, short for GeoDataBase, is a semantic search over the metadata of German georeferenced data
sources. You describe what you are looking for in plain language, in German or English
("Arztdichte", "childcare coverage in rural districts"), and get back the indicators, tables and
datasets that measure it, from the Bundesland down to grid cells. Each result carries its spatial
levels, its years, a short description and a link to the portal that holds the data.

It runs at <https://geodb.geolab.soz.uni-bielefeld.de/> and is part of the
[GeoLAB](https://geolab.soz.uni-bielefeld.de/) of the Leibniz ScienceCampus SOEP-RegioHub at
Bielefeld University and DIW Berlin.

> Status: research prototype. Retrieval is semantic and imperfect; check a hit against the
> source's own documentation before you use it.

## What is indexed

41 sources and about 12,500 records (index of 11 September 2026), among them the
Regionaldatenbank and GENESIS-Online of the statistical offices, Zensus 2022, INKAR (BBSR), the
Regionalatlas, the Deutschlandatlas, the IÖR-Monitor, the Bundesagentur für Arbeit and
OpenStreetMap point layers. The full list, with each source's licence and attribution, is on the
[data sources page](https://geolab.soz.uni-bielefeld.de/data-sources.html).

The index holds descriptions and links. The data stays with the institutions that publish it.

## How it works

- **Bi-encoder retrieval** with
  [`intfloat/multilingual-e5-large-instruct`](https://huggingface.co/intfloat/multilingual-e5-large-instruct)
  over the metadata records. It was chosen over `BAAI/bge-m3` by a comparison on this corpus.
- **Cross-encoder rerank** of the top candidates. Production uses
  [`BAAI/bge-reranker-base`](https://huggingface.co/BAAI/bge-reranker-base), exported to ONNX and
  quantised to int8, which is fast enough on four CPU cores; the code default is
  [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3), set with
  `SOEP_RAG_RERANKER_MODEL`. The reranker has to be multilingual: an English-only one buries terse
  German labels under longer English descriptions.
- **Score fusion** of the bi-encoder, the reranker and a lexical-overlap signal, with a bonus for
  an exact match on a record's code.
- **Filters** by source, spatial level, year range and theme. Each filter shows how many records
  a value would leave, given the other filters.
- One backend also serves the [SOEP Variable Finder](https://github.com/KonstantinWandel/soep-variable-finder),
  selected by `GEOLAB_APP_MODE`: `inkar` is GeoDB (the name dates from when INKAR was its only
  source), `soep` is the SOEP finder.

## Models

Downloaded from Hugging Face at runtime and cached locally:

- `intfloat/multilingual-e5-large-instruct`, bi-encoder, MIT.
- `BAAI/bge-reranker-base`, cross-encoder, MIT; `BAAI/bge-reranker-v2-m3`, cross-encoder, Apache-2.0.

The code can load a local answer-generating language model (`SOEP_RAG_LOAD_LLM`). It is off by
default and off in production; the finders only retrieve.

## Building the index

The pipeline lives in `scripts/`, one step per script:

```bash
python scripts/build_source_registry.py   # source workbook -> data_sources/registry/
python scripts/fetch_sources.py           # portals -> data_sources/<NN>-<slug>/raw/
python scripts/build_geodb_metadata.py    # raw/ -> soep_metadata_output/geodb_metadata.json
bash scripts/refresh_all.sh --no-deploy   # all of the above, then embedding and the retrieval gate
```

The source workbook is not part of the repository; the registry built from it is
(`data_sources/registry/geo_sources.json`). `build_geodb_metadata.py` holds one flattener per
source. Two retrieval tests guard changes to the models or the records:
`scripts/eval_geodb_search.py` (58 queries) and `scripts/eval_geodb_hard.py` (concept-only and
cross-language questions, plus questions the index cannot answer).

The interface is built with `bash frontend/build.sh inkar`, which writes `frontend/dist-inkar/`.

## Running it

The production service runs natively: uvicorn under systemd, behind Caddy. `deploy/` holds
container stacks for hosts with a container runtime (`cd deploy/secure-inkar && ./run.sh`), each a
FastAPI backend with a Caddy frontend.

## Data and licences

This repository holds code only. The metadata it indexes belongs to the publishing institutions
and is used under their terms, listed per source on the data sources page. INKAR and the BBSR
Raumgliederung are © [BBSR](https://www.inkar.de/). Embeddings, indexes, downloaded catalogue
files and any credentials are git-ignored.

## Repository layout

```
backend/        FastAPI app; app/services/soep_rag_advisor.py is the retrieval service
frontend/       React/Vite interface, one build per finder (build.sh)
scripts/        source registry, fetchers, flatteners, retrieval tests, link checks
data_sources/   per-source briefs and the generated source registry
deploy/         container stacks and Caddyfiles
MAINTENANCE.md  operating notes, in German
```

## Author

Konstantin Wandel, research fellow at Universität Bielefeld (SOEP-RegioHub):
<https://konstantinwandel.github.io/>

## Citing

Please cite the archived release; see `CITATION.cff`. Zenodo archives every GitHub release, and
the DOI above always resolves to the newest one.

## License

[MIT](LICENSE) © 2026 Konstantin Wandel. Part of the GeoLAB project, Universität Bielefeld.
