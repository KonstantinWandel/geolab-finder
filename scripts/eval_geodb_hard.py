#!/usr/bin/env python3
"""The hard half of the GeoDB retrieval gate.

`eval_geodb_search.py` is a smoke test: most of its queries contain a word that also appears in
the target label, so a lexical matcher would pass much of it. This file is the opposite. Every
case is built so that keyword overlap does NOT decide it:

  concept        the query names an outcome, never the indicator ("wo muss man am weitesten
                 fahren, um einzukaufen" -> Erreichbarkeit / Nahversorgung)
  lay            how a non-specialist asks ("gibt es hier genug Kita-Plätze")
  crosslingual   English question, German label, no cognate to latch onto
  discrimination two neighbouring concepts that are routinely confused; the wrong one is named
                 explicitly as `reject`, so trading one for the other is a failure, not a hit
  constraint     the answer has to carry a property (spatial level, year coverage, source),
                 checked against the record's own fields rather than its wording
  code           the record is asked for by its code
  negative       the index genuinely does not hold this. Nothing can be a "hit"; what is
                 measured is whether the finder answers with a confident wrong record.

A negative case therefore has no rank. It reports the top score and whether the top hit matches
its `reject` pattern, which is what "the finder invents an answer" looks like from the outside.

Runs against the deployed service by default, because that is what a user meets:

    python scripts/eval_geodb_hard.py --api https://geodb.geolab.soz.uni-bielefeld.de/api

or in-process against this checkout (loads the model, needs the metadata env vars):

    GEOLAB_APP_MODE=inkar INKAR_METADATA_ROOT=$PWD/soep_metadata_output \\
    SOEP_METADATA_ROOT=$PWD/soep_metadata_output SOEP_RAG_DEVICE=cuda \\
    SOEP_RAG_CACHE_DIR=$PWD/soep_metadata_output/cache python scripts/eval_geodb_hard.py
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

warnings.filterwarnings("ignore")

# kind, query, accept regex over name+label, reject regex, allowed sources, structural requirement
CASES: List[Dict[str, Any]] = [
    # ---------- concept: the indicator's own vocabulary is absent from the question
    dict(kind="concept", query="wo müssen Menschen am weitesten fahren, um einzukaufen",
         accept=r"erreichbar|nahversorg|supermarkt|lebensmittel|distanz|entfernung|fahrzeit"),
    dict(kind="concept", query="in welchen Regionen sterben die Menschen früher",
         accept=r"lebenserwartung|sterb|mortalit|todes"),
    dict(kind="concept", query="wo ziehen mehr Leute weg als hin",
         accept=r"wander|fortzug|zuzug|saldo|abwanderung"),
    dict(kind="concept", query="Gegenden, in denen viele Menschen von staatlicher Unterstützung leben",
         accept=r"grundsicher|sgb|arbeitslosengeld|sozial|mindestsicher|leistungsempf|hilfe"),
    dict(kind="concept", query="wie stark ist eine Region vom Verarbeitenden Gewerbe abhängig",
         accept=r"verarbeitendes gewerbe|industrie|beschäft|wirtschaftszweig|bruttowertsch"),
    dict(kind="concept", query="Orte, an denen kaum junge Familien wohnen",
         accept=r"alter|jugend|kinder|geburt|altersstruktur|durchschnittsalter|bevölkerung"),
    dict(kind="concept", query="wie teuer ist es, dort zu wohnen",
         accept=r"miet|wohnkosten|kaufwert|bodenrichtwert|preis|belastung"),
    dict(kind="concept", query="Regionen mit schlechter Internetversorgung",
         accept=r"breitband|gigabit|mbit|ftth|versorg|mobilfunk|5g|lte"),

    # ---------- lay phrasing
    dict(kind="lay", query="gibt es hier genug Kita-Plätze",
         accept=r"betreu|kita|kinderta|kinderbetreu|plätze"),
    dict(kind="lay", query="wie viele Leute haben keinen Job",
         accept=r"arbeitslos|erwerbslos|beschäftigungslos|unterbeschäft"),
    dict(kind="lay", query="ist die Gegend eher arm oder reich",
         accept=r"einkommen|kaufkraft|armut|verfügbares|bip|bruttoinlandsprodukt"),
    # Land use is not traffic volume: "Anteil Straßenverkehrsfläche" passed the first version
    # of this case on the word "verkehr" alone.
    dict(kind="lay", query="wie voll sind die Straßen",
         accept=r"pkw|kfz|motorisier|fahrzeug|pendl|verkehrsaufkommen|verkehrsleistung|stau",
         reject=r"verkehrsfläche|siedlungsfläche|flächenanteil"),
    # "grün" also names a party, and the first version of this case accepted
    # "Zweitstimmenanteil GRÜNE" as a hit. The pun is exactly what has to fail here.
    dict(kind="lay", query="wie grün ist die Gemeinde",
         accept=r"wald|erholung|freifläche|vegetation|grünfläche|landwirtschaftsfl|siedlungs- und verkehrsfl",
         reject=r"zweitstimme|erststimme|partei|wahl"),

    # ---------- crosslingual: English question, German record
    dict(kind="crosslingual", query="share of dwellings heated with gas",
         accept=r"heiz|energieträger|gas", sources={"zensus2022"}),
    dict(kind="crosslingual", query="how far is the nearest general practitioner",
         accept=r"arzt|ärzt|hausarzt|erreichbar|versorgung"),
    dict(kind="crosslingual", query="deaths caused by traffic accidents",
         accept=r"unfall|verunglück|getötet|verkehrstot"),
    dict(kind="crosslingual", query="apprenticeship and vocational training places",
         accept=r"ausbildung|azubi|lehrstelle|berufsausbild"),
    dict(kind="crosslingual", query="land prices for building plots",
         accept=r"bodenrichtwert|baugrund|grundstück|kaufwert|bauland"),

    # ---------- discrimination: the neighbour must not win
    dict(kind="discrimination", query="Zahl der Pflegekräfte in Krankenhäusern",
         accept=r"pflegekraft|pflegepersonal|personal|beschäftigt", reject=r"pflegebedürftig|pflegequote"),
    dict(kind="discrimination", query="Bodenrichtwerte, nicht Mieten",
         accept=r"bodenrichtwert|boden|grundstück|kaufwert", reject=r"^miete|mietpreis|angebotsmiete"),
    dict(kind="discrimination", query="Erwerbslosenquote nach ILO-Konzept, nicht die BA-Arbeitslosenquote",
         accept=r"erwerbslos|ilo", reject=r"^arbeitslosenquote$"),
    dict(kind="discrimination", query="fertiggestellte Wohnungen im Jahr, nicht der Wohnungsbestand",
         accept=r"baufertig|fertiggestellt|baugenehmig|neubau", reject=r"wohnungsbestand|bestand an wohn"),
    dict(kind="discrimination", query="Anteil der Bevölkerung mit ausländischer Staatsangehörigkeit, nicht mit Migrationshintergrund",
         accept=r"ausländ|staatsangehörig|nichtdeutsch", reject=r"migrationshintergrund|mhg"),

    # ---------- constraint: a property of the record has to hold
    dict(kind="constraint", query="Bevölkerungszahl auf Gemeindeebene",
         accept=r"bevölker|einwohner", require={"spatial": r"gemeinde|lau"}),
    dict(kind="constraint", query="Breitbanddaten als Rasterzellen",
         accept=r"breitband|gigabit|raster|mbit", require={"spatial": r"raster|grid|100 ?m|gitter"}),
    dict(kind="constraint", query="Arbeitsmarktzahlen aus der amtlichen Arbeitsmarktstatistik der Bundesagentur",
         accept=r"arbeitslos|beschäft|arbeitsmarkt", require={"source": r"^ba_|bundesagentur|arbeitsagentur"}),
    dict(kind="constraint", query="Zensus 2022 Ergebnisse zur Wohnsituation",
         accept=r"wohn|gebäude|haushalt", require={"source": r"zensus"}),
    dict(kind="constraint", query="Indikator mit einer langen Zeitreihe seit den 1990er Jahren",
         accept=r".", require={"year_before": 2000}),

    # ---------- code lookups
    dict(kind="code", query="AI1401", accept=r"ai1401|krankenhausbett"),
    dict(kind="code", query="INT251", accept=r"int251|krankenhausbett"),
    dict(kind="code", query="Merkmal 12411 Bevölkerungsstand", accept=r"12411|bevölkerungsstand|bevölker"),

    # ---------- negative controls: the index does not hold these
    dict(kind="negative", query="Anteil vegetarisch lebender Personen je Kreis",
         reject=r"vegetar|ernährung"),
    dict(kind="negative", query="durchschnittliche Zahl der Katzen pro Haushalt",
         reject=r"katze|haustier"),
    dict(kind="negative", query="Twitter-Sentiment der Bevölkerung je Gemeinde",
         reject=r"twitter|sentiment|social media"),
    dict(kind="negative", query="Zufriedenheit der Befragten mit ihrem Leben",
         reject=r"lebenszufriedenheit|zufriedenheit"),
    dict(kind="negative", query="Anteil der Haushalte mit einem Balkon",
         reject=r"balkon"),
]

API_TIMEOUT = 120


def ask_api(api: str, question: str, top_k: int) -> Dict[str, Any]:
    body = json.dumps({"question": question, "top_k": top_k, "dataset_scope": "all"}).encode()
    request = urllib.request.Request(f"{api.rstrip('/')}/soep/advice", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=API_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def haystack(row: Dict[str, Any]) -> str:
    return f"{row.get('variable_name', '')} {row.get('label', '')} {row.get('description', '')}".lower()


def accepts(row: Dict[str, Any], case: Dict[str, Any]) -> bool:
    if case.get("sources") and row.get("source_key") not in case["sources"]:
        return False
    if case.get("reject") and re.search(case["reject"], haystack(row), re.I):
        return False
    if case.get("accept") and not re.search(case["accept"], haystack(row), re.I):
        return False
    need = case.get("require") or {}
    if "spatial" in need:
        levels = " ".join(row.get("spatial_levels") or []) + " " + " ".join(row.get("nuts_levels") or [])
        if not re.search(need["spatial"], levels, re.I):
            return False
    if "source" in need and not re.search(need["source"], str(row.get("source_key", "")), re.I):
        return False
    if "year_before" in need:
        years = re.findall(r"(19|20)\d{2}", str(row.get("available_years_text", "")))
        found = [int(y) for y in re.findall(r"((?:19|20)\d{2})", str(row.get("available_years_text", "")))]
        if not found or min(found) >= need["year_before"]:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="", help="query a deployed service instead of loading the model")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--only", default="", help="run one kind only")
    args = parser.parse_args()

    service = None
    if not args.api:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from app.services.soep_rag_advisor import SOEPRagAdvisorService  # noqa: E402
        service = SOEPRagAdvisorService()
        service.load()
        print(f"in-process: rows={len(service._rows)} model={service.model_name} "
              f"reranker={service._reranker_name}\n")
    else:
        print(f"deployed service: {args.api}\n")

    cases = [c for c in CASES if not args.only or c["kind"] == args.only]
    results: List[Dict[str, Any]] = []
    for case in cases:
        started = time.time()
        if service is not None:
            response = service.answer_research_question(case["query"], top_k=args.top_k)
        else:
            response = ask_api(args.api, case["query"], args.top_k)
        elapsed = time.time() - started
        rows = response.get("recommended_variables") or []
        top = rows[0] if rows else {}

        entry: Dict[str, Any] = {
            "kind": case["kind"], "query": case["query"], "seconds": round(elapsed, 2),
            "top_label": top.get("label", ""), "top_source": top.get("source_key", ""),
            "top_score": top.get("score"), "top_link_level": top.get("link_level", ""),
        }
        if case["kind"] == "negative":
            # nothing here can be right; a hit on `reject` means it answered anyway
            entry["false_positive"] = bool(top and re.search(case["reject"], haystack(top), re.I))
            mark = "  FP  " if entry["false_positive"] else "  ok  "
        else:
            rank = next((i + 1 for i, row in enumerate(rows) if accepts(row, case)), None)
            entry["rank"] = rank
            mark = "  ok  " if rank == 1 else (f"  #{rank}  " if rank else "  MISS")
        results.append(entry)
        print(f"{mark}[{case['kind'][:6]:<6}] {case['query'][:52]:<52} -> "
              f"[{entry['top_source'][:16]:<16}] {str(entry['top_label'])[:40]}")

    graded = [r for r in results if r["kind"] != "negative"]
    found = [r for r in graded if r.get("rank")]
    negatives = [r for r in results if r["kind"] == "negative"]
    by_kind: Dict[str, Dict[str, int]] = {}
    for r in graded:
        bucket = by_kind.setdefault(r["kind"], {"n": 0, "hit@1": 0, "hit@3": 0, "hit@10": 0})
        bucket["n"] += 1
        if r.get("rank"):
            bucket["hit@10"] += 1
            if r["rank"] <= 3:
                bucket["hit@3"] += 1
            if r["rank"] == 1:
                bucket["hit@1"] += 1

    summary = {
        "graded_queries": len(graded),
        "hit@1": sum(1 for r in found if r["rank"] == 1),
        "hit@3": sum(1 for r in found if r["rank"] <= 3),
        "hit@10": len(found),
        "misses": [r["query"] for r in graded if not r.get("rank")],
        "by_kind": by_kind,
        "negative_controls": len(negatives),
        "false_positives": [r["query"] for r in negatives if r["false_positive"]],
        "seconds_median": round(statistics.median([r["seconds"] for r in results]), 2),
        "seconds_max": round(max(r["seconds"] for r in results), 2),
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"summary": summary, "results": results},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
