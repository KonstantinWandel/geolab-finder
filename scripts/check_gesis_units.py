#!/usr/bin/env python3
"""Record unit checks using each component's existing environment."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def worker(pattern):
    output = io.StringIO()
    with redirect_stdout(output):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "scripts"), pattern=pattern)
        result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    return {"pattern": pattern, "tests": result.testsRun, "passed": result.wasSuccessful(),
            "interpreter": sys.executable, "skipped": len(result.skipped), "output": output.getvalue()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geo-python", default=str(Path.home() / "miniconda3/envs/geo/bin/python"))
    parser.add_argument("--rag-python", default=str(Path.home() / "miniconda3/envs/geolab-rag/bin/python"))
    parser.add_argument("--worker-pattern", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_pattern:
        print(json.dumps(worker(args.worker_pattern)))
        return
    checks = []
    for interpreter, pattern in ((args.geo_python, "test*gesis*.py"), (args.rag_python, "test_geodb_*.py")):
        result = subprocess.run([interpreter, str(Path(__file__).resolve()), "--worker-pattern", pattern],
                                text=True, capture_output=True, check=True)
        checks.append(json.loads(result.stdout))
    report = {"tested_at": datetime.now(timezone.utc).isoformat(), "interpreter": sys.executable,
              "passed": all(c["passed"] and c["tests"] for c in checks), "checks": checks}
    (ROOT / "data_sources/gesis/UNIT_TEST_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
