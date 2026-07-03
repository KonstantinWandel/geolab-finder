# GeoLAB Regional Indicator Finder (INKAR)

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21134145.svg)](https://doi.org/10.5281/zenodo.21134145)

Semantic search over research-data **metadata**: a [SOEP](https://www.diw.de/soep) survey-variable finder and an [INKAR](https://www.inkar.de/) regional-indicator finder, served from one codebase.

You ask in plain language ("net individual income from labour", "rural childcare coverage by district") and get the most relevant variables/indicators back, ranked — across German labels and English descriptions.

> Status: research prototype. Retrieval is semantic and imperfect; verify hits against the official documentation before use.

## How it works

- **Bi-encoder retrieval** with [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) (multilingual, 1024-d) over the metadata corpus.
- **Cross-encoder rerank** with a multilingual reranker — default [`BAAI/bge-reranker-base`](https://huggingface.co/BAAI/bge-reranker-base) (fast on CPU), configurable to [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) via `SOEP_RAG_RERANKER_MODEL`. A multilingual reranker matters: an English-only one buries terse German-labelled canonical variables (e.g. `pgen/pglabnet`) under chattier subsample items.
- **Score fusion:** the final rank fuses the bi-encoder, the reranker, a lexical-overlap signal, and a small **dataset-authority prior** (boosts canonical generated/survey datasets like `pgen/pequiv/pl`, down-weights age/group subsample instruments) plus a decisive exact-code bonus.
- **Document hygiene:** the standard SOEP missing-value boilerplate (`-1`…`-9`), identical across ~all variables, is stripped before embedding so it doesn't dominate the signal.
- **FAISS** inner-product index over normalized embeddings; optional filters (dataset, year, spatial/NUTS level, theme).
- One backend, two modes via `GEOLAB_APP_MODE=soep|inkar|all`; a small React UI per mode.

## Models

The retrieval models are downloaded from Hugging Face at runtime (cached locally):

- [`BAAI/bge-m3`](https://huggingface.co/BAAI/bge-m3) — bi-encoder — **MIT**.
- [`BAAI/bge-reranker-base`](https://huggingface.co/BAAI/bge-reranker-base) / [`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3) — cross-encoder reranker — **Apache-2.0**.

An optional local answer-generation LLM (`meta-llama/Llama-3.1-8B-Instruct`, Meta Llama 3.1 Community License) is **disabled by default** (`SOEP_RAG_LOAD_LLM=0`); the finders are retrieval-only.

## Quickstart (Docker)

```bash
# 1. Provide the metadata + build embeddings (see scripts/ and the data note below)
# 2. Bring up a stack:
cd deploy/secure-soep   # or deploy/secure-inkar
./run.sh
```

Each stack is a FastAPI backend + a Caddy frontend (basic auth) + an optional Cloudflare tunnel. On hosts without a working container runtime the same processes run natively (uvicorn + the `caddy`/`cloudflared` binaries).

## Data and licenses — **not included in this repository**

This repo is **code only**. You must supply the metadata yourself; it is governed by its own terms:

- **SOEP variable metadata** (labels, categories, descriptions) — from [paneldata.org](https://paneldata.org/) / SOEP-Core. Public *metadata*; using it is covered by your SOEP data-use agreement. No microdata is used or distributed here. The enriched English descriptions are model-generated derivatives of that metadata.
- **INKAR 2025 indicators** and the **BBSR Raumgliederungssystem 2023** reference — © [BBSR](https://www.inkar.de/), used under their terms.

Generated embeddings, FAISS indexes, raw data files, and any `.env`/auth secrets are git-ignored and must never be committed.

## Repository layout

```
backend/        FastAPI app + services (retrieval, rerank, advisor)
frontend/       React/Vite UI (mode-aware: SOEP / INKAR)
scripts/        Metadata flattening + index building (e.g. build_inkar_metadata_index.py)
deploy/         Container stacks (secure-soep, secure-inkar) + Caddyfiles
```

## Citing

If you use this software, please cite it via the archived release (see `CITATION.cff`). A Zenodo DOI is minted per GitHub release.

## License

[MIT](LICENSE) © 2026 Konstantin Wandel. Built as part of the GeoLAB project, Universität Bielefeld.
