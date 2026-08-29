#!/usr/bin/env python3
"""Retrieval smoke test for the SOEP Variable Finder.

The GeoDB finder has had a gate since 2026-08-25; the SOEP finder had none, so no change to it
(model, document construction, enrichment, filters) could be told apart from a regression. This
is that gate.

Each case is a plain-language query plus the variable names that would be a correct answer. The
gold variables were not written from memory: every one was looked up in the built v41 metadata
first, so a case failing means retrieval missed it, not that the variable does not exist.

Several variables are often equally right (`plh0151` and `pequiv p11101` both ARE life
satisfaction), so a case accepts a set. Where the concept is a battery or a harmonised family,
the pattern matches the family (`plh0212`..) rather than one arbitrary member.

Run (loads the model, so give it a minute):
  GEOLAB_APP_MODE=soep SOEP_METADATA_ROOT=$PWD/soep_metadata_output \
  SOEP_RAG_METADATA_PATH=$PWD/soep_metadata_output/soep_v41_metadata.json \
  SOEP_RAG_CACHE_DIR=$PWD/soep_metadata_output/cache SOEP_RAG_DEVICE=cuda \
  python scripts/eval_soep_search.py
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

# (query, regex over variable_name, optional regex over the label as a fallback)
# German first, then the same corpus asked in English, then the awkward cases.
CASES = [
    # --- core socio-economics
    # plc0013/plc0014 is the survey item for exactly this; pglabnet the generated version.
    # Both are correct answers, so both count.
    ("Nettoerwerbseinkommen im letzten Monat", r"^(pglabnet|pglabgro|i11110|plc001[34])", None),
    ("Bruttoerwerbseinkommen aus Haupttätigkeit", r"^(pglabgro|i11110)$", None),
    ("monatliches Haushaltsnettoeinkommen", r"^(hghinc|i11102|hlc0005)", None),
    ("bedarfsgewichtetes Haushaltseinkommen", r"^(i11102|d11106|hghinc)", None),
    # pgbilzt does not exist; the variable is pgbilzeit ("Dauer der Ausbildung, in Jahren").
    # The first run of this eval marked a rank-1 answer as a miss because of that typo.
    ("Bildungsjahre einer Person", r"^(d11109|pgbilzeit)$", None),
    ("höchster Schulabschluss", r"^(pgpsbil|pgcasmin|isced|d11108)", r"schulabschl|casmin|isced"),
    ("berufliche Stellung", r"^(pgstib|e11105)", r"stellung im beruf|occupational position"),
    ("Beruf nach ISCO-Klassifikation", r"^(pgisco|isco)", r"isco"),
    ("Beruf nach KldB 2010", r"kldb", r"kldb"),
    ("tatsächliche Arbeitszeit pro Woche", r"^(pgtatzeit|plb0186)", r"tats.chliche arbeitszeit"),
    ("vereinbarte Wochenarbeitszeit", r"^(pgvebzeit|plb0176|plc0455)", r"vereinbarte arbeitszeit"),
    ("Beschäftigungsstatus und Erwerbsstatus", r"^(pgemplst|pglfs|e11102)$", None),
    ("arbeitslos gemeldet", r"^(plb0021|pab0004|e11103)", r"arbeitslos gemeldet"),
    ("Nettovermögen des Haushalts", r"^(w011h[a-e]|w0111[a-e])$", None),
    ("Wohnfläche der Wohnung in Quadratmetern", r"^(hgsize|hlf0019)", r"wohnfl"),
    ("Miete pro Monat", r"^(hlj0028|hgrent|hlf00)", r"^miete|bruttokaltmiete|rent"),
    ("Wohneigentum oder Mieter", r"^(hgowner|plc0342)", r"eigentüm|wohneigentum|owner"),

    # --- health, wellbeing, personality
    ("allgemeiner Gesundheitszustand", r"^(ple0008|m11126)$", None),
    ("Lebenszufriedenheit heute", r"^(plh0182|plh0151|p11101)$", None),
    ("Zufriedenheit mit dem Haushaltseinkommen", r"^(plh0175)$", None),
    ("Rauchen und Zigarettenkonsum", r"^(ple008[0-9])", r"rauch|smok|zigarett"),
    ("wie oft wird Fleisch gegessen", r"^(ple0179|hlf0192)$", None),
    ("Sport und körperliche Aktivität", r"^(ple0027|pli0090|plh0245)", r"sport"),
    ("Big Five Persönlichkeitsmerkmale", r"^plh02(1[2-9]|2[0-9])", r"personality|selbsteinsch"),
    ("Risikobereitschaft", r"^plh0(19[5-9]|20[0-9])", r"risikobereitschaft|risk"),
    ("allgemeines Vertrauen in andere Menschen", r"^(plh0192|plh019[0-9])", r"vertrauen|trust"),
    ("Locus of Control, Kontrollüberzeugung", r"^plh03(7[0-9]|8[0-9])", r"kontroll|locus"),
    ("Pflegebedürftige Person im Haushalt", r"^(hlf0291|plb0315|hlf0293)", r"pflegebed"),

    # --- household, family, biography
    ("Anzahl der Kinder einer Person", r"^(sumkids|pld0172|d11107)$", None),
    ("Geburtsjahr der befragten Person", r"^(gebjahr|geburt)", r"geburtsjahr|year of birth"),
    ("Geschlecht der befragten Person", r"^(sex|pgsex|d11102)", r"geschlecht|gender|sex"),
    ("Haushaltsgröße, Zahl der Personen", r"^(hhgr|d11106|hgtyp)", r"haushaltsgr|household size|personen im"),
    ("Familienstand", r"^(pgfamstd|d11104)$", None),
    ("Migrationshintergrund", r"^(migback|mig)", r"migrationshintergrund|migration background"),
    ("Staatsangehörigkeit", r"^(pgnation|corigin)", r"staatsang|nationality|citizenship"),
    ("Partner im Haushalt", r"^(partz|parid|pld0)", r"partner"),

    # --- attitudes, politics, region
    ("Interesse an Politik", r"^(plh0007|plm0564)$", None),
    ("Parteineigung", r"^plh001[0-9]", r"parteineigung|party"),
    ("Religionszugehörigkeit", r"^plh0(25[0-9]|10[0-9])", r"religion|konfession|kirche"),
    ("Bundesland des Haushalts", r"^(bula|hgnuts1)", r"bundesland|federal state"),
    ("Gewichtungsfaktor für Hochrechnungen", r"^(phrf|hhrf|pbleib|hbleib)", r"hochrechnungsfaktor|weight"),
    # syear is a key column, indexed for only two datasets; erhebj/iyear are the real answers.
    ("Erhebungsjahr der Befragung", r"^(syear|erhebj|iyear)$", None),

    # --- the same corpus asked in English
    ("net labour income last month", r"^(pglabnet|i11110|plc001[34])", None),
    ("years of education", r"^(d11109|pgbilzeit)$", None),
    ("current self-rated health", r"^(ple0008|m11126)$", None),
    ("overall life satisfaction", r"^(p11101|plh0182|plh0151)$", None),
    ("household net wealth", r"^(w011h[a-e]|w0111[a-e])$", None),
    ("actual weekly working hours", r"^(pgtatzeit|plb0186)", r"actual work"),
    ("employment status of the individual", r"^(e11102|pgemplst|pglfs)$", None),
    ("frequency of meat consumption", r"^(ple0179|hlf0192)$", None),
    ("political interest", r"^(plh0007|plm0564)$", None),
    ("migration background of the respondent", r"^(migback|mig)", r"migration background"),
    ("number of children in the household", r"^(sumkids|d11107|pld0172)$", None),
    ("size of the dwelling in square metres", r"^(hgsize|hlf0019)", r"floor space|wohnfl"),

    # --- harder: the query names a concept, not the label
    ("wie viel verdient jemand netto im Monat", r"^(pglabnet|i11110|plc0013)", r"netto"),
    ("wie zufrieden sind die Leute mit ihrem Leben", r"^(plh0182|plh0151|p11101)$", None),
    ("Bildungsabschluss der Eltern", r"^(bioparen|fsedu|msedu|fprofstat|mprofstat)", r"vater|mutter|father|mother"),
    ("Einkommensarmut und Armutsgefährdung", r"^(i11102|d11106|pequiv)", r"armut|poverty|income"),
    ("Wohnort in Ost- oder Westdeutschland", r"^(bula_ew|sampreg|loc1989)", r"ost|west|east"),
]


def matches(row: dict, name_pattern: str, label_pattern: str | None) -> bool:
    name = str(row.get("variable_name", ""))
    if re.search(name_pattern, name, re.I):
        return True
    if label_pattern:
        label = f"{row.get('label', '')} {row.get('label_en', '')}"
        return re.search(label_pattern, label, re.I) is not None
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--any-corpus", action="store_true",
                        help="allow a corpus other than v41 (normally a mistake)")
    parser.add_argument("--include-raw", action="store_true",
                        help="also search the raw questionnaire files (off, like the UI default)")
    args = parser.parse_args()

    service = SOEPRagAdvisorService()
    service.load()
    path = str(service.metadata_path or "")
    print(f"rows={len(service._rows)} corpus={path} model={service.model_name} "
          f"reranker={service._reranker_name}\n")
    # Without SOEP_RAG_METADATA_PATH the service falls back to the pre-v41 file (22,097 rows)
    # and every number here would describe a corpus nobody serves. Production sets the variable
    # in its systemd unit; this refuses to produce numbers for the wrong corpus.
    if not args.any_corpus and "v41" not in path:
        raise SystemExit(
            f"loaded {path or 'no metadata'} ({len(service._rows)} rows), which is not the v41 "
            "corpus. Set SOEP_RAG_METADATA_PATH=$PWD/soep_metadata_output/soep_v41_metadata.json "
            "(or pass --any-corpus deliberately).")

    results = []
    for query, name_pattern, label_pattern in CASES:
        # include_raw goes through `filters`, exactly as the API passes the UI checkbox.
        response = service.answer_research_question(
            query, top_k=args.top_k, filters={"include_raw": args.include_raw})
        rows = response["recommended_variables"]
        rank = next((i + 1 for i, row in enumerate(rows)
                     if matches(row, name_pattern, label_pattern)), None)
        top = rows[0] if rows else {}
        results.append({
            "query": query, "rank": rank,
            "top_variable": top.get("variable_name", ""), "top_label": top.get("label", ""),
            "top_dataset": top.get("dataset", ""),
        })
        mark = "  ok " if rank == 1 else (f"  #{rank} " if rank else "  MISS")
        print(f"{mark} {query[:46]:<46} -> {top.get('dataset', ''):<10} "
              f"{top.get('variable_name', ''):<14} {str(top.get('label', ''))[:38]}")

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
