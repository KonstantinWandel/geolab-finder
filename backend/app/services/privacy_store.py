"""Private, purpose-separated telemetry. Never expose this database through a public route."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONSENT_VERSION = "2026-10-04"
QUALITY_CONSENT_VERSION = "2026-10-04.2"
RETENTION_DAYS = 90


class PrivacyStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def prepare(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o750)
        self.directory.chmod(0o750)

    @contextmanager
    def connect(self):
        self.prepare()
        path = self.directory / "privacy.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        db = sqlite3.connect(path, timeout=10)
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA secure_delete=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS visitor_days (
                app_mode TEXT NOT NULL, visitor_id TEXT NOT NULL, day TEXT NOT NULL,
                visits INTEGER NOT NULL DEFAULT 0, searches INTEGER NOT NULL DEFAULT 0,
                consent_version TEXT NOT NULL,
                PRIMARY KEY (app_mode, visitor_id, day)
            );
            CREATE TABLE IF NOT EXISTS feedback (
                app_mode TEXT NOT NULL, query_id TEXT NOT NULL, item_id TEXT NOT NULL,
                rank INTEGER NOT NULL, vote TEXT NOT NULL, day TEXT NOT NULL,
                embedding_model TEXT NOT NULL, reranker_model TEXT NOT NULL,
                PRIMARY KEY (app_mode, query_id, item_id)
            );
            CREATE TABLE IF NOT EXISTS service_days (
                app_mode TEXT NOT NULL, day TEXT NOT NULL, searches INTEGER NOT NULL,
                PRIMARY KEY (app_mode, day)
            );
            CREATE TABLE IF NOT EXISTS quality_queries (
                app_mode TEXT NOT NULL, query_id TEXT NOT NULL, quality_id TEXT NOT NULL,
                day TEXT NOT NULL, question TEXT NOT NULL, filters TEXT NOT NULL,
                top_results TEXT NOT NULL, duration REAL NOT NULL, consent_version TEXT NOT NULL,
                PRIMARY KEY (app_mode, query_id)
            );
            CREATE TABLE IF NOT EXISTS quality_withdrawals (
                app_mode TEXT NOT NULL, quality_id TEXT NOT NULL, day TEXT NOT NULL,
                PRIMARY KEY (app_mode, quality_id)
            );
            CREATE TABLE IF NOT EXISTS visitor_withdrawals (
                app_mode TEXT NOT NULL, visitor_id TEXT NOT NULL, day TEXT NOT NULL,
                PRIMARY KEY (app_mode, visitor_id)
            );
        """)
        try:
            with db:
                yield db
        finally:
            db.close()

    def event(self, mode, visitor_id, event):
        day = datetime.now(timezone.utc).date().isoformat()
        visits, searches = (1, 0) if event == "visit" else (0, 1)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM visitor_withdrawals WHERE app_mode=? AND visitor_id=?', (mode, visitor_id)).fetchone():
                return
            db.execute("""INSERT INTO visitor_days VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_mode, visitor_id, day) DO UPDATE SET
                visits=visits+excluded.visits, searches=searches+excluded.searches
                """, (mode, visitor_id, day, visits, searches, CONSENT_VERSION))

    def withdraw(self, mode, visitor_id):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO visitor_withdrawals VALUES (?, ?, ?)',
                       (mode, visitor_id, datetime.now(timezone.utc).date().isoformat()))
            db.execute("DELETE FROM visitor_days WHERE app_mode=? AND visitor_id=?", (mode, visitor_id))

    def search(self, mode, query_id, question, filters, rows, duration, quality_id=None):
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            db.execute("""INSERT INTO service_days VALUES (?, ?, 1)
                ON CONFLICT(app_mode, day) DO UPDATE SET searches=searches+1""", (mode, day))
            if quality_id and not db.execute("SELECT 1 FROM quality_withdrawals WHERE app_mode=? AND quality_id=?",
                                           (mode, quality_id)).fetchone():
                db.execute("INSERT INTO quality_queries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (mode, query_id, quality_id, day, question, json.dumps(filters),
                            json.dumps([row.get('item_id') for row in rows[:5]]), duration,
                            QUALITY_CONSENT_VERSION))

    def withdraw_quality(self, mode, quality_id):
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            # Reject delayed searches as well as deleting already completed ones.
            db.execute("INSERT OR REPLACE INTO quality_withdrawals VALUES (?, ?, ?)", (mode, quality_id, day))
            db.execute("""DELETE FROM feedback WHERE app_mode=? AND query_id IN
                (SELECT query_id FROM quality_queries WHERE app_mode=? AND quality_id=?)""", (mode, mode, quality_id))
            db.execute("DELETE FROM quality_queries WHERE app_mode=? AND quality_id=?", (mode, quality_id))

    def key(self):
        self.prepare()
        path = self.directory / ".feedback-signing-key"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(secrets.token_bytes(32))
        # A second worker may have observed the file before the first finished writing it.
        for _ in range(20):
            key = path.read_bytes()
            if len(key) == 32:
                return key
            time.sleep(0.01)
        raise OSError("Feedback signing key unavailable")

    def token(self, mode, query_id, rows, models):
        payload = json.dumps({
            "mode": mode, "query_id": query_id, "issued": int(time.time()),
            "items": [str(row.get("item_id", "")) for row in rows], "models": models,
        }, separators=(",", ":")).encode()
        data = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(self.key(), data.encode(), hashlib.sha256).hexdigest()
        return f"{data}.{signature}"

    def feedback(self, mode, query_id, item_id, vote, token):
        try:
            data, signature = token.rsplit(".", 1)
            expected = hmac.new(self.key(), data.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("Invalid feedback token")
            payload = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)))
            age = time.time() - payload["issued"]
            if payload["mode"] != mode or payload["query_id"] != query_id or not 0 <= age < RETENTION_DAYS * 86400:
                raise ValueError("Expired or mismatched feedback token")
            rank = payload["items"].index(item_id) + 1
            embedding, reranker = payload["models"]
        except (ValueError, KeyError, TypeError, IndexError, binascii.Error) as exc:
            raise ValueError("Invalid or expired feedback token") from exc
        if vote not in {"useful", "not_useful", None}:
            raise ValueError("Invalid vote")
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            if vote is None:
                db.execute("DELETE FROM feedback WHERE app_mode=? AND query_id=? AND item_id=?", (mode, query_id, item_id))
                return
            db.execute("""INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_mode, query_id, item_id) DO UPDATE SET vote=excluded.vote
                """, (mode, query_id, item_id, rank, vote, day, embedding, reranker))

    def purge(self, now=None):
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
        with self.connect() as db:
            db.execute("DELETE FROM visitor_days WHERE day < ?", (cutoff.date().isoformat(),))
            db.execute("DELETE FROM feedback WHERE day < ?", (cutoff.date().isoformat(),))
            db.execute("DELETE FROM quality_queries WHERE day < ?", (cutoff.date().isoformat(),))
            db.execute("DELETE FROM quality_withdrawals WHERE day < ?", (cutoff.date().isoformat(),))
            db.execute("DELETE FROM visitor_withdrawals WHERE day < ?", (cutoff.date().isoformat(),))
        # Rewrite old monthly files only: searches append to the current month's file.
        current = (now or datetime.now(timezone.utc)).strftime("%Y-%m")
        for path in [*self.directory.glob("queries-????-??.jsonl"),
                     *self.directory.glob("feedback-????-??.jsonl")]:
            if path.stem.endswith(current):
                continue
            temporary = path.with_suffix(".purging")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            kept = 0
            with path.open(encoding="utf-8") as source, os.fdopen(fd, "w", encoding="utf-8") as target:
                for line in source:
                    try:
                        stamp = datetime.fromisoformat(json.loads(line)["ts"])
                        if stamp >= cutoff:
                            target.write(line)
                            kept += 1
                    except (ValueError, KeyError, TypeError):
                        # A malformed line cannot establish a lawful retention interval.
                        continue
            if kept:
                temporary.replace(path)
            else:
                temporary.unlink()
                path.unlink()
        with self.connect() as db:
            db.execute("VACUUM")

    def metrics(self):
        with self.connect() as db:
            rows = db.execute("""SELECT app_mode, substr(day,1,7), COUNT(DISTINCT visitor_id),
                SUM(visits), SUM(searches) FROM visitor_days GROUP BY 1,2 ORDER BY 1,2""").fetchall()
            return [{"app_mode": mode, "month": month, "consenting_browsers": browsers,
                     "visits": visits, "searches": searches,
                     "returning_browsers": db.execute("""SELECT COUNT(*) FROM (
                         SELECT visitor_id FROM visitor_days WHERE app_mode=? AND substr(day,1,7)=?
                         GROUP BY visitor_id HAVING COUNT(*) > 1)""", (mode, month)).fetchone()[0]}
                    for mode, month, browsers, visits, searches in rows]

    def service_metrics(self):
        with self.connect() as db:
            return [{"app_mode": mode, "day": day, "searches": count}
                    for mode, day, count in db.execute('SELECT app_mode, day, searches FROM service_days ORDER BY 1,2')]
