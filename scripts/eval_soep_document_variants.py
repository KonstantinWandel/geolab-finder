#!/usr/bin/env python3
"""Offline document ablation; never overwrites metadata, production embeddings or models.

Uses the existing 59-case SOEP gate on the UI's default analysis-variable cohort. These are
known, sometimes broad acceptance patterns, not held-out relevance judgments. Results can
reject a harmful change but cannot alone justify deploying a new document representation.
All variants are re-embedded at the same fp32 precision. With --rerank, only candidate
retrieval changes: the current reranker documents, model and fusion remain fixed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.soep_rag_advisor import SOEPRagAdvisorService, OnnxCrossEncoder
from eval_soep_search import CASES, matches


def variant_doc(raw: dict, row: dict, variant: str, service) -> str:
    if variant == 'current':
        return service._build_doc(row)
    labels = [row.get(key, '') for key in ('label', 'label_en', 'label_de_mt', 'label_en_mt')]
    identity = '\n'.join([f"Variable: {row['variable_name']}", *dict.fromkeys(filter(None, labels))])
    if variant == 'titles_only':
        return identity
    # Exact official fields, not LLM summaries: keep measurement qualifications verbatim.
    fields = []
    for line in str(raw.get('rich_description', '')).splitlines():
        prefix = line.partition(':')[0]
        if prefix in {'Offizielle Erläuterung', 'Official note', 'Fragetext', 'Question wording'}:
            fields.append(line)
    fields = list(dict.fromkeys(fields))
    return '\n'.join([
        identity, f"Dataset: {row['dataset']}", f"Topic: {row.get('theme', '')}",
        f"Analysis unit: {raw.get('analysis_unit', '')}", f"Period: {raw.get('period', '')}",
        *fields, f"Categories: {row.get('value_labels', '')}",
    ])


def summary(ranks: list, cutoffs: tuple) -> dict:
    return {
        **{f'hit@{k}': sum(rank is not None and rank <= k for rank in ranks) for k in cutoffs},
        f'mrr@{max(cutoffs)}': sum(1 / rank for rank in ranks if rank is not None) / len(ranks),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--rerank', action='store_true')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    os.environ['GEOLAB_APP_MODE'] = 'soep'
    os.environ['SOEP_RAG_METADATA_PATH'] = str(args.metadata.resolve())
    service = SOEPRagAdvisorService()
    raw = json.loads(args.metadata.read_text())
    assert raw and all(row.get('soep_version') == 'v41' for row in raw), 'Expected official v41 corpus'
    raw = [row for row in raw if not row.get('is_raw')]
    service._rows = [service._normalise_soep_row(row) for row in raw]
    service._loaded = True
    if args.rerank:
        onnx = os.getenv('SOEP_RAG_RERANK_ONNX', '')
        if not onnx:
            raise SystemExit('--rerank requires the production ONNX model path; no torch fallback')
        # Embeddings use the GPU, but comparisons must use the production CPU/int8 reranker.
        service._cross_enc = OnnxCrossEncoder(
            onnx, max_length=int(os.getenv('SOEP_RAG_RERANKER_MAX_LENGTH', '256')),
            threads=int(os.getenv('OMP_NUM_THREADS', '4')), tokenizer_name=service._reranker_name)
    service._embedder = service._new_embedder()
    queries = service._embedder.encode(
        [service._format_query(case[0]) for case in CASES], batch_size=32,
        convert_to_numpy=True, normalize_embeddings=True).astype('float32')
    report = {
        'run_utc': datetime.now(timezone.utc).isoformat(),
        'metadata': args.metadata.name,
        'metadata_sha256': hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
        'rows': len(raw), 'queries': len(CASES), 'cohort': 'default analysis variables, no raw files',
        'model': service.model_name, 'max_seq_length': service.embedding_max_seq_length,
        'precision': 'fp32', 'reranker': service._reranker_name if args.rerank else None,
        'rerank_candidates': os.getenv('SOEP_RAG_RERANK_CANDIDATES', '24') if args.rerank else None,
        'limitation': 'Known broad-pattern gate, not held-out expert relevance. No automatic deployment.',
        'variants': {},
    }
    for variant in ('current', 'titles_only', 'official_fields'):
        docs = [variant_doc(source, row, variant, service) for source, row in zip(raw, service._rows)]
        print(f'Embedding {variant}: {len(docs)} rows', flush=True)
        # Explicitly keep the precision identical even if a caller configured the large-corpus path.
        emb = service._embedder.encode(
            docs, batch_size=args.batch_size, convert_to_numpy=True,
            normalize_embeddings=True, show_progress_bar=True).astype('float32')
        np.save(args.out_dir / f'{variant}.npy', emb)
        scores = queries @ emb.T
        cases, dense_ranks, reranked_ranks = [], [], []
        service._embeddings = emb
        service._docs = docs
        service._faiss_index = None
        service._filter_view_cache.clear()
        for index, (query, name_pattern, label_pattern) in enumerate(CASES):
            order = np.argsort(-scores[index], kind='stable')[:30]
            dense_rank = next((rank for rank, row_index in enumerate(order, 1)
                               if matches(service._rows[row_index], name_pattern, label_pattern)), None)
            dense_ranks.append(dense_rank)
            result = {'query': query, 'dense_rank': dense_rank,
                      'dense_top': service._rows[order[0]]['item_id']}
            if args.rerank:
                rows = service.answer_research_question(query, 10, {'include_raw': False})['recommended_variables']
                rank = next((i for i, row in enumerate(rows, 1) if matches(row, name_pattern, label_pattern)), None)
                reranked_ranks.append(rank)
                result.update(reranked_rank=rank, reranked_top=rows[0]['item_id'] if rows else None)
            cases.append(result)
        result = {'docs_sha256': hashlib.sha256('\0'.join(docs).encode()).hexdigest(),
                  'dense': summary(dense_ranks, (1, 10, 30)), 'cases': cases}
        if args.rerank:
            result['reranked'] = summary(reranked_ranks, (1, 3, 10))
        report['variants'][variant] = result
        (args.out_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({variant: {k: v for k, v in result.items() if k != 'cases'}}), flush=True)


if __name__ == '__main__':
    main()
