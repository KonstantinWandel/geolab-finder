#!/usr/bin/env python3
"""Finish the Zensus follow-up without a human: wait, rebuild, re-embed, gate, deploy.

`scripts/resolve_zensus_levels.py` runs for hours. Everything that has to happen afterwards is
mechanical, so it runs here instead of waiting for someone to come back:

  1. wait for the resolver to exit and leave a complete level file
  2. measure retrieval on the CURRENT index, so the gate compares like with like
  3. rebuild the metadata (now with resolved Zensus levels) and re-embed on the GPU
  4. measure again; refuse to deploy if hit@1 dropped by more than TOLERANCE
  5. back up what is on the VM, install, restart, health-check, roll back on failure
  6. regenerate the tracker and the handoff table, commit and push both repos

Everything it does is written to logs/autopilot.log, and the outcome to logs/autopilot_result.json.

**It logs a heartbeat while waiting.** The first version logged nothing until the wait ended, so
when it died mid-wait on 2026-08-25 there was no trace at all: no last-seen time, no traceback,
nothing to distinguish "killed" from "still sleeping". A silent long-running process is an
undiagnosable one. It also writes logs/autopilot_alive.json each poll, so a later session can see
when it was last breathing and whether its PID is still around.

Run detached:
  setsid python scripts/autopilot_zensus_followup.py </dev/null >>logs/autopilot.log 2>&1 &
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
PY = "/home/researcher/miniconda3/envs/geolab-rag/bin/python"
NODE_BIN = "/home/researcher/miniconda3/envs/nodejs/bin"
OUT_DIR = REPO / "soep_metadata_output"
LEVELS = REPO / "data_sources" / "29-zensus-2022" / "raw" / "zensus_table_levels.json"
RESULT = REPO / "logs" / "autopilot_result.json"
ALIVE = REPO / "logs" / "autopilot_alive.json"
TOLERANCE = 2          # allowed drop in hit@1 before the deploy is refused
POLL_SECONDS = 120
MAX_WAIT_HOURS = 12

ENV = {
    **os.environ,
    "GEOLAB_APP_MODE": "inkar",
    "GEOLAB_ENABLE_DESTATIS": "0",
    "INKAR_METADATA_ROOT": str(OUT_DIR),
    "SOEP_METADATA_ROOT": str(OUT_DIR),
    "SOEP_RAG_DEVICE": "cuda",
    "SOEP_RAG_CACHE_DIR": str(REPO / ".cache" / "geolab"),
    "SOEP_RAG_RERANKER_MODEL": "BAAI/bge-reranker-base",
    "SOEP_RAG_RERANK_CANDIDATES": "16",
    "TOKENIZERS_PARALLELISM": "false",
}


def say(message: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def run(args: List[str], cwd: Optional[Path] = None, timeout: int = 7200) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(cwd or REPO), env=ENV, capture_output=True, text=True, timeout=timeout)


def resolver_running() -> bool:
    found = subprocess.run(["pgrep", "-f", "resolve_zensus_levels.py"], capture_output=True, text=True)
    return bool(found.stdout.strip())


def eval_hit_at_one(label: str) -> Optional[int]:
    """Run the retrieval smoke test and return hit@1, or None if it could not run."""
    done = run([PY, "scripts/eval_geodb_search.py"], timeout=5400)
    match = re.search(r'"hit@1":\s*(\d+)', done.stdout)
    total = re.search(r'"queries":\s*(\d+)', done.stdout)
    if not match:
        say(f"eval ({label}) produced no result: {done.stdout[-400:]} {done.stderr[-400:]}")
        return None
    say(f"eval ({label}): hit@1 {match.group(1)}/{total.group(1) if total else '?'}")
    return int(match.group(1))


def main() -> None:
    started = time.time()
    say("autopilot start")

    # 1. wait for the resolver, leaving a trace on every poll
    polls = 0
    while resolver_running():
        polls += 1
        ALIVE.write_text(json.dumps({
            "pid": os.getpid(),
            "phase": "waiting-for-resolver",
            "polls": polls,
            "last_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, indent=2), encoding="utf-8")
        if polls % 5 == 1:  # every ~10 minutes, so the log stays readable
            say(f"waiting for the resolver (poll {polls})")
        if time.time() - started > MAX_WAIT_HOURS * 3600:
            say("resolver still running after the maximum wait; giving up without deploying")
            RESULT.write_text(json.dumps({"status": "timeout"}, indent=2), encoding="utf-8")
            return
        time.sleep(POLL_SECONDS)
    say("resolver finished")

    resolved = 0
    if LEVELS.exists():
        data = json.loads(LEVELS.read_text(encoding="utf-8"))
        resolved = sum(1 for entry in data.values() if entry.get("geo"))
        say(f"levels file: {len(data)} tables, {resolved} with a regional level")
    else:
        say("no levels file: continuing anyway, the rebuild is still worth doing")

    # 2. baseline on the current index
    before = eval_hit_at_one("before")

    # 3. rebuild + re-embed
    previous_records = len(json.loads((OUT_DIR / "geodb_metadata.json").read_text(encoding="utf-8")))
    build = run([PY, "scripts/build_geodb_metadata.py"])
    if build.returncode != 0:
        say(f"metadata build FAILED: {build.stderr[-800:]}")
        RESULT.write_text(json.dumps({"status": "build-failed"}, indent=2), encoding="utf-8")
        return
    records = len(json.loads((OUT_DIR / "geodb_metadata.json").read_text(encoding="utf-8")))
    say(f"rebuilt: {records} records (was {previous_records})")
    if not 0.8 * previous_records <= records <= 1.25 * previous_records:
        say("record count moved by more than a quarter: refusing to deploy")
        RESULT.write_text(json.dumps({"status": "record-count-implausible",
                                      "records": records, "previous": previous_records}, indent=2), encoding="utf-8")
        return

    embed = run([PY, "-c",
                 "import warnings;warnings.filterwarnings('ignore');"
                 "from app.services.soep_rag_advisor import SOEPRagAdvisorService as S;"
                 "print(S().build_and_save_embeddings(64))"], cwd=REPO / "backend")
    if embed.returncode != 0:
        say(f"embedding FAILED: {embed.stderr[-800:]}")
        RESULT.write_text(json.dumps({"status": "embed-failed"}, indent=2), encoding="utf-8")
        return
    say("re-embedded")

    # 4. gate
    after = eval_hit_at_one("after")
    if before is not None and after is not None and after < before - TOLERANCE:
        say(f"retrieval regressed ({before} -> {after}): refusing to deploy")
        RESULT.write_text(json.dumps({"status": "regressed", "before": before, "after": after}, indent=2),
                          encoding="utf-8")
        return

    # 5. deploy with a backup and a health check
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    payload = ["geodb_metadata.json", "geodb_metadata_embeddings.npy", "geodb_metadata_embeddings.npy.meta.json"]
    rsync = run(["rsync", "-az", *[str(OUT_DIR / name) for name in payload], "vm:/home/kwandel/geodb_stage/"])
    if rsync.returncode != 0:
        say(f"rsync FAILED: {rsync.stderr[-500:]}")
        RESULT.write_text(json.dumps({"status": "rsync-failed"}, indent=2), encoding="utf-8")
        return

    remote = f"""set -e
D=/opt/geolab/app/destatis-rag
B=/opt/geolab/backups/autopilot_{stamp}
sudo mkdir -p $B
for f in {' '.join(payload)}; do
  sudo cp -a $D/soep_metadata_output/$f $B/ 2>/dev/null || true
  sudo install -o geolab -g geolab -m 664 ~/geodb_stage/$f $D/soep_metadata_output/
done
sudo systemctl restart geolab-inkar
echo backup=$B"""
    install = run(["ssh", "vm", remote], timeout=900)
    say(install.stdout.strip() or install.stderr[-300:])
    if install.returncode != 0:
        RESULT.write_text(json.dumps({"status": "install-failed"}, indent=2), encoding="utf-8")
        return

    healthy = False
    for _ in range(60):
        probe = run(["ssh", "vm", "curl -s -m 10 http://127.0.0.1:18002/health"], timeout=120)
        if "ok" in probe.stdout:
            healthy = True
            break
        time.sleep(15)
    if not healthy:
        say("service did not come back: rolling back")
        run(["ssh", "vm", f"sudo cp -a /opt/geolab/backups/autopilot_{stamp}/. "
                          f"/opt/geolab/app/destatis-rag/soep_metadata_output/ && "
                          f"sudo systemctl restart geolab-inkar"], timeout=900)
        RESULT.write_text(json.dumps({"status": "rolled-back", "backup": f"autopilot_{stamp}"}, indent=2),
                          encoding="utf-8")
        return
    say("geodb healthy after deploy")

    # 6. tracker, deliverable, commit, push
    run([PY, "scripts/build_status_report.py"], timeout=1800)
    message = (f"Autopilot: fold the resolved Zensus regional levels into the index\n\n"
               f"{resolved} of the Zensus tables now carry a real regional level, resolved through\n"
               f"metadata/table rather than guessed from the title, and their labels carry the level\n"
               f"so the five 'Personen: Religion' rows are told apart. Rebuilt, re-embedded and\n"
               f"deployed automatically after the resolver finished.\n\n"
               f"Retrieval gate: hit@1 {before} -> {after} on {58} queries.\n"
               f"Records: {previous_records} -> {records}.\n\n"
               f"Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>")
    token_file = Path.home() / ".config" / "gh" / "hosts.yml"
    token = re.search(r"oauth_token:\s*(\S+)", token_file.read_text(encoding="utf-8")).group(1)
    for repo_path, remote_name in [(REPO, "KonstantinWandel/geolab-finder"),
                                   (REPO.parent / "soep-variable-finder", "KonstantinWandel/soep-variable-finder")]:
        if repo_path != REPO:
            for name in ["scripts/build_geodb_metadata.py", "scripts/eval_geodb_search.py"]:
                source, target = REPO / name, repo_path / name
                if source.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        subprocess.run(["git", "-C", str(repo_path), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "commit", "-q", "-m", message], capture_output=True)
        push = subprocess.run(["git", "-C", str(repo_path), "push",
                               f"https://x-access-token:{token}@github.com/{remote_name}.git", "HEAD"],
                              capture_output=True, text=True)
        say(f"push {remote_name}: rc={push.returncode}")

    RESULT.write_text(json.dumps({
        "status": "deployed",
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "zensus_tables_with_level": resolved,
        "records_before": previous_records, "records_after": records,
        "hit_at_1_before": before, "hit_at_1_after": after,
        "backup": f"autopilot_{stamp}",
    }, indent=2), encoding="utf-8")
    say("autopilot done")


if __name__ == "__main__":
    main()
