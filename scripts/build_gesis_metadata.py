#!/usr/bin/env python3
"""Select evidenced regional metadata from the entire harvested GESIS catalogue."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, urlencode

from gesis_regions import RULE_VERSION, dataset_eligibility, period, text, variable_eligibility
from harvest_gesis import DDI, FOLDER, KG, SCHEMA, plain

CITATION = "Biswas, D., Gupta, E., Yu, R., & Zapilko, B. (2025). GESIS Knowledge Graph, Version 2.0.0. https://doi.org/10.7802/2969"
NOTES = {
    "regional_dataset": "Regionaler Datensatz laut öffentlich zugänglichen Studienmetadaten; Datenzugang beim Anbieter prüfen.",
    "regional_study": "Regional abgegrenzte Studie, nicht automatisch ein Datensatz mit regional aggregierten Beobachtungen.",
    "regional_dataset_variable": "Variable eines regionalen Datensatzes laut Studienmetadaten; keine Messwerte im GeoDB-Index.",
    "survey_geography_variable": "Geografie-/Kontextvariable einer Befragung, kein regional aggregierter Indikator. Geocodes und Datenzugang beim Anbieter prüfen.",
}
RETRIEVAL_TYPES = {
    "regional_dataset": "Regional aggregate dataset; catalogue metadata, not hosted observations.",
    "regional_study": "Individual-level survey or mixed regional study, not an aggregated regional indicator.",
    "regional_dataset_variable": "Variable in a regional aggregate dataset; catalogue metadata, not hosted observations.",
    "survey_geography_variable": "Individual-level geographic identifier or regional context field, not an aggregated regional statistic.",
}


def literals(fields, predicate):
    items = fields.get(predicate, [])
    # German first for display; preserve English/other variants as official aliases.
    items = sorted(items, key=lambda v: {"de": 0, "en": 1, "": 2}.get(v.get("language", ""), 3))
    return list(dict.fromkeys(plain(i["value"]) for i in items if i.get("type") != "uri" and plain(i["value"])))


def graph_dataset(fields):
    return {
        "title": literals(fields, SCHEMA + "name"), "abstract": literals(fields, SCHEMA + "abstract") + literals(fields, SCHEMA + "description"),
        "analysis_unit": literals(fields, KG + "analysisUnit"), "geographic_unit": literals(fields, KG + "geographicalUnit"),
        "data_kind": literals(fields, KG + "datasetDatatype"),
        "geography": literals(fields, KG + "locationsId"), "universe": literals(fields, KG + "universe"),
        "collection_dates": literals(fields, SCHEMA + "startDate") + literals(fields, SCHEMA + "endDate"),
        "topics": literals(fields, KG + "category") + literals(fields, KG + "studyGroup"), "doi": literals(fields, KG + "doi"),
        "access": literals(fields, SCHEMA + "conditionsOfAccess"), "kg": True,
    }


def merge_metadata(left, right):
    result = dict(left)
    for key, value in right.items():
        if isinstance(value, list):
            if key == "date_attributes":
                result[key] = result.get(key, []) + value
            else:
                unique = {}
                for item in result.get(key, []) + value:
                    identity = json.dumps(item, sort_keys=True, ensure_ascii=False) if isinstance(item, dict) else " ".join(item.split())
                    unique.setdefault(identity, item)
                result[key] = list(unique.values())
        elif value:
            result[key] = value
    return result


def study_key(identifier, metadata):
    if ":DBK/" in identifier or ":COL/" in identifier:
        return identifier.rsplit("/", 1)[-1]
    if identifier.startswith("https://data.gesis.org/gesiskg/resource/"):
        return identifier.rsplit("/", 1)[-1]
    if ":SDN/" in identifier:
        return "SDN-" + identifier.split(":SDN/", 1)[1].replace("_", "-", 1)
    # SDN studies have no ZA identifier. The OAI ID remains stable and unique.
    return identifier


def make_item(identifier, metadata, eligible, variable=None, resource_uri=""):
    from build_geodb_metadata import make_record

    title = metadata["title"][0]
    label = (variable.get("label") or variable.get("name"))[0] if variable else title
    code = (variable.get("name") or [identifier])[0] if variable else identifier
    start, end, dates = period(metadata)
    years = str(start) if start == end and start is not None else f"{start}-{end}" if start is not None and end is not None else dates
    description = text(variable.get("question", [])) if variable else text(metadata.get("abstract", []))
    if variable:
        description = text([description, "Studie: " + title])
    description = text([description, NOTES[eligible["classification"]],
                        "Raumbezug: " + text(metadata.get("geography", [])),
                        "Datenzugang: " + (text(metadata.get("access_status", []) + metadata.get("access", [])) or "Nicht in diesen Metadaten spezifiziert."),
                        "Historische Raumgliederung; keine automatische Zuordnung zu heutigen AGS/NUTS." if eligible["historical_geography"] else ""])
    kg = bool(resource_uri or metadata.get("kg"))
    attribution = CITATION if kg else "GESIS Datenarchiv: öffentliche DBK-Studienmetadaten (CC0 1.0)."
    destination_id = variable.get("study_id", "") if variable else identifier
    # KG resource IRIs are identities, not dereferenceable pages (provider returns
    # 404). Link to the containing study; retain the IRI as separate provenance.
    if re.fullmatch(r"ZA\d+", destination_id):
        url = "https://search.gesis.org/research_data/" + destination_id
    elif any(re.fullmatch(r"10\.7802/[^\s]+", doi) for doi in metadata.get("doi", [])):
        doi = next(doi for doi in metadata["doi"] if re.fullmatch(r"10\.7802/[^\s]+", doi))
        url = "https://data.gesis.org/sharing/#!Detail/" + doi
    elif metadata.get("oai_identifier"):
        url = "https://dbkapps.gesis.org/dbkoai/?verb=GetRecord&metadataPrefix=oai_dc&identifier=" + quote(metadata["oai_identifier"], safe="")
    else:
        iri = resource_uri or metadata["kg_resource_uri"]
        url = "https://data.gesis.org/gesiskg/sparql?" + urlencode({"query": f"SELECT ?p ?o WHERE {{ <{iri}> ?p ?o }}", "format": "json"})
    result = make_record(
        source_key="gesis", source_label="GESIS", item_type=eligible["classification"],
        item_id="gesis:" + identifier, variable_name=code, label=label, dataset_label=title,
        theme="Geografie / Kontext" if eligible["classification"] == "survey_geography_variable" else (metadata.get("topics") or [""])[0],
        description=description + "\nMetadatenquelle: " + attribution,
        aliases=text((variable.get("label", []) if variable else metadata.get("title", []))),
        spatial_levels=eligible["spatial_levels"], nuts_levels=eligible["nuts_levels"],
        year_start=start, year_end=end, years_text=years, source_url="https://search.gesis.org/",
        indicator_url=url, access_modes=["metadata API", "web UI / search form only"],
        api_hint="Öffentliche Metadaten: https://dbkapps.gesis.org/dbkoai/ und https://data.gesis.org/gesiskg/sparql . Keine Befragungsdaten.",
        link_level="dataset" if destination_id or metadata.get("oai_identifier") else "indicator", link_verified=False,
    )
    result.update({"metadata_only": True, "observation_data_available": False, "map_ready": False,
                   "geographic_evidence": eligible["evidence"], "regional_rule_version": RULE_VERSION,
                   "historical_geography": eligible["historical_geography"], "metadata_license": "CC-BY-4.0" if kg else "CC0-1.0",
                   "metadata_attribution": attribution, "study_id": study_key(identifier, metadata) if not variable else variable.get("study_id", ""),
                   "doi": text(metadata.get("doi", [])), "data_access": text(metadata.get("access_status", []) + metadata.get("access", [])),
                   "study_topics": metadata.get("topics", []), "collection_periods": dates})
    if resource_uri:
        result["metadata_resource_uri"] = resource_uri
    # Display keeps access/licensing warnings; retrieval uses official subject matter,
    # without repeating the same disclaimer and portal URL in every document.
    subject = text(variable.get("question", [])) if variable else text(metadata.get("abstract", []))
    result["search_description"] = text([RETRIEVAL_TYPES[eligible["classification"]], subject])
    result["embedding_context"] = text([
        "Official labels: " + result["aliases"],
        "Study: " + title if variable else "",
        "Geographic evidence: " + eligible["evidence"][:1500],
    ])
    return result


def build(folder, allow_partial=False):
    report = json.loads((folder / "HARVEST_REPORT.json").read_text())
    required = {"oai_de", "oai_en", "kg_dataset", "kg_variable"}
    if not allow_partial and any(not report["stages"].get(k, {}).get("complete") for k in required):
        raise ValueError("Full harvest not complete; do not publish a partial catalogue as complete")
    db = sqlite3.connect(f"file:{folder / 'catalogue.sqlite'}?mode=ro", uri=True)
    studies = {}
    for kind, identifier, payload in db.execute("SELECT kind,id,payload FROM documents WHERE kind IN ('oai_de','oai_en','kg_dataset') ORDER BY kind,id"):
        raw = json.loads(payload)
        metadata = graph_dataset(raw) if kind == "kg_dataset" else raw
        if metadata.get("deleted") or metadata.get("metadata_error") or not metadata.get("title"):
            continue
        key = study_key(identifier, metadata)
        metadata["oai_identifier"] = identifier if kind.startswith("oai") else ""
        if kind == "kg_dataset":
            metadata["kg_resource_uri"] = identifier
        studies[key] = merge_metadata(studies.get(key, {}), metadata)
    eligible_studies = {key: dataset_eligibility(value) for key, value in studies.items()}
    records, classes = [], Counter()
    for key, eligible in eligible_studies.items():
        if not eligible:
            continue
        metadata = studies[key]
        item = make_item(key, metadata, eligible)
        records.append(item)
        classes[eligible["classification"]] += 1
    scanned = 0
    missing_parents = 0
    for identifier, payload in db.execute("SELECT id,payload FROM documents WHERE kind='kg_variable' ORDER BY id"):
        fields = json.loads(payload)
        scanned += 1
        parents = [v["value"].rsplit("/", 1)[-1] for v in fields.get(KG + "relatedDataset", []) + fields.get(KG + "relatedDatasetURI", []) if v.get("type") == "uri"]
        parent_id = next((p for p in parents if p in studies), None)
        metadata = studies.get(parent_id, graph_dataset(fields))
        if parent_id is None:
            missing_parents += 1
            metadata["title"] = ["Studienmetadaten nicht zugeordnet"]
        variable = {"label": literals(fields, KG + "variableLabel"), "name": literals(fields, DDI + "variableName"),
                    "question": literals(fields, KG + "variableInterviewInstructions"), "parent_metadata": metadata, "study_id": parent_id or ""}
        if not variable["label"]:
            variable["label"] = literals(fields, SCHEMA + "name")
        eligible = variable_eligibility(variable, eligible_studies.get(parent_id))
        if eligible and metadata.get("title"):
            item = make_item(identifier.rsplit("/", 1)[-1], metadata, eligible, variable, identifier)
            records.append(item)
            classes[eligible["classification"]] += 1
        if scanned % 100000 == 0:
            print(f"Classified {scanned} variable records", flush=True)
    db.close()
    keys = [r["item_id"] for r in records]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate GESIS item identities")
    destination = folder / "geodb_records.json"
    destination.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    counts = {"built_at": datetime.now(timezone.utc).isoformat(), "rule_version": RULE_VERSION,
              "harvest_complete": not allow_partial, "studies_considered": len(studies), "variables_considered": scanned,
              "variables_without_study_metadata": missing_parents,
              "indexed_records": len(records), "classifications": dict(classes), "metadata_only": True,
              "modern_map_join_claimed": False, "records_sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    (folder / "REGIONAL_REPORT.json").write_text(json.dumps(counts, indent=2) + "\n")
    print(json.dumps(counts, indent=2))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--allow-partial", action="store_true", help="Local diagnostic only, never publish")
    args = parser.parse_args()
    build(args.folder, args.allow_partial)


if __name__ == "__main__":
    main()
