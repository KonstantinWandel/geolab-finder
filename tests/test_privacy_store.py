import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.privacy_store import PrivacyStore


class PrivacyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PrivacyStore(Path(self.temp.name) / 'private')

    def tearDown(self):
        self.temp.cleanup()

    def test_analytics_separated_and_withdrawable(self):
        self.store.event('soep', 'a' * 32, 'visit')
        self.store.event('soep', 'a' * 32, 'search')
        self.store.event('inkar', 'a' * 32, 'visit')
        self.assertEqual(self.store.metrics()[1]['consenting_browsers'], 1)
        with self.store.connect() as db:
            columns = {row[1] for row in db.execute('PRAGMA table_info(visitor_days)')}
            self.assertFalse(columns & {'question', 'query_id', 'ip', 'user_agent'})
        self.store.withdraw('soep', 'a' * 32)
        self.assertEqual([r['app_mode'] for r in self.store.metrics()], ['inkar'])

    def test_feedback_validated_and_updated_without_visitor_id(self):
        token = self.store.token('soep', 'b' * 16, [{'item_id': 'x'}, {'item_id': 'y'}], ['embedding-v1', 'reranker-v1'])
        self.store.feedback('soep', 'b' * 16, 'y', 'useful', token)
        self.store.feedback('soep', 'b' * 16, 'y', 'not_useful', token)
        with self.store.connect() as db:
            rows = db.execute('SELECT rank, vote, embedding_model FROM feedback').fetchall()
            columns = {row[1] for row in db.execute('PRAGMA table_info(feedback)')}
        self.assertEqual(rows, [(2, 'not_useful', 'embedding-v1')])
        self.assertNotIn('visitor_id', columns)
        for mode, query, item, signed in [('inkar', 'b' * 16, 'y', token), ('soep', 'c' * 16, 'y', token),
                                          ('soep', 'b' * 16, 'z', token), ('soep', 'b' * 16, 'y', token + 'a')]:
            with self.assertRaises(ValueError):
                self.store.feedback(mode, query, item, 'useful', signed)
        self.assertEqual(PrivacyStore(self.store.directory).key(), self.store.key())
        self.assertEqual(os.stat(self.store.directory / '.feedback-signing-key').st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.store.directory / 'privacy.sqlite3').st_mode & 0o777, 0o600)

    def test_retention_and_returning_browser_count(self):
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        self.store.event('soep', 'a' * 32, 'visit')
        with self.store.connect() as db:
            db.execute("DELETE FROM visitor_days")
            for day in ['2026-06-01', '2026-09-01', '2026-09-02']:
                db.execute("INSERT INTO visitor_days VALUES ('soep', ?, ?, 1, 0, '2026-10-04')", ('a' * 32, day))
        old = self.store.directory / 'queries-2026-06.jsonl'
        old.write_text(json.dumps({'ts': (now - timedelta(days=100)).isoformat()}) + '\n')
        boundary = self.store.directory / 'queries-2026-07.jsonl'
        boundary.write_text('\n'.join(json.dumps({'ts': (now - timedelta(days=days)).isoformat()}) for days in [100, 80]) + '\n')
        current = self.store.directory / 'queries-2026-10.jsonl'
        current.write_text('current file left alone\n')
        self.store.purge(now)
        self.assertFalse(old.exists())
        self.assertEqual(len(boundary.read_text().splitlines()), 1)
        self.assertEqual(current.read_text(), 'current file left alone\n')
        self.assertEqual(self.store.metrics()[0]['returning_browsers'], 1)


if __name__ == '__main__':
    unittest.main()
