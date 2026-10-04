#!/usr/bin/env python3
"""Catalogue-wide GESIS public metadata harvest, never respondent data.

OAI resumption tokens and SPARQL keyset pages are followed to exhaustion. The
entire dataset/variable metadata catalogue is retained locally; regional
eligibility is decided later, not by restricting the provider query.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import gzip
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import time
from xml.etree import ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data_sources/gesis"
OAI = "https://dbkapps.gesis.org/dbkoai/"
SPARQL = "https://data.gesis.org/gesiskg/sparql"
KG = "https://data.gesis.org/gesiskg/schema/"
SCHEMA = "https://schema.org/"
DDI = "http://rdf-vocabulary.ddialliance.org/lifecycle#"
NS = {"o": "http://www.openarchives.org/OAI/2.0/", "d": "ddi:codebook:2_5", "a": "http://da-ra.de/schema/kernel-4"}
NS.update({"dc": "http://purl.org/dc/elements/1.1/", "odc": "http://www.openarchives.org/OAI/2.0/oai_dc/"})


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "li", "ul", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "li", "div"}:
            self.parts.append("\n")


def plain(value):
    parser = PlainText()
    parser.feed(value or "")
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines() if line.strip())


def xml_text(node, path):
    return [plain("".join(n.itertext())) for n in node.findall(path, NS) if plain("".join(n.itertext()))]


def dara_record(record):
    resource = record.find("o:metadata/a:resource", NS)
    if resource is None:
        raise ValueError("Fallback da|ra metadata unavailable")
    paths = {"title": "a:titles/a:title/a:titleName", "study_id": "a:resourceIdentifier/a:identifier",
             "abstract": "a:descriptions/a:description/a:freetext", "doi": "a:doiProposal",
             "author": "a:creators/a:creator", "topics": ".//a:classifications/a:classification",
             "geography": ".//a:geographicCoverages/a:geographicCoverage", "access": "a:availability/a:availabilityType",
             "version": "a:resourceIdentifier/a:currentVersion", "collection_dates": ".//a:temporalCoverages/a:temporalCoverage"}
    result = {key: xml_text(resource, path) for key, path in paths.items()}
    result["metadata_format"] = "oai_dara"
    result["variables"] = []
    return result


def dc_record(record):
    dc = record.find("o:metadata/odc:dc", NS) if record is not None else None
    if dc is None:
        return {"metadata_error": "Provider advertises this identifier but supplies neither DDI, da|ra nor Dublin Core metadata"}
    fields = {"title": "title", "abstract": "description", "author": "creator", "topics": "subject",
              "geography": "coverage", "access": "rights", "identifiers": "identifier", "publication_date": "date"}
    result = {key: xml_text(dc, f"dc:{field}") for key, field in fields.items()}
    result["metadata_format"] = "oai_dc"
    result["variables"] = []
    return result


def ddi_record(record, client=None):
    header = record.find("o:header", NS)
    identifier = header.findtext("o:identifier", namespaces=NS)
    if header.get("status") == "deleted":
        return identifier, {"deleted": True}
    book = record.find("o:metadata/d:codeBook", NS)
    if book is None:
        if client is not None:
            raw = client.get(OAI, {"verb": "GetRecord", "metadataPrefix": "oai_dara", "identifier": identifier},
                             "oai-fallback/" + hashlib.sha256(identifier.encode()).hexdigest() + ".xml")
            fallback = ET.fromstring(raw).find("o:GetRecord/o:record", NS)
            if fallback is not None and fallback.find("o:metadata/a:resource", NS) is not None:
                result = dara_record(fallback)
            else:
                raw = client.get(OAI, {"verb": "GetRecord", "metadataPrefix": "oai_dc", "identifier": identifier},
                                 "oai-dc-fallback/" + hashlib.sha256(identifier.encode()).hexdigest() + ".xml")
                result = dc_record(ET.fromstring(raw).find("o:GetRecord/o:record", NS))
            result["modified"] = header.findtext("o:datestamp", namespaces=NS)
            return identifier, result
        raise ValueError(f"Missing DDI codebook for {identifier}")
    paths = {
        "title": ".//d:stdyDscr/d:citation/d:titlStmt/d:titl",
        "study_id": ".//d:stdyDscr/d:citation/d:titlStmt/d:IDNo",
        "abstract": ".//d:stdyDscr/d:stdyInfo/d:abstract",
        "doi": ".//d:stdyDscr/d:citation/d:rspStmt/d:othId[@type='DOI']",
        "author": ".//d:stdyDscr/d:citation/d:rspStmt/d:AuthEnty",
        "topics": ".//d:stdyDscr/d:stdyInfo/d:subject/d:topcClas",
        "geography": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:geogCover",
        "geographic_unit": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:geogUnit",
        "analysis_unit": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:anlyUnit",
        "universe": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:universe",
        "data_kind": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:dataKind",
        "collection_dates": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:collDate",
        "time_period": ".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:timePrd",
        "access": ".//d:stdyDscr/d:dataAccs/d:useStmt/d:restrctn",
        "access_status": ".//d:stdyDscr/d:dataAccs/d:setAvail/d:avlStatus",
        "access_place": ".//d:stdyDscr/d:dataAccs/d:setAvail/d:accsPlac",
        "collection_method": ".//d:stdyDscr/d:method/d:dataColl/d:collMode",
        "sampling": ".//d:stdyDscr/d:method/d:dataColl/d:sampProc",
        "version": ".//d:stdyDscr/d:citation/d:verStmt/d:version",
        "metadata_rights": ".//d:docDscr/d:citation/d:prodStmt/d:copyright",
    }
    result = {k: xml_text(book, path) for k, path in paths.items()}
    result["modified"] = header.findtext("o:datestamp", namespaces=NS)
    result["date_attributes"] = [dict(n.attrib) for n in book.findall(".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:timePrd", NS)
                                 + book.findall(".//d:stdyDscr/d:stdyInfo/d:sumDscr/d:collDate", NS) if n.attrib]
    result["variables"] = [{"id": v.get("ID"), "name": v.get("name"), "label": xml_text(v, "d:labl"),
                            "question": xml_text(v, "d:qstn/d:qstnLit")} for v in book.findall(".//d:dataDscr/d:var", NS)]
    return identifier, result


class Client:
    def __init__(self, folder, delay):
        self.folder = folder
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "GeoLAB-GESIS-metadata-harvester/1.0 (+https://geolab.soz.uni-bielefeld.de/)"

    def get(self, url, params, relative):
        target = self.folder / "raw" / relative
        request_url = requests.Request("GET", url, params=params).prepare().url
        if target.exists():
            provenance = json.loads(target.with_suffix(target.suffix + ".meta.json").read_text())
            raw = gzip.decompress(target.read_bytes()) if target.suffix == ".gz" else target.read_bytes()
            if provenance["url"] != request_url or provenance["sha256"] != hashlib.sha256(raw).hexdigest():
                raise ValueError(f"Cached request or checksum mismatch: {target}; use a fresh snapshot folder")
            return raw
        for attempt in range(5):
            try:
                response = self.session.get(url, params=params, timeout=(20, 180))
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 4:
                    raise
                time.sleep(2 ** (attempt + 2))
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                delay = response.headers.get("Retry-After", "")
                time.sleep(min(300, int(delay) if delay.isdigit() else 2 ** (attempt + 2)))
                continue
            response.raise_for_status()
            if "just a moment" in response.text[:500].lower():
                raise RuntimeError("Provider challenge page; no bypass attempted")
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(target.suffix + ".part")
            part.write_bytes(gzip.compress(response.content) if target.suffix == ".gz" else response.content)
            part.replace(target)
            provenance = {"url": response.url, "fetched_at": datetime.now(timezone.utc).isoformat(),
                          "sha256": hashlib.sha256(response.content).hexdigest(), "bytes": len(response.content)}
            target.with_suffix(target.suffix + ".meta.json").write_text(json.dumps(provenance, indent=2) + "\n")
            time.sleep(self.delay)
            return response.content
        raise RuntimeError(f"Provider failed after retries: {url}")


def database(folder):
    connection = sqlite3.connect(folder / "catalogue.sqlite")
    connection.execute("CREATE TABLE IF NOT EXISTS documents(kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id))")
    return connection


def harvest_oai(client, connection, language):
    token = None
    visited = set()
    page = 0
    total = 0
    identifiers = set()
    gaps = []
    while True:
        params = {"verb": "ListRecords", "resumptionToken": token} if token else {"verb": "ListRecords", "metadataPrefix": f"oai_ddi25-{language}"}
        raw = client.get(OAI, params, f"oai-{language}/page-{page:05d}.xml")
        document = ET.fromstring(raw)
        errors = document.findall("o:error", NS)
        if errors:
            raise RuntimeError("; ".join(f"{e.get('code')}: {e.text}" for e in errors))
        records = document.findall("o:ListRecords/o:record", NS)
        if not records:
            raise ValueError("Empty OAI page before termination")
        values = [ddi_record(r, client) for r in records]
        for identifier, metadata in values:
            if identifier in identifiers:
                raise ValueError("OAI returned a duplicate identifier across pages")
            identifiers.add(identifier)
            if metadata.get("metadata_error"):
                gaps.append({"identifier": identifier, "error": metadata["metadata_error"]})
        connection.executemany("INSERT OR REPLACE INTO documents VALUES (?,?,?)",
                               [(f"oai_{language}", key, json.dumps(value, ensure_ascii=False)) for key, value in values])
        connection.commit()
        total += len(values)
        next_token = document.find("o:ListRecords/o:resumptionToken", NS)
        token = next_token.text.strip() if next_token is not None and next_token.text else None
        print(f"OAI {language}: page {page}, records {total}", flush=True)
        if not token:
            break
        if token in visited:
            raise ValueError("Repeated OAI resumption token")
        visited.add(token)
        page += 1
    return {"records": total, "pages": page + 1, "complete": True, "metadata_gaps": gaps}


def sparql(client, query, path):
    document = json.loads(client.get(SPARQL, {"query": query, "format": "json"}, path))
    if "results" not in document:
        raise ValueError("Unexpected SPARQL response")
    return document["results"]["bindings"]


def decode_triples(rows, counts):
    documents = {r["id"]["value"]: defaultdict(list) for r in counts}
    expected = {r["id"]["value"]: int(r["triples"]["value"]) for r in counts}
    for row in rows:
        identifier = row["id"]["value"]
        if identifier not in documents:
            raise ValueError("Triple response contains an unrequested resource")
        value = row["o"]
        documents[identifier][row["p"]["value"]].append({
            "value": value["value"], "type": value["type"],
            "language": value.get("xml:lang", ""), "datatype": value.get("datatype", "")})
    for identifier, fields in documents.items():
        actual = sum(map(len, fields.values()))
        if actual != expected[identifier]:
            raise ValueError(f"Truncated resource {identifier}: {actual}/{expected[identifier]} triples")
    return documents


def graph_query(kind, after, page_size, counts=False):
    type_uri = SCHEMA + "Dataset" if kind == "dataset" else DDI + "Variable"
    select = "?id (COUNT(?p) AS ?triples)" if counts else "?id ?p ?o"
    end = "GROUP BY ?id ORDER BY ?id" if counts else "ORDER BY ?id ?p ?o LIMIT 10000"
    return f'''SELECT {select}
      WHERE {{ {{ SELECT DISTINCT ?id WHERE {{ ?id a <{type_uri}> FILTER(STR(?id) > {json.dumps(after)}) }} ORDER BY ?id LIMIT {page_size} }}
        ?id ?p ?o }} {end}'''


def harvest_graph(client, connection, kind, page_size):
    type_uri = SCHEMA + "Dataset" if kind == "dataset" else DDI + "Variable"
    count_query = f"SELECT (COUNT(DISTINCT ?id) AS ?count) WHERE {{ ?id a <{type_uri}> }}"
    reported = int(sparql(client, count_query, f"graph-{kind}/count.json")[0]["count"]["value"])
    after = ""
    page = 0
    total = 0
    effective_size = page_size
    while True:
        # Count each subject before requesting its triples: the public endpoint caps
        # SELECT responses at 10,000 rows. GROUP_CONCAT silently fails on long text.
        while True:
            counts = sparql(client, graph_query(kind, after, effective_size, counts=True),
                            f"graph-{kind}/v3/counts-{page:05d}-{effective_size}.json")
            expected = sum(int(r["triples"]["value"]) for r in counts)
            if expected <= 9500:
                break
            if effective_size == 1:
                raise ValueError("A single resource exceeds the provider row limit; separate predicate pagination is required")
            effective_size = max(1, min(effective_size - 1, int(effective_size * 9000 / expected)))
        if not counts:
            break
        rows = sparql(client, graph_query(kind, after, effective_size),
                      f"graph-{kind}/v3/triples-{page:05d}-{effective_size}.json.gz")
        decoded = decode_triples(rows, counts)
        documents = []
        for identifier, fields in decoded.items():
            if identifier <= after:
                raise ValueError("SPARQL keyset pagination failed to advance")
            documents.append(("kg_" + kind, identifier, json.dumps(fields, ensure_ascii=False)))
        connection.executemany("INSERT OR REPLACE INTO documents VALUES (?,?,?)", documents)
        connection.commit()
        total += len(documents)
        after = counts[-1]["id"]["value"]
        print(f"GESIS KG {kind}: {total}/{reported}", flush=True)
        page += 1
        if expected < 4000:
            effective_size = min(page_size, effective_size * 2)
    actual = connection.execute("SELECT COUNT(*) FROM documents WHERE kind=?", ("kg_" + kind,)).fetchone()[0]
    if actual != reported or total != reported:
        raise ValueError(f"Incomplete graph harvest: {kind}: unique={actual}, fetched={total}, reported={reported}")
    return {"reported": reported, "records": actual, "pages": page, "complete": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--stage", choices=["all", "oai", "graph", "datasets", "variables"], default="all")
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()
    if not 1 <= args.page_size <= 10000 or args.delay < 0:
        parser.error("Use page size 1..10000 and a nonnegative delay")
    args.folder.mkdir(parents=True, exist_ok=True)
    client = Client(args.folder, args.delay)
    connection = database(args.folder)
    report_file = args.folder / "HARVEST_REPORT.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {"started": datetime.now(timezone.utc).isoformat(), "scope": "All public GESIS dataset and variable metadata; not publications or microdata", "stages": {}}
    stages = []
    if args.stage in {"all", "oai"}:
        stages.append(("oai_de", lambda: harvest_oai(client, connection, "de")))
        stages.append(("oai_en", lambda: harvest_oai(client, connection, "en")))
    if args.stage in {"all", "graph", "datasets"}:
        stages.append(("kg_dataset", lambda: harvest_graph(client, connection, "dataset", args.page_size)))
    if args.stage in {"all", "graph", "variables"}:
        stages.append(("kg_variable", lambda: harvest_graph(client, connection, "variable", args.page_size)))
    for stage, function in stages:
        if report["stages"].get(stage, {}).get("complete"):
            actual = connection.execute("SELECT COUNT(*) FROM documents WHERE kind=?", (stage,)).fetchone()[0]
            if actual != report["stages"][stage]["records"]:
                raise ValueError(f"Cached stage {stage} database count changed; use a fresh snapshot")
            print(f"Verified cached stage {stage}", flush=True)
            continue
        try:
            report["stages"][stage] = function()
        except Exception as error:
            report["stages"][stage] = {"complete": False, "error": str(error)}
            report_file.write_text(json.dumps(report, indent=2) + "\n")
            raise
        report["updated"] = datetime.now(timezone.utc).isoformat()
        report_file.write_text(json.dumps(report, indent=2) + "\n")
    connection.close()


if __name__ == "__main__":
    main()
