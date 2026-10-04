#!/usr/bin/env python3
"""Deploy only the tested GeoDB index, with a concurrent-change guard and rollback."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FILES = ("geodb_metadata.json", "geodb_metadata_embeddings.npy", "geodb_metadata_embeddings.npy.meta.json", "geodb_build_info.json")
SITES = ("https://geolab.soz.uni-bielefeld.de/", "https://geodb.geolab.soz.uni-bielefeld.de/",
         "https://soep-faiss.geolab.soz.uni-bielefeld.de/", "https://germaparl.geolab.soz.uni-bielefeld.de/")


def command(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def site_hashes():
    result = {}
    for url in SITES:
        with urllib.request.urlopen(url, timeout=60) as response:
            result[url] = hashlib.sha256(response.read()).hexdigest()
    return result


def gate(before, after):
    for old, new in zip(before["results"], after["results"], strict=True):
        if old["query"] != new["query"]:
            raise ValueError("Gate case definitions changed")
        if old.get("rank") and not new.get("rank"):
            raise ValueError("Retrieval regression: " + old["query"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--qa-dir", type=Path, required=True)
    args = parser.parse_args()
    index = json.loads((ROOT / "data_sources/gesis/INDEX_REPORT.json").read_text())
    qa = json.loads((ROOT / "data_sources/gesis/QA_REPORT.json").read_text())
    if not qa["passed"] or qa["metadata_sha256"] != index["candidate_files"]["geodb_metadata.json"] or qa["service_sha256"] != index["candidate_service_sha256"]:
        raise ValueError("QA does not describe this index")
    for test in ("smoke", "hard"):
        gate(json.loads((args.qa_dir / f"baseline-{test}.json").read_text()),
             json.loads((args.qa_dir / f"candidate-{test}.json").read_text()))
    additional = json.loads((args.qa_dir / "gesis-retrieval.json").read_text())
    if not additional.get("passed"):
        raise ValueError("GESIS retrieval and metadata-safety checks have not passed")
    hashes = index["candidate_files"]
    service = ROOT / "backend/app/services/soep_rag_advisor.py"
    with service.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != index["candidate_service_sha256"]:
            raise ValueError("Service changed after candidate preparation")
    for filename in FILES:
        with (args.candidate / filename).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != hashes[filename]:
                raise ValueError("Candidate changed after embedding: " + filename)
    before = site_hashes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = f"/home/kwandel/geodb-gesis-stage-{stamp}"
    command(["ssh", "vm", "mkdir", "-p", stage])
    command(["rsync", "-az", *(str(args.candidate / f) for f in FILES), "vm:" + stage + "/"])
    command(["rsync", "-az", str(service), "vm:" + stage + "/"])
    checks = "\n".join(f"{hashes[f]}  {stage}/{f}" for f in FILES)
    script = r'''set -euo pipefail
root=/opt/geolab/app/destatis-rag/soep_metadata_output
service=/opt/geolab/app/destatis-rag/backend/app/services/soep_rag_advisor.py
exec 9>"$root/.gesis-deploy.lock"
flock -n 9
test "$(sha256sum "$root/geodb_metadata.json" | cut -d' ' -f1)" = BASELINE
test "$(sha256sum "$root/geodb_metadata_embeddings.npy" | cut -d' ' -f1)" = VECTOR_BASELINE
test "$(sha256sum "$service" | cut -d' ' -f1)" = SERVICE_BASELINE
test "$(sha256sum STAGE/soep_rag_advisor.py | cut -d' ' -f1)" = SERVICE_CANDIDATE
sha256sum -c <<'CHECKSUMS'
CHECKS
CHECKSUMS
backup=/opt/geolab/backups/gesis-STAMP
mkdir -p "$backup"
files=(geodb_metadata.json geodb_metadata_embeddings.npy geodb_metadata_embeddings.npy.meta.json geodb_build_info.json)
for file in "${files[@]}"; do cp -a "$root/$file" "$backup/"; done
cp -a "$service" "$backup/soep_rag_advisor.py"
rollback(){
  code=$?
  if [ "$code" -ne 0 ]; then
    for file in "${files[@]}"; do cp -a "$backup/$file" "$root/$file"; done
    cp -a "$backup/soep_rag_advisor.py" "$service"
    systemctl restart geolab-inkar
    echo "Deployment failed; previous GeoDB restored" >&2
  fi
  exit "$code"
}
trap rollback EXIT
systemctl stop geolab-inkar
for file in "${files[@]}"; do install -o geolab -g geolab -m 664 STAGE/"$file" "$root/$file"; done
install -o geolab -g geolab -m 664 STAGE/soep_rag_advisor.py "$service"
systemctl start geolab-inkar
healthy=0
for attempt in $(seq 1 40); do
  if curl -fsS --max-time 10 http://127.0.0.1:18002/health | grep -q '"status":"ok"'; then healthy=1; break; fi
  sleep 5
done
test "$healthy" = 1
/opt/geolab/.venv/bin/python - <<'VERIFY'
import json, urllib.request
body = json.dumps({"question": "Bundesland des Wohnorts", "top_k": 3, "dataset_scope": "gesis"}).encode()
request = urllib.request.Request("http://127.0.0.1:18002/api/soep/advice", data=body, headers={"Content-Type":"application/json"})
with urllib.request.urlopen(request, timeout=120) as response: result = json.load(response)
rows = result["recommended_variables"]
assert rows and all(r["source_key"] == "gesis" and r["metadata_only"] and not r["map_ready"] for r in rows)
print(json.dumps({"verified_gesis_results": len(rows), "labels": [r["label"] for r in rows]}, ensure_ascii=False))
VERIFY
echo "Backup: $backup"
'''.replace("VECTOR_BASELINE", index["baseline_vectors_sha256"]).replace("SERVICE_BASELINE", index["baseline_service_sha256"]).replace("SERVICE_CANDIDATE", index["candidate_service_sha256"]).replace("BASELINE", index["baseline_metadata_sha256"]).replace("CHECKS\n", checks + "\n").replace("STAMP", stamp).replace("STAGE", stage)
    output = command(["ssh", "vm", "sudo", "bash", "-s"], input=script)
    after = site_hashes()
    if before != after:
        raise ValueError("A site's root HTML changed concurrently; inspect before claiming unchanged sites")
    report = {"deployed_at": stamp, "index": index, "checks": output.strip(),
              "root_html_unchanged": after, "backup": "/opt/geolab/backups/gesis-" + stamp,
              "changed_service": "geolab-inkar", "app_code_changed": "Provider-resource identity, bounded GeoDB provider-diverse candidates and exact alphanumeric-code lookup; SOEP ranking path unchanged"}
    (ROOT / "data_sources/gesis/DEPLOYMENT_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
