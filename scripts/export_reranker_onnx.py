#!/usr/bin/env python3
"""Export a cross-encoder reranker to ONNX and quantise it to int8 for the CPU deployment.

The finders rerank on the VM's CPU through ONNX Runtime (`SOEP_RAG_RERANK_ONNX`, see
OnnxCrossEncoder in backend/app/services/soep_rag_advisor.py). The first export, of
bge-reranker-base in August 2026, was done by hand and left only its ort_config.json behind;
this script reproduces that recipe so a second model can be exported the same way:
dynamic quantisation, per-channel int8 weights, AVX2 instructions (the VM is an EPYC 7542,
which has AVX2 and no AVX-512).

  python scripts/export_reranker_onnx.py --model BAAI/bge-reranker-v2-m3 \
      --out models/bge-reranker-v2-m3-onnx-int8

The quantised graph changes the scores slightly, so a new export is judged on the retrieval
tests (eval_soep_search.py, eval_soep_concepts.py, eval_geodb_search.py, eval_geodb_hard.py),
not on score correlation.
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", required=True, help="Hugging Face id of the cross-encoder")
    parser.add_argument("--out", required=True, help="directory for the quantised model")
    args = parser.parse_args()

    from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig
    from transformers import AutoTokenizer

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        model = ORTModelForSequenceClassification.from_pretrained(args.model, export=True)
        model.save_pretrained(tmp)
        AutoTokenizer.from_pretrained(args.model).save_pretrained(tmp)
        quantizer = ORTQuantizer.from_pretrained(tmp)
        config = AutoQuantizationConfig.avx2(is_static=False, per_channel=True)
        quantizer.quantize(save_dir=out, quantization_config=config)
        for name in ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
                     "sentencepiece.bpe.model"):
            if (Path(tmp) / name).exists() and not (out / name).exists():
                shutil.copy(Path(tmp) / name, out / name)
    print(f"wrote {out}: {sorted(p.name for p in out.iterdir())}")


if __name__ == "__main__":
    main()
