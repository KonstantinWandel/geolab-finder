#!/usr/bin/env python3
"""Import the provider's complete public RDF metadata export, checked against its API."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from pyoxigraph import BlankNode, Literal, NamedNode, RdfFormat, Store

from harvest_gesis import Client, DDI, FOLDER, KG, SCHEMA, sparql

RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
TYPES = {"kg_dataset": SCHEMA + "Dataset", "kg_variable": DDI + "Variable"}
CORE = {
    "kg_dataset": {SCHEMA + p for p in ("name", "abstract", "description", "startDate", "endDate", "conditionsOfAccess")}
        | {KG + p for p in ("analysisUnit", "geographicalUnit", "locationsId", "universe", "category", "studyGroup", "doi")},
    "kg_variable": {KG + p for p in ("variableLabel", "variableInterviewInstructions", "relatedDataset", "relatedDatasetURI")}
        | {DDI + "variableName", SCHEMA + "name"},
}


def term(value):
    if isinstance(value, NamedNode):
        return {"value": value.value, "type": "uri", "language": "", "datatype": ""}
    if isinstance(value, BlankNode):
        return {"value": value.value, "type": "bnode", "language": "", "datatype": ""}
    if isinstance(value, Literal):
        return {"value": value.value, "type": "literal", "language": value.language or "",
                "datatype": "" if value.language else value.datatype.value}
    raise TypeError(f"Unsupported RDF term: {value!r}")


def canonical(value):
    kind = "literal" if value["type"] == "typed-literal" else value["type"]
    language = value.get("language", value.get("xml:lang", ""))
    datatype = value.get("datatype", "")
    if kind == "literal" and not language and not datatype:
        datatype = "http://www.w3.org/2001/XMLSchema#string"
    return (kind, value["value"], language, "" if language else datatype)


def triples(fields, predicates=None):
    return {(p, *canonical(v)) for p, values in fields.items() if predicates is None or p in predicates for v in values}


def resource(store, subject):
    fields = defaultdict(list)
    for quad in store.quads_for_pattern(subject, None, None, None):
        fields[quad.predicate.value].append(term(quad.object))
    return dict(fields)


def load_export(folder):
    manifest = json.loads((folder / "BULK_DOWNLOAD_REPORT.json").read_text())
    store = Store(str(folder / "raw/bulk/rdf-store"))
    progress_path = folder / "raw/bulk/import-progress.json"
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
    for filename, info in manifest["files"].items():
        if not filename.endswith(".zip"):
            continue
        archive = folder / "raw/bulk" / filename
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != info["sha256"]:
                raise ValueError(f"Export checksum mismatch: {filename}")
        with ZipFile(archive) as zipped:
            for member in zipped.infolist():
                if member.is_dir():
                    continue
                if not member.filename.endswith(".ttl"):
                    raise ValueError(f"Unexpected non-RDF export member: {member.filename}")
                key = filename + ":" + member.filename
                if key in progress and progress[key] != info["sha256"]:
                    raise ValueError("Export release changed; use a fresh snapshot/store")
                if progress.get(key) == info["sha256"]:
                    continue
                print("Parsing " + member.filename, flush=True)
                # Read directly from the archive: no path extraction or hand-parsed Turtle.
                with zipped.open(member) as stream:
                    store.bulk_load(input=stream, format=RdfFormat.TURTLE, lenient=False)
                store.flush()
                progress[key] = info["sha256"]
                progress_path.write_text(json.dumps(progress, indent=2) + "\n")
    return store, manifest


def validate_samples(client, store, db, kind, count):
    samples = []
    # Spread deterministic samples across the full resource ordering, not the hand-picked study.
    for offset in sorted({0, count - 1, *(i * (count - 1) // 11 for i in range(12))}):
        identifier, payload = db.execute("SELECT id,payload FROM documents WHERE kind=? ORDER BY id LIMIT 1 OFFSET ?",
                                         (kind, offset)).fetchone()
        local = json.loads(payload)
        query = f"SELECT ?p ?o WHERE {{ <{identifier}> ?p ?o }} ORDER BY ?p ?o LIMIT 10000"
        path = "bulk-validation/" + hashlib.sha256(identifier.encode()).hexdigest() + ".json"
        remote = defaultdict(list)
        for row in sparql(client, query, path):
            remote[row["p"]["value"]].append(row["o"])
        core_local, core_remote = triples(local, CORE[kind]), triples(remote, CORE[kind])
        if core_local != core_remote:
            raise ValueError(f"Export/API metadata mismatch for {identifier}: "
                             f"only_export={core_local - core_remote}, only_API={core_remote - core_local}")
        extra_export, extra_api = triples(local) - triples(remote), triples(remote) - triples(local)
        samples.append({"id": identifier, "core_equal": True, "all_triples_equal": not (extra_export or extra_api),
                        "export_triples": len(triples(local)), "api_triples": len(triples(remote)),
                        "export_only_predicates": sorted({v[0] for v in extra_export}),
                        "api_only_predicates": sorted({v[0] for v in extra_api})})
    return samples


def run(folder):
    store, manifest = load_export(folder)
    client = Client(folder, 0.3)
    current = folder / "catalogue.sqlite"
    candidate = folder / "catalogue.bulk.sqlite"
    report_path = folder / "HARVEST_REPORT.json"
    report = json.loads(report_path.read_text())
    db = sqlite3.connect(candidate)
    db.execute("CREATE TABLE IF NOT EXISTS documents(kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id))")
    db.execute("ATTACH DATABASE ? AS archive", (str(current),))
    for kind in ("oai_de", "oai_en"):
        actual = db.execute("SELECT COUNT(*) FROM archive.documents WHERE kind=?", (kind,)).fetchone()[0]
        if not report["stages"].get(kind, {}).get("complete") or actual != report["stages"][kind]["records"]:
            raise ValueError(f"Verified OAI stage required: {kind}")
    db.execute("INSERT OR REPLACE INTO documents SELECT * FROM archive.documents WHERE kind IN ('oai_de','oai_en')")
    db.commit()
    db.execute("DETACH DATABASE archive")
    validation = {"validated_at": datetime.now(timezone.utc).isoformat(), "export_doi": manifest["doi"],
                  "export_version": manifest["version"], "classes": {}}
    for kind, type_uri in TYPES.items():
        reported = int(sparql(client, f"SELECT (COUNT(DISTINCT ?id) AS ?count) WHERE {{ ?id a <{type_uri}> }}",
                              f"bulk-validation/{kind}-count.json")[0]["count"]["value"])
        batch, count = [], 0
        db.execute("DELETE FROM documents WHERE kind=?", (kind,))
        for quad in store.quads_for_pattern(None, RDF_TYPE, NamedNode(type_uri), None):
            if not isinstance(quad.subject, NamedNode):
                raise ValueError("Unexpected anonymous dataset/variable identity")
            fields = resource(store, quad.subject)
            batch.append((kind, quad.subject.value, json.dumps(fields, ensure_ascii=False)))
            count += 1
            if len(batch) == 1000:
                db.executemany("INSERT INTO documents VALUES (?,?,?)", batch)
                db.commit()
                batch.clear()
                if count % 100000 == 0:
                    print(f"Imported {kind}: {count}/{reported}", flush=True)
        db.executemany("INSERT INTO documents VALUES (?,?,?)", batch)
        db.commit()
        if count != reported:
            raise ValueError(f"Export/API count mismatch: {kind}: {count} != {reported}")
        samples = validate_samples(client, store, db, kind, count)
        validation["classes"][kind] = {"records": count, "api_count": reported, "samples": samples}
        report["stages"][kind] = {"records": count, "reported": reported, "complete": True,
                                  "retrieval": "Published RDF export DOI 10.7802/2969 v2.0.0, API count and core-field sample validation"}
        print(f"Verified {kind}: {count} and {len(samples)} API samples", flush=True)
    db.close()
    (folder / "BULK_VALIDATION_REPORT.json").write_text(json.dumps(validation, indent=2) + "\n")
    # No partial graph replaces the verified current archive on an import failure.
    backup = folder / "catalogue.sqlite.sparql-backup"
    if not backup.exists():
        current.replace(backup)
    candidate.replace(current)
    report["updated"] = datetime.now(timezone.utc).isoformat()
    report["scope"] = "All public GESIS OAI archive dataset metadata and GESIS KG dataset/variable metadata; no microdata. Vitrine partner indices are separately reported as blocked."
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    run(parser.parse_args().folder)
