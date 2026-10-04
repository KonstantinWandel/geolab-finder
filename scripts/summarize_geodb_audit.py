#!/usr/bin/env python3
"""Make the bounded existing-provider audit reproducible from its measured reports."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    names = ("all-source-urls.json", "existing-link-health.json", "existing-browser-links.json", "existing-facets.json")
    reports = {name: json.loads((args.qa_dir / name).read_text()) for name in names}
    urls = reports[names[0]]["results"]
    links = reports[names[1]]["results"]
    browser = reports[names[2]]["results"]
    facets = reports[names[3]]
    exceptions = []
    for record in urls:
        if record["error"] or not record["status"] or record["status"] >= 400 or record["moved"]:
            target = urlsplit(record["final_url"])
            exceptions.append({"source": record["slug"], "status": record["status"],
                "url": record["url"], "final_origin_path": urlunsplit((target.scheme, target.netloc, target.path, "", "")),
                "error": record["error"], "title": record.get("title", ""),
                "classification": "provider challenge; not bypassed" if record["slug"] in {"gesis", "hochschulkompass"} else "needs review"})
    result = {
        "summarized_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Existing GeoDB providers: sampled availability and reviewed metadata issues, not exhaustive content, licence or semantic-quality certification. TLS validation was disabled in the legacy reachability checker; no TLS-security claim.",
        "root_addresses": {"count": len(urls), "exceptions": exceptions,
                           "unexpected_domain_changes": [r["slug"] for r in urls if r["moved"]]},
        "sampled_links": {"count": len(links), "source_keys": len({r["source_key"] for r in links}),
                          "verdicts": dict(Counter(r["verdict"].split(" ")[0] for r in links))},
        "browser_followup": {"complete": reports[names[2]]["complete"], "count": len(browser),
            "visible_record_evidence": sum(bool(r.get("code_visible") or r.get("label_visible")) for r in browser),
            "unresolved": [{k: r[k] for k in ("source", "url", "code", "error")} for r in browser if r.get("error")]},
        "facets": {"records": facets["records"], "missing": facets["missing_facets"],
                   "link_levels": facets["link_levels"], "unverified_links": facets["unverified_links"],
                   "caution": "Boilerplate mentions of grids, municipalities and coordinates are not evidence that every record has those observation levels. No automatic regex-based facet changes were deployed."},
        "confirmed_metadata_issues": [
            {"item_id": "fdz:10_7807_bridge_2015_v1", "source": "fdz_ruhr", "status": "documented; existing record unchanged",
             "problem": "PLZ-to-municipality crosswalk uses generic Kreis/Bundesland facets, 2005-2024 coverage and source-wide access wording.",
             "provider_evidence": "Provider identifies PLZ/Gemeinden, territorial vintage 2015 and availability NotAvailable. Do not confuse publication in 2017 with observation years.",
             "url": "https://fdz.rwi-essen.de/doi-detail/id-107807bridge2015v1.html",
             "next_action": "Parse per-dataset geographic vintage and access; rebuild and evaluate a separate correction candidate, not a blanket FDZ-source default."},
            {"item_id": "offeneregister:federal_state", "source": "offeneregister", "status": "documented; existing record unchanged",
             "problem": "Explicit register-court state field lacks Bundeslaender facet because all attributes inherit address-level source defaults.",
             "provider_evidence": "Provider documents federal_state as the state of the register court, not the company's verified observation location.",
             "url": "https://offeneregister.de/daten/",
             "next_action": "Apply field-level geography instead of promoting every register attribute to state level; retain the archive's historical collection window."}
        ],
        "input_sha256": {name: hashlib.sha256((args.qa_dir / name).read_bytes()).hexdigest() for name in names},
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(args.output.read_text())


if __name__ == "__main__":
    main()
