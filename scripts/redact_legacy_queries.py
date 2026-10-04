#!/usr/bin/env python3
"""Replace pre-consent raw JSONL logs with daily counts. Stop both backends for --apply.

Preview is the default. Never prints search text or copies raw logs into a backup.
The migration ledger prevents duplicate counts if interrupted between commit and unlink.
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.privacy_store import PrivacyStore


def redact(store, apply=False):
    summaries = []
    for path in sorted(store.directory.glob('queries-????-??.jsonl')):
        counts = Counter()
        with path.open(encoding='utf-8') as source:
            for line in source:
                try:
                    row = json.loads(line)
                    day = datetime.fromisoformat(row['ts']).date().isoformat()
                    mode = row.get('app_mode') or row.get('mode')
                    if mode in {'soep', 'inkar', 'all'}:
                        counts[(mode, day)] += 1
                except (ValueError, KeyError, TypeError):
                    continue
        if apply:
            with store.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS legacy_migrations (filename TEXT PRIMARY KEY)')
                if not db.execute('SELECT 1 FROM legacy_migrations WHERE filename=?', (path.name,)).fetchone():
                    for (mode, day), count in counts.items():
                        db.execute('''INSERT INTO service_days VALUES (?, ?, ?)
                            ON CONFLICT(app_mode, day) DO UPDATE SET searches=searches+excluded.searches''', (mode, day, count))
                    db.execute('INSERT INTO legacy_migrations VALUES (?)', (path.name,))
            path.unlink()
        summaries.append({'file': path.name, 'daily_count_rows': len(counts), 'searches': sum(counts.values())})
    for path in store.directory.glob('feedback-????-??.jsonl'):
        if apply:
            path.unlink()
        summaries.append({'file': path.name, 'action': 'delete legacy unverified feedback'})
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(redact(PrivacyStore(Path(os.getenv('GEOLAB_LOG_DIR', '/opt/geolab/logs'))), args.apply), indent=2))
