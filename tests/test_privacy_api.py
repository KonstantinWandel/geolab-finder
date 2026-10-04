"""Exercise the real routes without loading ML models or respondent data."""
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi.testclient import TestClient
from app.services.privacy_store import PrivacyStore, QUALITY_CONSENT_VERSION


class Stub:
    app_mode = 'soep'
    def __init__(self, *args, **kwargs):
        pass
    def load(self):
        pass
    def answer_research_question(self, *args):
        return {'recommended_variables': [{'item_id': 'soep/pgen/pgtest', 'score': 0.9}]}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = {'search': 'SearchService', 'data_fetch_agent': 'DataFetchAgentService',
                 'execution_service': 'ExecutionService', 'harmonizer': 'HarmonizerService',
                 'soep_aggregator': 'SOEPAggregatorService', 'soep_search': 'SOEPSearchService',
                 'soep_rag_advisor': 'SOEPRagAdvisorService'}
        modules = {}
        for module, name in names.items():
            full = 'app.services.' + module
            modules[full] = types.ModuleType(full)
            setattr(modules[full], name, Stub)
        with patch.dict(sys.modules, modules), patch.dict('os.environ', {'GEOLAB_ENABLE_DESTATIS': '0'}):
            cls.main = importlib.import_module('app.main')
        cls.client = TestClient(cls.main.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.main.privacy_store = PrivacyStore(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_analytics_requires_explicit_current_consent_and_rejects_identity_extras(self):
        body = {'visitor_id': 'a' * 32, 'event': 'visit', 'consent': True, 'consent_version': '2026-10-04'}
        self.assertEqual(self.client.post('/api/analytics/event', json=body).status_code, 204)
        for invalid in [{**body, 'consent': False}, {k: v for k, v in body.items() if k != 'consent'},
                        {**body, 'question': 'not allowed'}, {**body, 'consent_version': 'old'}]:
            self.assertEqual(self.client.post('/api/analytics/event', json=invalid).status_code, 422)
        self.assertEqual(self.client.post('/api/analytics/event', json=body,
                         headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/analytics/withdraw', json={'visitor_id': 'a' * 32}).status_code, 204)
        self.assertEqual(self.main.privacy_store.metrics(), [])
        self.assertEqual(self.client.get('/api/analytics/metrics').status_code, 404)

    def test_search_works_without_analytics_and_feedback_validates_returned_item(self):
        response = self.client.post('/api/soep/advice', json={'question': 'education', 'top_k': 2})
        self.assertEqual(response.status_code, 200)
        with self.main.privacy_store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quality_queries').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT searches FROM service_days').fetchone()[0], 1)
        self.assertEqual(self.main.privacy_store.metrics(), [])
        result = response.json()
        body = {'query_id': result['query_id'], 'item_id': 'soep/pgen/pgtest', 'vote': 'useful',
                'token': result['feedback_token']}
        self.assertEqual(self.client.post('/api/soep/feedback', json=body).status_code, 204)
        self.assertEqual(self.client.post('/api/soep/feedback', json={**body, 'item_id': 'invented'}).status_code, 422)
        self.assertEqual(self.client.post('/api/soep/feedback', json={**body, 'visitor_id': 'a' * 32}).status_code, 422)
        self.assertEqual(self.client.post('/api/soep/feedback', json={**body, 'vote': None}).status_code, 204)
        with self.main.privacy_store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0], 0)

    def test_raw_queries_require_separate_consent_and_withdrawal_blocks_delayed_search(self):
        body = {'question': 'education', 'quality_id': 'c' * 32}
        for extras in [{}, {'quality_consent': True}, {'quality_consent_version': QUALITY_CONSENT_VERSION}]:
            self.assertEqual(self.client.post('/api/soep/advice', json={**body, **extras}).status_code, 200)
        with self.main.privacy_store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quality_queries').fetchone()[0], 0)
        grant = {**body, 'quality_consent': True, 'quality_consent_version': QUALITY_CONSENT_VERSION}
        self.assertEqual(self.client.post('/api/soep/advice', json=grant).status_code, 200)
        with self.main.privacy_store.connect() as db:
            self.assertEqual(db.execute('SELECT question FROM quality_queries').fetchall(), [('education',)])
        self.assertEqual(self.client.post('/api/quality/withdraw', json={'visitor_id': 'c' * 32},
                         headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/quality/withdraw', json={'visitor_id': 'c' * 32}).status_code, 204)
        self.client.post('/api/soep/advice', json=grant)
        with self.main.privacy_store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM quality_queries').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
