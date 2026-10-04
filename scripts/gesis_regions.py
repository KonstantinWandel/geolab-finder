"""Evidence-based discovery rules, not proof of joinability or data access.

Geographic coverage of a national survey is not a regional variable. Dataset
eligibility and variable eligibility are evaluated separately; parent abstracts
must never turn every questionnaire item into a geographic item.
"""
from __future__ import annotations

import re

RULE_VERSION = "1.6"
LEVELS = [
    ("Wahlkreise", r"\bwahlkreis\w*|\belectoral (?:district|constituenc)\w*|\bconstituenc\w*"),
    ("Bundesländer", r"\bbundesl(?:a|ä|ae)nd\w*|\bfederal state\w*|\bstate of residence\b"),
    ("Regierungsbezirke", r"\bregierungsbezirk\w*"),
    ("Kreise", r"\blandkreis\w*|\bkreise?\b|\bkreisfreie\w*|\bkreisebene\b|\bkreisschl[uü]ssel\b|\bcount(?:y|ies)\b|\bdistricts?\b"),
    ("Gemeinden", r"\bgemeinde\w*|\bst[aä]dte\b|\bmunicipalit\w*|\bcities\b|\b(?:municipal|city) (?:code|identifier|level)\b"),
    ("PLZ", r"\bpostleitzahl\w*|\bpostal codes?\b|\bpostcodes?\b|\bzip codes?\b"),
    ("NUTS", r"\bnuts\s*[-_]?[0-3]\b"),
    ("Adressen/Koordinaten", r"\blatitude\b|\blongitude\b|\bbreitengrad\b|\bl[aä]ngengrad\b|\blaengengrad\b|\bgeograph\w* koordinaten\b|\bgeographic coordinates\b"),
    ("Rasterzellen", r"\brasterzelle\w*|\bgitterzelle\w*|\bgrid[ -]cells?\b|\bgeographic(?:al)? grid\b"),
    ("Weitere Gliederungen", r"\bregion(?:al)? (?:code|identifier|of residence)\b|\bwohnort\w*|\bresidential area\b|\bsiedlungstyp\b|\bortsgro[eö]sse\b|\bortsgr[oö]ße\b|\btown size\b|\bwahlbezirk\w*|\bstimmbezirk\w*|\bstadtteil\w*|\bortsteil\w*"),
]
INDIVIDUAL = re.compile(r"\bindividu\w*|\bpersonen\b|\bbefragte\w*|\brespondents?\b|\bhaushalt\w*|\bprivathaushalt\w*|\bhouseholds?\b|\bw[aä]hlberechtigte\w*|\babgeordnete\w*|\bmembers of parliament\b|\btweets?\b|\beinwohnermelde\w*", re.I)
AGGREGATE = re.compile(r"\baggreg(?:at|iert)\w*|\bmacro[ -]?data\b|\bmakrodaten\b|\becological data\b|\bregional statistics\b|\bregionalstatistik\b", re.I)
HISTORICAL = re.compile(r"\bdeutsches reich\b|\breichstag\w*|\bwilhelmin\w*|\bkaiserreich\b", re.I)
GEOREFERENCED = re.compile(r"\bgeo[ -]?referenc\w*|\bgeoreferenziert\w*|\bgeocod(?:ed|iert)\w*|\bgeospatial\b|\bgeodaten\b", re.I)
GEO_VARIABLE = re.compile(
    r"\bnuts\s*[-_]?[0-3]\b|\ballgemeiner gemeindeschl[uü]ssel\b|\b(?:ags|plz)\b|"
    r"\b(?:gemeinde|kreis)schl[uü]ssel\w*|\bpostleitzahl\w*|\bpostal codes?\b|\bpostcodes?\b|"
    r"\bbundesland\w*|\bbundesl(?:a|ä|ae)nder\b|\blandkreis\w*|\bstate of residence\b|"
    r"\b(?:region|district|county|municipality) (?:code|identifier|of residence)\b|"
    r"\b(?:region|kreis|gemeinde|wohnort)(?:nummer|kennung|code)\b|"
    r"\b(?:region|kreis|gemeinde|stadtteil|ortsteil|district|county|municipality)\s+(?:des|der|of)\s+(?:wohnorts?|residence|interview)\b|"
    r"\b(?:ortsgr[oö]ße|ortsgroesse|siedlungstyp|town size)\b|"
    r"\b(?:latitude|longitude|breitengrad|l[aä]ngengrad|laengengrad)\b|"
    r"\b(?:bundestags|landtags)?wahlkreis(?:nummer|kennung|code|schl[uü]ssel|schluessel)?\b|"
    r"\bregierungsbezirk\w*|\bherkunftsregion\b|\bgeographic coordinates?\b|"
    r"\brasterzelle\w*|\bgitterzelle\w*|\bgrid[ -]cell (?:code|identifier|id)\b|"
    r"\bconstituency (?:code|identifier|of residence)\b|"
    r"\b(?:wahlbezirk|stimmbezirk|stadtteil|ortsteil)(?:nummer|kennung|code)\b", re.I)
FIELD_HEAD = re.compile(
    r"^(?:(?:[a-z]+[.]?\d[\w.]*|\d+[\w.]*)[ _.:/-]+)*"
    r"(?:(?:recoded|recode|harmonized|harmonised|derived|original|rekodiert|demographie|bik|politische)\s*[: _-]*\s*)?"
    r"(?:region\w*|bundesl\w*|landkreis\w*|kreis\w*|gemeinde\w*|wohnort\w*|geburtsort\w*|"
    r"arbeitsst[aä]tte\w*|geburtsland|herkunftsregion|regierungsbezirk\w*|interviewort\w*|befragungsort\w*|(?:bundestags|landtags)?wahlkreis\w*|constituenc\w*|"
    r"ortsgr\w*|ortsgro\w*|siedlungstyp\w*|town size|state of residence|"
    r"(?:residential|administrative|electoral) (?:area|district)|district|county|municipality|"
    r"postleitzahl\w*|postal|postcode|plz|nuts|ags|latitude|longitude|breitengrad|l[aä]ngengrad|"
    r"geographic coordinates?|rasterzelle\w*|gitterzelle\w*|grid[ -]cell|stadtteil\w*|ortsteil\w*|wahlbezirk\w*|stimmbezirk\w*)\b", re.I)
EXPLICIT_IDENTIFIER = re.compile(r"\bnuts\s*[-_]?[0-3]\b|\b(?:ags|plz)\b|\b\w*(?:schl[uü]ssel|schluessel|kennung|identification code)\b", re.I)


def geography_field(variable):
    labels = variable.get("label", []) or variable.get("name", [])
    # Mentioning a place in a behaviour/attitude question is not a location field.
    # Accept a geographic primary field, an explicit identifier, or a named
    # residence/workplace/birthplace attribute. Question wording is not inherited.
    for label in labels:
        cleaned = label.strip().replace("_", " ").lstrip("[]* ")
        cleaned = re.sub(r"^[A-Z]{1,3}[.]", "", cleaned)
        if FIELD_HEAD.search(cleaned) or EXPLICIT_IDENTIFIER.search(cleaned):
            return True
        if ":" in cleaned and FIELD_HEAD.search(cleaned.rsplit(":", 1)[1].strip()):
            return True
        if re.search(r"\b(?:wohnort|geburtsort|arbeitsst[aä]tte|residence|birthplace|workplace)\s*[:(-]", cleaned, re.I):
            return True
    return False


def text(values):
    return "\n".join(str(v) for v in values if v)


def period(metadata):
    values = metadata.get("collection_dates", []) + metadata.get("time_period", [])
    values += [d.get("date", "") for d in metadata.get("date_attributes", [])]
    years = sorted({int(y) for y in re.findall(r"\b(?:1\d{3}|20\d{2})\b", text(values))})
    return (years[0], years[-1], text(values)) if years else (None, None, text(values))


def levels(value, germany=False, historical=False):
    spatial, nuts = [], []
    for level, pattern in LEVELS:
        if not re.search(pattern, value, re.I):
            continue
        if level == "NUTS":
            matches = re.findall(r"\bnuts\s*[-_]?([0-3])\b", value, re.I)
            nuts.extend("NUTS" + m for m in matches)
            spatial.extend({"0": "Bund", "1": "NUTS1", "2": "NUTS2", "3": "NUTS3"}[m] for m in matches)
        else:
            if historical and level in {"Wahlkreise", "Kreise", "Gemeinden", "Bundesländer", "Regierungsbezirke"}:
                level = "Historische " + ("Regionen" if level == "Bundesländer" else level)
            elif not germany and level in {"Kreise", "Gemeinden", "Bundesländer"}:
                level = {"Kreise": "Districts (international)", "Gemeinden": "Municipalities (international)",
                         "Bundesländer": "Federal states (international)"}[level]
            spatial.append(level)
    # Explicit provider NUTS notation is retained. No Kreis-to-NUTS equivalence
    # is inferred without the definitions/vintage or individual region codes.
    return sorted(set(spatial)), sorted(set(nuts))


def country_is_germany(metadata):
    return bool(re.search(r"\bdeutschland\b|\bgermany\b|\bDE(?:\b|[-_])", text(metadata.get("geography", [])), re.I))


def dataset_eligibility(metadata):
    if metadata.get("deleted") or metadata.get("metadata_error") or not metadata.get("title"):
        return None
    units = text(metadata.get("analysis_unit", []) + metadata.get("geographic_unit", []))
    core = text(metadata.get("title", []) + metadata.get("geography", []) + metadata.get("universe", []))
    evidence = core + "\n" + units
    start, end, _ = period(metadata)
    historical = bool(HISTORICAL.search(core)) or (end is not None and end < 1949)
    spatial, nuts = levels(evidence, country_is_germany(metadata), historical)
    # The archive also expresses subnational coverage as explicit DE subdivision
    # codes. This is coverage of a study, not a NUTS equivalence or a map join.
    if re.search(r"\bDE-[A-Z]{2}\b", text(metadata.get("geography", []))):
        spatial = sorted(set(spatial + ["Historische Regionen" if historical else "Bundesländer"]))
    # An explicitly aggregate description may locate the level in the abstract.
    abstract = text(metadata.get("abstract", []))
    aggregate = bool(AGGREGATE.search(units + "\n" + core))
    if not spatial and AGGREGATE.search(abstract):
        # A national history abstract can mention municipalities in one paragraph
        # and aggregated national investment many paragraphs later. Those are not
        # evidence of regional observations. Require a nearby level instead.
        windows = text([abstract[max(0, m.start() - 140):m.end() + 140] for m in AGGREGATE.finditer(abstract)])
        spatial, nuts = levels(windows, country_is_germany(metadata), historical)
        aggregate = bool(spatial)
        evidence = windows
    if not spatial and GEOREFERENCED.search(core + "\n" + units + "\n" + text(metadata.get("data_kind", [])) + "\n" + abstract):
        windows = text([abstract[max(0, m.start() - 140):m.end() + 140] for m in GEOREFERENCED.finditer(abstract)])
        spatial, nuts = levels(windows, country_is_germany(metadata), historical)
        spatial = spatial or ["Weitere Gliederungen"]
        evidence = core + "\n" + units + "\n" + windows
    if not spatial:
        return None
    unit_levels, _ = levels(units, country_is_germany(metadata), historical)
    aggregate = aggregate or (bool(unit_levels) and not INDIVIDUAL.search(units))
    # An election-result table has regional observations even when the archive's
    # analysis-unit field is empty. Surveys about elections do not meet this rule.
    election_table = re.search(r"wahl(?:ergebnis|statistik)\w*|ergebnisse\s+der\s+reichstagswahlen|election\s+results", core, re.I)
    if election_table and not INDIVIDUAL.search(units):
        aggregate = True
    # Mixed studies may include a contextual aggregate file as well as individual
    # records. Never promote every variable in that study to aggregate data.
    individual = bool(INDIVIDUAL.search(units + "\n" + text(metadata.get("universe", []))))
    individual = individual or bool(re.search(r"befrag\w*|interview\w*|questionnaire|\bsurvey\b", text(metadata.get("collection_method", [])), re.I))
    category = "regional_dataset" if aggregate and not individual else "regional_study"
    return {"classification": category, "spatial_levels": spatial, "nuts_levels": nuts,
            "historical_geography": historical, "evidence": evidence[:4000], "rule_version": RULE_VERSION}


def variable_eligibility(variable, parent):
    own = text(variable.get("label", []) + variable.get("name", []))
    if not own.strip():
        return None
    if parent and parent.get("classification") == "regional_dataset":
        if any(re.fullmatch(r"(?:doi|id|lfd|serial|year|jahr|case ?id|interview ?id|(?:za )?study identification|studiennummer)", value.strip(), re.I)
               for value in variable.get("label", []) + variable.get("name", [])):
            return None
        return {**parent, "classification": "regional_dataset_variable", "evidence": own + "\n" + parent["evidence"]}
    if re.search(r"zufrieden|beurteil|bewert|pr[eä]ferenz|arbeiten sie|satisfaction|opinion|prefer|would you|willing|"
                 r"verbundenheit|verbundenheits|belonging|attachment|gewicht|weight|\bgruende\b|\bgründe\b|"
                 r"\breasons?\b|\bseit wann\b|\bsince when\b|\bwohndauer\b", own, re.I):
        return None
    match = GEO_VARIABLE.search(own)
    # Short labels such as "Region" are geographic identifier fields, not a
    # national income item whose inherited study description mentions regions.
    if not match and not any(re.fullmatch(r"(?:region|region of interview|kreis|gemeinde|wohnort|constituency|wahlkreis|wahlbezirk|stimmbezirk|stadtteil|ortsteil)", v.strip(), re.I)
                             for v in variable.get("label", []) + variable.get("name", [])):
        return None
    if not geography_field(variable):
        return None
    parent_metadata = variable.get("parent_metadata", {})
    _, end, _ = period(parent_metadata)
    historical = bool(HISTORICAL.search(text(parent_metadata.get("title", []) + parent_metadata.get("geography", [])))) or (end is not None and end < 1949)
    spatial, nuts = levels(own, country_is_germany(parent_metadata), historical)
    if not spatial:
        spatial = ["Weitere Gliederungen"]
    return {"classification": "survey_geography_variable", "spatial_levels": spatial, "nuts_levels": nuts,
            "historical_geography": historical, "evidence": own[:4000], "rule_version": RULE_VERSION}
