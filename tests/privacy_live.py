"""Before/after ranking and telemetry contract checks against production, with synthetic data."""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ACTION, OUTPUT = sys.argv[1:]
QUERIES = [('soep', 'life satisfaction'), ('soep', 'Geschlechterrollen'),
           ('inkar', 'Arztdichte'), ('inkar', 'regional unemployment')]
HOSTS = {'soep': 'https://soep-faiss.geolab.soz.uni-bielefeld.de', 'inkar': 'https://geodb.geolab.soz.uni-bielefeld.de'}


def post(base, path, body, origin=None):
    headers = {'Content-Type': 'application/json'}
    if origin:
        headers['Origin'] = origin
    request = urllib.request.Request(base + '/api/' + path, json.dumps(body).encode(), headers)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


baseline = json.loads(Path(OUTPUT).read_text()) if ACTION == 'verify' else {}
current = {}
feedback_ids = []
for mode, question in QUERIES:
    base = HOSTS[mode]
    status, response = post(base, 'soep/advice', {'question': question, 'top_k': 5})
    assert status == 200, (mode, status)
    rows = response['recommended_variables']
    current[f'{mode}:{question}'] = [(row.get('item_id'), row.get('score')) for row in rows]
    assert rows, (mode, 'no results')
    if ACTION == 'verify':
        assert json.loads(json.dumps(current[f'{mode}:{question}'])) == baseline[f'{mode}:{question}'], 'Ranking changed'
        rating = {'query_id': response['query_id'], 'item_id': rows[0]['item_id'], 'vote': 'useful',
                  'token': response['feedback_token']}
        assert post(base, 'soep/feedback', rating, base)[0] == 204
        feedback_ids.append(response['query_id'])
        assert post(base, 'soep/feedback', {**rating, 'token': 'forged'}, base)[0] == 422
        assert post(base, 'soep/feedback', {**rating, 'vote': None}, base)[0] == 204
        identity = 'f' * 32  # test only, remove after checking; never a browser's real identity
        event = {'visitor_id': identity, 'consent': True, 'consent_version': '2026-10-04', 'event': 'visit'}
        assert post(base, 'analytics/event', {**event, 'consent': False}, base)[0] == 422
        assert post(base, 'analytics/event', event, 'https://not-geolab.example')[0] == 403
        assert post(base, 'analytics/event', event, base)[0] == 204
        assert post(base, 'analytics/withdraw', {'visitor_id': identity}, base)[0] == 204
    print(json.dumps({'mode': mode, 'query': question, 'results': len(rows), 'status': ACTION + '-passed'}), flush=True)
if ACTION == 'baseline':
    Path(OUTPUT).write_text(json.dumps(current, indent=2))
else:
    Path(OUTPUT + '.feedback_ids').write_text(json.dumps(feedback_ids))
