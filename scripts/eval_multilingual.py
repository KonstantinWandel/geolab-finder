#!/usr/bin/env python3
"""Does the index answer a question asked in a language it does not contain?

The documents are German (GeoDB) or German and English (SOEP); the bi-encoder,
multilingual-e5-large-instruct, is trained on about a hundred languages. Whether that carries a
Turkish or Ukrainian question to a German record is an empirical question, and it matters here:
the campus works with international researchers, and migration research in particular is done by
people who do not think in German.

Method: twelve questions from the German gate, each translated into nine languages, judged against
the SAME gold pattern as the German original. So the number for Polish is directly comparable to
the number for German, and the only thing that varies is the language of the question.

The translations were written by hand for this file, not machine-translated at run time, so a
failure is a retrieval failure and not a translation artefact. They are deliberately plain: this
measures the tool, not someone's phrasing.

    python scripts/eval_multilingual.py --api https://geodb.geolab.soz.uni-bielefeld.de/api
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

warnings.filterwarnings("ignore")

LANGUAGES = ["de", "en", "fr", "es", "it", "pl", "tr", "uk", "ar", "zh"]

# (gold pattern over variable_name + label, {language: question})
CASES = [
    (r"bett", {
        "de": "Krankenhausbetten je Einwohner",
        "en": "hospital beds per inhabitant",
        "fr": "lits d'hôpital par habitant",
        "es": "camas de hospital por habitante",
        "it": "posti letto ospedalieri per abitante",
        "pl": "łóżka szpitalne na mieszkańca",
        "tr": "kişi başına hastane yatağı",
        "uk": "лікарняні ліжка на одного жителя",
        "ar": "أسرة المستشفيات لكل ساكن",
        "zh": "每位居民的医院床位数",
    }),
    (r"arbeitslos|erwerbslos", {
        "de": "Arbeitslosenquote auf Kreisebene",
        "en": "unemployment rate by district",
        "fr": "taux de chômage par district",
        "es": "tasa de desempleo por distrito",
        "it": "tasso di disoccupazione per distretto",
        "pl": "stopa bezrobocia w powiatach",
        "tr": "ilçelere göre işsizlik oranı",
        "uk": "рівень безробіття по районах",
        "ar": "معدل البطالة حسب المنطقة",
        "zh": "各地区失业率",
    }),
    (r"dicht", {
        "de": "Bevölkerungsdichte je Quadratkilometer",
        "en": "population density per square kilometre",
        "fr": "densité de population par kilomètre carré",
        "es": "densidad de población por kilómetro cuadrado",
        "it": "densità di popolazione per chilometro quadrato",
        "pl": "gęstość zaludnienia na kilometr kwadratowy",
        "tr": "kilometrekare başına nüfus yoğunluğu",
        "uk": "щільність населення на квадратний кілометр",
        "ar": "الكثافة السكانية لكل كيلومتر مربع",
        "zh": "每平方公里人口密度",
    }),
    (r"lebenserwartung", {
        "de": "Lebenserwartung bei Geburt",
        "en": "life expectancy at birth",
        "fr": "espérance de vie à la naissance",
        "es": "esperanza de vida al nacer",
        "it": "speranza di vita alla nascita",
        "pl": "oczekiwana długość życia w chwili urodzenia",
        "tr": "doğuşta beklenen yaşam süresi",
        "uk": "очікувана тривалість життя при народженні",
        "ar": "متوسط العمر المتوقع عند الولادة",
        "zh": "出生时预期寿命",
    }),
    (r"betreu|kita|kinder", {
        "de": "Betreuungsquote Kinder unter drei Jahren",
        "en": "childcare coverage for children under three",
        "fr": "taux de garde des enfants de moins de trois ans",
        "es": "tasa de atención infantil para menores de tres años",
        "it": "tasso di copertura degli asili nido sotto i tre anni",
        "pl": "odsetek dzieci poniżej trzech lat objętych opieką",
        "tr": "üç yaş altı çocuklar için bakım oranı",
        "uk": "охоплення доглядом дітей до трьох років",
        "ar": "نسبة رعاية الأطفال دون سن الثالثة",
        "zh": "三岁以下儿童保育覆盖率",
    }),
    (r"breitband|gigabit|mbit|ftth", {
        "de": "Breitbandverfügbarkeit auf Gemeindeebene",
        "en": "broadband availability by municipality",
        "fr": "disponibilité du haut débit par commune",
        "es": "disponibilidad de banda ancha por municipio",
        "it": "disponibilità della banda larga per comune",
        "pl": "dostępność szerokopasmowego internetu w gminach",
        "tr": "belediyelere göre geniş bant erişilebilirliği",
        "uk": "доступність широкосмугового інтернету по громадах",
        "ar": "توفر النطاق العريض حسب البلدية",
        "zh": "各市镇宽带覆盖情况",
    }),
    (r"ärzt|arzt|hausarzt", {
        "de": "Ärztedichte je Einwohner",
        "en": "physician density per inhabitant",
        "fr": "densité de médecins par habitant",
        "es": "densidad de médicos por habitante",
        "it": "densità di medici per abitante",
        "pl": "liczba lekarzy na mieszkańca",
        "tr": "kişi başına düşen doktor sayısı",
        "uk": "кількість лікарів на одного жителя",
        "ar": "كثافة الأطباء لكل ساكن",
        "zh": "每位居民的医生密度",
    }),
    (r"wahlbeteiligung|wähler|wahlberecht", {
        "de": "Wahlbeteiligung bei der Bundestagswahl",
        "en": "voter turnout in the federal election",
        "fr": "participation électorale aux élections fédérales",
        "es": "participación electoral en las elecciones federales",
        "it": "affluenza alle elezioni federali",
        "pl": "frekwencja wyborcza w wyborach federalnych",
        "tr": "federal seçimlerde seçmen katılımı",
        "uk": "явка виборців на федеральних виборах",
        "ar": "نسبة المشاركة في الانتخابات الاتحادية",
        "zh": "联邦选举投票率",
    }),
    (r"miet", {
        "de": "Mietpreise für Wohnungen",
        "en": "rent levels for flats",
        "fr": "niveau des loyers des logements",
        "es": "precios de alquiler de viviendas",
        "it": "livello degli affitti delle abitazioni",
        "pl": "wysokość czynszów za mieszkania",
        "tr": "konut kira fiyatları",
        "uk": "рівень орендної плати за житло",
        "ar": "مستويات إيجار الشقق",
        "zh": "住房租金水平",
    }),
    (r"wald", {
        "de": "Anteil der Waldfläche",
        "en": "share of forest area",
        "fr": "part de la surface forestière",
        "es": "proporción de superficie forestal",
        "it": "quota di superficie forestale",
        "pl": "udział powierzchni leśnej",
        "tr": "orman alanının payı",
        "uk": "частка лісової площі",
        "ar": "نسبة مساحة الغابات",
        "zh": "森林面积占比",
    }),
    (r"bruttoinlandsprodukt|bip", {
        "de": "Bruttoinlandsprodukt je Einwohner",
        "en": "gross domestic product per capita",
        "fr": "produit intérieur brut par habitant",
        "es": "producto interior bruto por habitante",
        "it": "prodotto interno lordo per abitante",
        "pl": "produkt krajowy brutto na mieszkańca",
        "tr": "kişi başına gayri safi yurt içi hasıla",
        "uk": "валовий внутрішній продукт на душу населення",
        "ar": "الناتج المحلي الإجمالي للفرد",
        "zh": "人均国内生产总值",
    }),
    (r"pendl", {
        "de": "Pendler zwischen Wohnort und Arbeitsort",
        "en": "commuters between home and workplace",
        "fr": "navetteurs entre domicile et lieu de travail",
        "es": "personas que se desplazan entre casa y trabajo",
        "it": "pendolari tra residenza e luogo di lavoro",
        "pl": "osoby dojeżdżające do pracy",
        "tr": "ev ile iş yeri arasında gidip gelenler",
        "uk": "маятникові мігранти між домом і роботою",
        "ar": "المتنقلون بين السكن ومكان العمل",
        "zh": "住所与工作地之间的通勤者",
    }),
]


# The same idea for the SOEP finder, whose corpus is German and English at once. Six concepts that
# every survey-based project touches, judged against the same gold patterns the SOEP gate uses.
SOEP_CASES = [
    (r"^(plh0182|plh0151|p11101)$", {
        "de": "Lebenszufriedenheit",
        "en": "overall life satisfaction",
        "fr": "satisfaction dans la vie",
        "es": "satisfacción con la vida",
        "it": "soddisfazione per la vita",
        "pl": "zadowolenie z życia",
        "tr": "yaşam memnuniyeti",
        "uk": "задоволеність життям",
        "ar": "الرضا عن الحياة",
        "zh": "生活满意度",
    }),
    (r"^(pglabnet|pglabgro|i11110|plc001[34])", {
        "de": "Nettoerwerbseinkommen im letzten Monat",
        "en": "net labour income last month",
        "fr": "revenu net du travail le mois dernier",
        "es": "ingresos netos del trabajo el mes pasado",
        "it": "reddito netto da lavoro dell'ultimo mese",
        "pl": "dochód netto z pracy w ubiegłym miesiącu",
        "tr": "geçen ayki net iş geliri",
        "uk": "чистий трудовий дохід за минулий місяць",
        "ar": "صافي دخل العمل الشهر الماضي",
        "zh": "上个月的税后劳动收入",
    }),
    (r"^(ple0008|m11126)$", {
        "de": "allgemeiner Gesundheitszustand",
        "en": "current self-rated health",
        "fr": "état de santé général",
        "es": "estado de salud general",
        "it": "stato di salute generale",
        "pl": "ogólny stan zdrowia",
        "tr": "genel sağlık durumu",
        "uk": "загальний стан здоров'я",
        "ar": "الحالة الصحية العامة",
        "zh": "总体健康状况",
    }),
    (r"^(migback|mig)", {
        "de": "Migrationshintergrund",
        "en": "migration background of the respondent",
        "fr": "origine migratoire",
        "es": "origen migratorio",
        "it": "background migratorio",
        "pl": "pochodzenie migracyjne",
        "tr": "göçmen kökeni",
        "uk": "міграційне походження",
        "ar": "الخلفية المهاجرة",
        "zh": "移民背景",
    }),
    (r"^(d11109|pgbilzeit)$", {
        "de": "Bildungsjahre einer Person",
        "en": "years of education",
        "fr": "nombre d'années d'études",
        "es": "años de educación",
        "it": "anni di istruzione",
        "pl": "liczba lat nauki",
        "tr": "eğitim yılı sayısı",
        "uk": "кількість років навчання",
        "ar": "سنوات التعليم",
        "zh": "受教育年限",
    }),
    (r"^(ple0179|hlf0192)$", {
        "de": "wie oft wird Fleisch gegessen",
        "en": "frequency of meat consumption",
        "fr": "fréquence de consommation de viande",
        "es": "frecuencia del consumo de carne",
        "it": "frequenza del consumo di carne",
        "pl": "jak często spożywane jest mięso",
        "tr": "et tüketim sıklığı",
        "uk": "як часто вживають м'ясо",
        "ar": "تكرار استهلاك اللحوم",
        "zh": "食用肉类的频率",
    }),
]


def ask(api: str, question: str, top_k: int, tries: int = 4):
    body = json.dumps({"question": question, "top_k": top_k, "dataset_scope": "all"}).encode()
    request = urllib.request.Request(f"{api.rstrip('/')}/soep/advice", data=body,
                                     headers={"Content-Type": "application/json"})
    for _ in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read())["recommended_variables"]
        except Exception:
            time.sleep(10)
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="https://geodb.geolab.soz.uni-bielefeld.de/api")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--languages", default=",".join(LANGUAGES))
    parser.add_argument("--json-out", default="")
    parser.add_argument("--corpus", choices=["geodb", "soep"], default="geodb")
    args = parser.parse_args()

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    cases = CASES if args.corpus == "geodb" else SOEP_CASES
    results = []
    for pattern, questions in cases:
        for language in languages:
            question = questions.get(language)
            if not question:
                continue
            rows = ask(args.api, question, args.top_k)
            # The pattern is tried against the code alone AND against code plus label. The SOEP
            # golds are anchored on the variable name (^pglabnet$), so testing them against the
            # concatenation never matches and counted correct hits as failures; the GeoDB golds
            # are loose words that need the label. Both kinds work this way.
            def hit(row):
                name = str(row.get("variable_name", ""))
                return bool(re.search(pattern, name, re.I)
                            or re.search(pattern, f"{name} {row.get('label', '')}", re.I))

            rank = next((index + 1 for index, row in enumerate(rows) if hit(row)), None)
            results.append({"language": language, "question": question, "rank": rank,
                            "top_label": (rows[0].get("label") if rows else "")})

    print(f"{len(cases)} Fragen in {len(languages)} Sprachen ({args.corpus})\n")
    print(f"{'Sprache':<9}{'auf Platz 1':>12}{'in Top 3':>10}{'in Top 10':>11}{'kein Treffer':>14}")
    summary = {}
    for language in languages:
        rows = [r for r in results if r["language"] == language]
        found = [r for r in rows if r["rank"]]
        at1 = sum(1 for r in found if r["rank"] == 1)
        at3 = sum(1 for r in found if r["rank"] <= 3)
        summary[language] = {"n": len(rows), "hit@1": at1, "hit@3": at3, "hit@10": len(found)}
        print(f"{language:<9}{at1:>7}/{len(rows):<4}{at3:>6}/{len(rows):<3}{len(found):>7}/{len(rows):<3}"
              f"{len(rows) - len(found):>10}")

    misses = [r for r in results if not r["rank"]]
    if misses:
        print("\nnicht gefunden:")
        for r in misses:
            print(f"  [{r['language']}] {r['question'][:52]:<54} statt dessen: {str(r['top_label'])[:38]}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({"summary": summary, "results": results},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
