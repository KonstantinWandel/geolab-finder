# Description review and offline embedding comparison

Reviewed 4 October 2026. No respondent microdata was opened and no production embedding file
was replaced. Current SOEP metadata is official v41 documentation, not the former small-model
enrichment. Temperature-zero LLM generation would still risk inventing or dropping qualifications.

## Presentation change

Official notes, question wording, categories and distributions now appear as separate sections,
preferring the selected language. Only exact repeated question alternatives are deduplicated;
distinct variants remain. The API's `description_original` preserves source line breaks while
the existing normalized `rich_description`, retrieval inputs and exports remain unchanged.
The full original is available in an expandable source section. Regionalatlas definitions use
their source's method/statistics/limitations headings, preserving any preceding date qualification.
Unknown description formats fall back to the complete text instead of guessing their meaning.

Inspected examples include `pgen/pglabnet` (monthly main-job income, imputation), `pgen/pgisced11`
(education coding), and `pl/plh0033` / `pl/plh0182` (question alternatives). Six live desktop/mobile
checks verified income/education official notes and life-satisfaction wording and original text.

## Embedding experiment

`scripts/eval_soep_document_variants.py` re-embedded the 23,855 default analysis variables in three
representations, separately from production. Same e5-large-instruct model, 512-token limit and fp32
precision throughout. The 59 existing German/English gate queries covered income, education,
health, personality, household/family, migration, politics and geography. The CPU/int8 GTE
multilingual reranker, 12-candidate pool, 480-character rerank document and fusion stayed fixed.
Only the dense representation changed; this is not an experiment rewriting reranker documents.

Complete machine-readable evidence, corpus/document hashes, per-query ranks and timestamps:
[`output/eval_soep_document_variants_20261004.json`](output/eval_soep_document_variants_20261004.json).

| Embedding document | Dense hit@30 | Final hit@1 | Final hit@3 | Final hit@10 | Final MRR@10 |
|---|---:|---:|---:|---:|---:|
| Current retrieval document | 59/59 | 49/59 | 55/59 | 59/59 | 0.8903 |
| Identifier and bilingual titles only | 58/59 | 47/59 | 53/59 | 56/59 | 0.8534 |
| Titles, dataset/topic/unit/period, exact official notes/questions and substantive categories | 55/59 | 45/59 | 51/59 | 55/59 | 0.8232 |

Decision: retain the existing production embeddings. Title-only lost gross earnings, Big Five
and household-child-count cases from the top ten. Separated official fields additionally missed
equivalised household income and education duration. A tidier document was not better retrieval.
Temporary arrays remain outside the repositories; only the report and evaluation code are committed.

These are **known regression cases with sometimes broad name/label acceptance patterns**, not a
held-out expert relevance study. In particular some patterns accept adjacent income definitions
or questionnaire populations. A hit@10 does not certify the first suggestion is suitable: the
current run ranked youth life satisfaction first for one generic query, and a specialised
instrument first for highest school qualification. No thresholds or priors were tuned to these
results, and no general accuracy or causal improvement claim follows from them.

Before another document/reranker change, add stricter held-out judgments for unit, period,
population, denominator and imputation; inspect top-hit errors as well as recall. LLM summaries,
if later attempted, should remain separate, cite exact supporting spans, retain provenance and
pass this broader review before replacing any official definitions or embedding corpus.

Reproduce in the existing `geolab-rag` environment with the locally prepared ONNX model:

```bash
SOEP_RAG_DEVICE=cuda OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 \
SOEP_RAG_RERANKER_MODEL=Alibaba-NLP/gte-multilingual-reranker-base \
SOEP_RAG_RERANK_ONNX="$PWD/models/gte-multilingual-reranker-base-onnx-int8" \
SOEP_RAG_RERANK_CANDIDATES=12 SOEP_RAG_RERANK_DOC_CHARS=480 \
~/miniconda3/envs/geolab-rag/bin/python scripts/eval_soep_document_variants.py \
  --metadata soep_metadata_output/soep_v41_metadata.json \
  --out-dir /tmp/geolab-document-ablation --rerank
```
