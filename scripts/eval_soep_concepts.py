#!/usr/bin/env python3
"""Concept test for the SOEP Variable Finder: queries that name a topic, not a label.

`eval_soep_search.py` asks mostly for things whose label one can almost type ("Familienstand",
"Lebenszufriedenheit heute"), and every tuning decision until 2026-10-01 was made on it. The
anonymous search log showed where that leaves the finder: people ask for "Geschlechterrollen",
"Diskriminierung", "mental health" or "Willkommensgefühl", and the variables that answer them
are labelled "Fam: Kind unter 6 J. leidet wenn Mutter arbeitet" or "Bereich Diskriminierung 1".
No word of the query is in the label, so a change that only protects label-near queries can
quietly make these worse, and nothing measured it.

The cases cover about twenty topics, each asked two or three ways (a German umbrella term, the
English term, an everyday question), so one topic cannot carry the result. The query texts are
written for this file; none is copied from the search log. Every gold set was looked up in the
built v41 metadata first, and a set lists all variables that answer the question, because a
topic query has many right answers.

Two numbers matter here. The rank of the first relevant hit says whether the topic is found at
all. DR@10, the number of different relevant variables or batteries among the first ten, says
whether the first screen is useful for exploring it, which is what a topic query is for.

To compare two settings, write both runs with --json-out and pair them:
  python scripts/eval_soep_concepts.py --compare before.json after.json

Run (loads the model, so give it a minute):
  GEOLAB_APP_MODE=soep SOEP_METADATA_ROOT=$PWD/soep_metadata_output \
  SOEP_RAG_METADATA_PATH=$PWD/soep_metadata_output/soep_v41_metadata.json \
  SOEP_RAG_CACHE_DIR=$PWD/soep_metadata_output/cache SOEP_RAG_DEVICE=cpu \
  SOEP_RAG_RERANK_ONNX=$PWD/models/bge-reranker-base-onnx-int8 \
  SOEP_RAG_RERANKER_MODEL=BAAI/bge-reranker-base \
  python scripts/eval_soep_concepts.py
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_soep_search import matches  # noqa: E402  (one definition of a match for both tests)

# Gold sets, one per topic. Battery members are listed by stem so a whole battery counts.
GENDER = r"^(plh0(298|30[1-4789])|lb11(1[03-69]|2[01])|plj06(11|2[0-5]))"
DISCRIMINATION = (r"^(plh0387|plh040[56]|plh041[1-6]|plj0048|plj022[7-9]|plj023[0-5]|plj03(28|3[0-9])"
                  r"|plm0144|plm0505|plb0338|lr3139|lr3086|jl165[0-3]|ylh003[2-5]|bjp_lmore76|lb0557"
                  r"|elb0011|elb0368|noinst6|clj0013|k_awshr)")
ORIGIN_DISCRIMINATION = (r"^(plj0048|plh0387i08|plj03(28|3[0-9])|plm0144|plj022[7-9]|plj023[0-5]|lb0557"
                         r"|plh0413i01|plh0415i01|plm0505|lr3139|lr3086)")
LONELINESS = r"^(plh0407|plh0189|plj058[7-9]|jl184[5-7]|jl1920|ylh0074|spisa6|jl1898|ylh0070|bjp_lmore295)"
MENTAL = (r"^(plh03(39|4[0-2])|ple002[78]|ple003[34]|ple0019|mcs|mh_nbs|plh0185|plm0555i02"
          r"|ple0192i02|ple0193i02|ple0219i04|jl182[1-4])")
TRUST_INSTITUTIONS = r"^(plh0421|plm067[2-5])"
STAY = r"^(plj008[4-8]|jl1497|ylm000[56]|plj0598|f1501)"
WELCOME = r"^(plj059[12]|lr3659|lr3660|lr3175|welcp|welcnow|plm0628|ylm0008)"
BELONGING = r"^(plj0078|plm0579|plj0082|plm0656|plm0659|plm0721i06|plm0722i06|plm0628|plj059[12]|lr3659|lr3660|ylm000[89])"
GERMAN = r"^(plj006[67]|plj007[1-3]|lb087[1-3]|lb119[1-3]|lb054[45]|lr2089|gskl[1-4]|gbfimmi|clg004[1-3]|clj0030)"
GERMAN_LABEL = r"deutsch (sprechen|schreiben|lesen)|(spoken|written) german|german (speaking|writing|reading)|deutschkenntnis"
VOLUNTEERING = r"^(pli0096|pghonor|plb062[3-5]|plb0618|plb0619|plh0167|jl0072|bjp_lmore245)"
CARE = r"^(pli0046|pli0055|pli0057|ple017[45]|hlf0291|hlf0631|hle0015|hle0025|plb0315|hlf032[34])"
ALCOHOL = r"^(ple017[78]|ple009[0-3])$"
FAIR_PAY = r"^(plh0337|plh0338|plh0137|plh0138|plh0140|plc000[3-7])"
HOMEOFFICE = r"^(plb009[5-7]|plb0697|plb0722|plb073[1-3]|plb0723|plg033[34]|elb0740)"
COMMUTE = r"^(plb014[2-6]|plb015[6-9]|plb0590|plb0591|plb0592|plb0165|plb0353|itray)"
HOUSEWORK = r"^(pli0012|pli0016|pli0043|plh0303|plh0323|plh0174)"
RELIGION = r"^(pli0098|plh0258|plh0437|plj0748|pgreli|lb1268|lr362[78])"
REFUGEE_ATTITUDE = r"^(plj043[3-7]|plj0046|plj0047)"

CASES = [
    ("Geschlechterrollen", GENDER, None),
    ("Einstellungen zur Rolle von Frauen und Männern in Familie und Beruf", GENDER, None),
    ("attitudes towards gender roles", GENDER, None),
    ("Sollten Mütter mit kleinen Kindern erwerbstätig sein?", r"^(plh0298|plh0302|plh0309|lb1110|lb1114|lb1121)", None),

    ("Diskriminierung", DISCRIMINATION, None),
    ("Diskriminierungserfahrungen", DISCRIMINATION, None),
    ("experiences of discrimination", DISCRIMINATION, None),
    ("Wird man wegen seiner Herkunft schlechter behandelt?", ORIGIN_DISCRIMINATION, None),
    ("Rassismus im Alltag", ORIGIN_DISCRIMINATION + r"|^plj0047", None),
    ("Ungleichbehandlung am Arbeitsplatz", r"^(plj0338|plj0229|plm0144i07|plh0411i01|plb0338|plh0405i02|elb0368)", None),

    ("Einsamkeit", LONELINESS, None),
    ("loneliness", LONELINESS, None),
    ("Wie oft fehlt Menschen die Gesellschaft anderer?", LONELINESS, None),

    ("psychische Gesundheit", MENTAL, None),
    ("mental health", MENTAL, None),
    ("Depressivität und Niedergeschlagenheit", r"^(plh0340|plh0339|ple0019|ple0027|plm0555i02|jl182[1-4]|mcs)", None),

    ("Vertrauen in Institutionen", TRUST_INSTITUTIONS, None),
    ("trust in institutions", TRUST_INSTITUTIONS, None),
    ("Wie sehr vertrauen die Menschen Polizei, Gerichten und Parteien?", TRUST_INSTITUTIONS, None),

    ("Bleibeabsicht", STAY, None),
    ("settlement intentions of immigrants", STAY, None),
    ("Wollen Zugewanderte dauerhaft in Deutschland bleiben?", STAY, None),

    ("Willkommenskultur", WELCOME, None),
    ("feeling welcome in Germany", WELCOME, None),
    ("Zugehörigkeitsgefühl zu Deutschland", BELONGING, None),
    ("identification with Germany", BELONGING, None),

    ("Deutschkenntnisse", GERMAN, GERMAN_LABEL),
    ("How well do immigrants speak German?", GERMAN, GERMAN_LABEL),

    ("Ehrenamt", VOLUNTEERING, None),
    ("volunteering", VOLUNTEERING, None),

    ("Pflege von Angehörigen", CARE, None),
    ("informal care for relatives", CARE, None),

    ("Alkoholkonsum", ALCOHOL, None),
    ("Wie oft trinken die Leute Alkohol?", ALCOHOL, None),

    ("Wie lange schlafen die Menschen?", r"^(pli0059|pli0060)$", None),
    ("Sorgen über den Klimawandel", r"^(plh0037|plh0036)$", None),
    ("Angst vor Kriminalität", r"^(plh0040|hlf0151|hlf068[01])$", None),
    ("Sorgen um die eigene finanzielle Lage", r"^(plh0033|plh0335)$", None),
    ("Einstellung zu Geflüchteten", REFUGEE_ATTITUDE, None),

    ("Ist das eigene Einkommen gerecht?", FAIR_PAY, None),
    ("perceived fairness of one's own pay", FAIR_PAY, None),

    ("Homeoffice", HOMEOFFICE, None),
    ("Pendeln zur Arbeit", COMMUTE, None),
    ("Zeit für Hausarbeit", HOUSEWORK, None),
    ("Religiosität und Kirchgang", RELIGION, None),
    ("Vegetarismus", r"^(ple0182)$", None),
]


def battery(item: str):
    """A result's battery: dataset plus variable stem, the key the finder folds batteries by."""
    from app.services.soep_rag_advisor import SOEP_BATTERY_NAME
    dataset, _, name = item.partition(":")
    match = SOEP_BATTERY_NAME.match(name)
    return (dataset, match.group(1).lower()) if match else item


def evaluate(service, cases, top_k: int, include_raw: bool = False):
    """Per case: rank of the first relevant hit, P@10, and DR@10, the number of DIFFERENT relevant
    variables or batteries among the first ten. P@10 counts ten items of one battery ten times;
    DR@10 counts them once, which is what a reader exploring a topic gets out of the first screen."""
    results = []
    for query, name_pattern, label_pattern in cases:
        response = service.answer_research_question(query, top_k=top_k, filters={"include_raw": include_raw})
        rows = response["recommended_variables"]
        flags = [matches(row, name_pattern, label_pattern) for row in rows]
        rank = next((i + 1 for i, hit in enumerate(flags) if hit), None)
        ids = [f"{r.get('dataset', '')}:{r.get('variable_name', '')}" for r in rows]
        results.append({
            "query": query, "rank": rank, "p_at_10": sum(flags[:10]) / 10,
            "dr_at_10": len({battery(i) for i, hit in zip(ids[:10], flags[:10]) if hit}),
            "top": [f"{r.get('dataset', '')}:{r.get('variable_name', '')}" for r in rows[:10]],
            "ranked": [f"{r.get('dataset', '')}:{r.get('variable_name', '')}" for r in rows],
            "top_label": str(rows[0].get("label", "")) if rows else "",
        })
    return results


def summarise(results):
    found = [r for r in results if r["rank"]]
    return {
        "queries": len(results),
        "hit@1": sum(1 for r in found if r["rank"] == 1),
        "hit@3": sum(1 for r in found if r["rank"] <= 3),
        "hit@10": sum(1 for r in found if r["rank"] <= 10),
        "mrr": round(sum(1 / r["rank"] for r in found) / len(results), 3),
        "p@10": round(sum(r["p_at_10"] for r in results) / len(results), 3),
        "dr@10": round(sum(r["dr_at_10"] for r in results) / len(results), 2),
        "misses": [r["query"] for r in results if not r["rank"] or r["rank"] > 10],
    }


def compare(path_a: str, path_b: str, resamples: int = 20000) -> None:
    """Paired bootstrap of B minus A over the same queries: reciprocal rank, and DR@10 where both
    files have it. Works on the --json-out of this script and of eval_soep_search.py. Overlapping
    marginal intervals say nothing about a difference measured on the same queries; this does."""
    import numpy as np
    a = json.loads(Path(path_a).read_text(encoding="utf-8"))["results"]
    b = json.loads(Path(path_b).read_text(encoding="utf-8"))["results"]
    if [r["query"] for r in a] != [r["query"] for r in b]:
        raise SystemExit("the two files do not hold the same queries in the same order")
    rng = np.random.default_rng(7)
    index = rng.integers(0, len(a), (resamples, len(a)))
    metrics = {"reciprocal rank": lambda r: 1 / r["rank"] if r["rank"] else 0.0}
    if all("dr_at_10" in r for r in a + b):
        metrics["DR@10"] = lambda r: r["dr_at_10"]
    for name, value in metrics.items():
        diff = np.array([value(y) - value(x) for x, y in zip(a, b)])
        means = diff[index].mean(axis=1)
        print(f"{name}: {diff.mean():+.3f}, 95% interval {np.percentile(means, 2.5):+.3f} "
              f"to {np.percentile(means, 97.5):+.3f} (n={len(diff)})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=20, help="results per query, as the UI asks for")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--include-raw", action="store_true")
    parser.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"),
                        help="paired bootstrap of B minus A from two earlier --json-out files; loads no model")
    args = parser.parse_args()
    if args.compare:
        compare(*args.compare)
        return

    from app.services.soep_rag_advisor import SOEPRagAdvisorService

    service = SOEPRagAdvisorService()
    service.load()
    path = str(service.metadata_path or "")
    if "v41" not in path:
        raise SystemExit(f"loaded {path or 'no metadata'}, which is not the v41 corpus; "
                         "set SOEP_RAG_METADATA_PATH as in the docstring")
    print(f"rows={len(service._rows)} corpus={path} model={service.model_name} "
          f"reranker={service._reranker_name}\n")

    results = evaluate(service, CASES, args.top_k, args.include_raw)
    for r in results:
        mark = "  ok " if r["rank"] == 1 else (f"  #{r['rank']:<2}" if r["rank"] else "  MISS")
        print(f"{mark} P@10={r['p_at_10']:.1f} DR@10={r['dr_at_10']:>2}  {r['query'][:46]:<46} "
              f"-> {r['top'][0] if r['top'] else ''}")
    summary = summarise(results)
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"summary": summary, "results": results},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
