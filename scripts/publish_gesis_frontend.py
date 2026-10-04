#!/usr/bin/env python3
"""Publish a browser-tested GeoDB build, preserving old bundles and other apps."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from deploy_gesis_index import site_hashes

ROOT = Path(__file__).resolve().parents[1]
GEODB = "https://geodb.geolab.soz.uni-bielefeld.de/"


def command(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--check", type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve()
    check = json.loads(args.check.read_text())
    html = (build / "index.html").read_bytes()
    expected = hashlib.sha256(html).hexdigest()
    if not check["passed"] or check["build_index_sha256"] != expected or b"%VITE_" in html:
        raise ValueError("Build does not match the passing browser check")
    before = site_hashes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = f"/home/kwandel/geodb-ui-{stamp}"
    backup = f"/opt/geolab/backups/gesis-frontend-{stamp}"
    command(["ssh", "vm", "mkdir", "-p", stage])
    command(["rsync", "-az", str(build) + "/", "vm:" + stage + "/"])
    checksums = "\n".join(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {stage}/{file.relative_to(build)}"
                          for file in sorted(build.rglob("*")) if file.is_file())
    script = r'''set -euo pipefail
root=/opt/geolab/sites/inkar
exec 9>"$root/.gesis-frontend.lock"
flock -n 9
test "$(sha256sum "$root/index.html" | cut -d' ' -f1)" = OLD_HASH
sha256sum -c <<'CHECKSUMS'
CHECKS
CHECKSUMS
cp -a "$root" BACKUP
rollback(){
  code=$?
  if [ "$code" -ne 0 ]; then
    rsync -a BACKUP/ "$root/"
    echo "Previous GeoDB frontend restored" >&2
  fi
  exit "$code"
}
trap rollback EXIT
rsync -a --exclude=index.html STAGE/ "$root/"
install -o geolab -g geolab -m 644 STAGE/index.html "$root/.index.next"
mv "$root/.index.next" "$root/index.html"
chown -R geolab:geolab "$root"
curl -fsS --max-time 20 http://127.0.0.1:18002/health | grep -q '"status":"ok"'
test "$(curl -fsS --max-time 60 https://geodb.geolab.soz.uni-bielefeld.de/ | sha256sum | cut -d' ' -f1)" = NEW_HASH
'''.replace("OLD_HASH", before[GEODB]).replace("NEW_HASH", expected).replace("CHECKS\n", checksums + "\n").replace("BACKUP", backup).replace("STAGE", stage)
    command(["ssh", "vm", "sudo", "bash", "-s"], input=script)
    after = site_hashes()
    if after[GEODB] != expected or any(after[url] != value for url, value in before.items() if url != GEODB):
        raise ValueError("Published hashes differ, or another app changed concurrently; inspect before claiming completion")
    report = {"published_at": stamp, "build_index_sha256": expected, "backup": backup,
              "before": before, "after": after, "other_roots_unchanged": True,
              "old_bundles_retained": True, "service_restart": False,
              "local_browser_check_sha256": hashlib.sha256(args.check.read_bytes()).hexdigest()}
    (ROOT / "data_sources/gesis/FRONTEND_DEPLOYMENT_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
