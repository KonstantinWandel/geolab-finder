#!/usr/bin/env python3
"""Retrieval smoke test for the GeoDB finder.

A fixed set of concept queries with an expected hit, expressed as a regex over
`variable_name`/`label` plus (optionally) the source it should come from. Prints the rank
of the first acceptable hit per query and hit@1 / hit@3 / hit@10 overall, so a change to
the embedding model, the document construction, or the record set can be compared against
a previous run instead of eyeballed.

Run (loads the model, so give it a minute):
  GEOLAB_APP_MODE=inkar INKAR_METADATA_ROOT=$PWD/soep_metadata_output \
  SOEP_METADATA_ROOT=$PWD/soep_metadata_output SOEP_RAG_DEVICE=cuda \
  python scripts/eval_geodb_search.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.soep_rag_advisor import SOEPRagAdvisorService  # noqa: E402

# (query, expected-label/code regex, allowed source_keys or None for any)
CASES = [
    ("Breitbandverfügbarkeit auf Gemeindeebene", r"breitband|gigabit|100 ?mbit", None),
    ("Ärztedichte je Einwohner", r"ärzt|arzt", None),
    ("Krankenhausbetten je Einwohner", r"bett", None),
    ("Krankenhäuser mit Stroke Unit", r"strokeunit|stroke", {"bundes_klinik_atlas"}),
    ("Pflegepersonal je Klinik", r"pfleg", None),
    ("Qualitätsindikatoren der Krankenhäuser", r"qualitaet|qualität", {"gba_qualitaetsbericht", "bundes_klinik_atlas"}),
    ("Erreichbarkeit der nächsten Apotheke", r"apothek", None),
    ("Pkw-Dichte je 1000 Einwohner", r"pkw|auto", None),
    ("Betreuungsquote Kinder unter drei Jahren", r"betreu|kita|kinder", None),
    ("Strukturdaten der Bundestagswahlkreise", r".", {"btw_strukturdaten"}),
    ("Ausländeranteil im Kreis", r"ausl|migration|staatsang", None),
    ("Studierende und Hochschulstandorte", r"stud|hochschul", None),
    ("ÖPNV Haltestellen und Fahrpläne", r"haltestelle|fahrplan|öpnv|oepnv", None),
    ("Unternehmen und Gewerbeanmeldungen", r"unternehmen|gewerbe|firm", None),
    ("Arbeitslosenquote auf Kreisebene", r"arbeitslos|erwerbslos", None),
    ("Bruttoinlandsprodukt je Einwohner", r"bruttoinlandsprodukt|bip", None),
    ("Anteil der Waldfläche", r"wald", None),
    ("Angebotsmieten und Mietpreise", r"miet", None),
    ("Lebenserwartung bei Geburt", r"lebenserwartung", None),
    ("Spielplätze in der Umgebung", r"spielplatz", None),
    ("Personalschlüssel in Kindertagesstätten", r"personalschlüssel|personal", {"laendermonitor"}),
    ("Bevölkerungsdichte je Quadratkilometer", r"dicht", None),
    ("Schulabgänger ohne Abschluss", r"schulabg|abschluss|hauptschul", None),
    ("Pendler zwischen Wohnort und Arbeitsort", r"pendl", None),
    ("Wohnfläche je Einwohner", r"wohnfl", None),
    ("Barrierefreiheit von Krankenhäusern", r"barriere", None),
    ("Erneuerbare Energien und Flächennutzung", r"energie|fläche|flaeche", None),
    ("Kaufkraft und verfügbares Einkommen", r"einkommen|kaufkraft", None),
    # --- second block, added 2026-08-25: English phrasing, the newer sources, and cases where a
    # real indicator must beat a portal card. Kept in the same list so one number covers both.
    ("hospital beds per inhabitant", r"bett", None),
    ("broadband availability 1000 Mbit households", r"1000|gigabit|ftth", None),
    ("population by age and sex", r"alter|age|geschlecht|sex", None),
    ("dwellings by year of construction", r"baujahr|wohnung", {"zensus2022"}),
    ("road accidents involving cyclists", r"rad|fahrrad", {"unfallatlas"}),
    ("commuters into the district", r"pendl|einpendl", None),
    ("share of foreigners", r"ausl|migration|staatsang", None),
    ("municipal debt per inhabitant", r"schuld", None),
    ("gross domestic product per capita", r"bruttoinlandsprodukt|bip", None),
    ("childcare coverage under three", r"betreu|kita|kinder", None),
    ("Anteil Erneuerbarer Energien", r"energie|erneuerbar|strom", None),
    ("Krankenhäuser mit Geburtshilfe", r"geburt|entbind|krankenhaus", None),
    ("Zahl der Beschäftigten nach Wirtschaftszweig", r"beschäft|wirtschaftszweig", None),
    ("Wanderungssaldo je 1000 Einwohner", r"wander|zuzug|fortzug", None),
    ("Wahlbeteiligung", r"wahlbeteiligung|wähler|wahlberecht", None),
    ("Bodenrichtwerte und Grundstückspreise", r"boden|grundstück|kaufwert", None),
    ("Ärztliche Versorgung auf dem Land", r"arzt|ärzt|hausarzt", None),
    ("Pflegebedürftige und Pflegeheime", r"pflege", None),
    ("Zahl der Studierenden", r"stud", None),
    ("Kriminalität und Straftaten", r"straftat|kriminal|sicherheit", None),
    ("Fläche für Siedlung und Verkehr", r"siedlung|verkehrsfläche|fläche", None),
    ("Durchschnittsalter der Bevölkerung", r"alter", None),
    ("Zahl der Gewerbeanmeldungen", r"gewerbe", None),
    ("Erwerbstätigenquote von Frauen", r"frau|erwerb|beschäftig", None),
    ("Anteil Ein-Personen-Haushalte", r"haushalt", None),
    ("Mobilfunkabdeckung 5G", r"5g|mobilfunk", None),
    ("Reisezeit zum nächsten Oberzentrum", r"erreichbar|distanz|zentrum|fahrzeit", None),
    ("Zahl der Übernachtungen im Tourismus", r"übernacht|tourism|beherberg", None),
    ("Sozialhilfe und Grundsicherung", r"grundsicher|sozialhilfe|sozialleist", None),
    ("Schulabbrecherquote", r"schulabg|abschluss|abbrech", None),
]


def matches(row: dict, pattern: str, sources) -> bool:
    if sources and row.get("source_key") not in sources:
        return False
    haystack = f"{row.get('variable_name', '')} {row.get('label', '')}".lower()
    return re.search(pattern, haystack, re.I) is not None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    service = SOEPRagAdvisorService()
    service.load()
    print(f"rows={len(service._rows)} model={service.model_name} reranker={service._reranker_name}\n")

    results = []
    for query, pattern, sources in CASES:
        response = service.answer_research_question(query, top_k=args.top_k)
        rows = response["recommended_variables"]
        rank = next((i + 1 for i, row in enumerate(rows) if matches(row, pattern, sources)), None)
        top = rows[0] if rows else {}
        results.append({
            "query": query, "rank": rank,
            "top_source": top.get("source_key", ""), "top_label": top.get("label", ""),
            "sources_in_top": sorted({row.get("source_key", "") for row in rows}),
        })
        mark = "  ok " if rank == 1 else (f"  #{rank} " if rank else "  MISS")
        print(f"{mark} {query[:48]:<48} -> [{top.get('source_key', ''):<20}] {top.get('label', '')[:46]}")

    found = [r for r in results if r["rank"]]
    summary = {
        "queries": len(results),
        "hit@1": sum(1 for r in found if r["rank"] == 1),
        "hit@3": sum(1 for r in found if r["rank"] <= 3),
        "hit@10": len(found),
        "misses": [r["query"] for r in results if not r["rank"]],
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"summary": summary, "results": results},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
