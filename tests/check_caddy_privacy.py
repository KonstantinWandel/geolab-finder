"""Run on the VM with sudo; inspect only the log record from our synthetic request."""
import json
import time
import urllib.request
import uuid
from pathlib import Path

path = '/privacy-log-probe-' + uuid.uuid4().hex
request = urllib.request.Request('https://geodb.geolab.soz.uni-bielefeld.de' + path + '?q=private-query-probe',
                                 headers={'Referer': 'https://example.com/private-referrer', 'User-Agent': 'privacy-test'})
with urllib.request.urlopen(request, timeout=20) as response:
    assert response.status == 200
time.sleep(1)
entries = [json.loads(line) for line in Path('/var/log/caddy/access.log').read_text().splitlines()[-100:]]
entry = next(row for row in entries if row.get('request', {}).get('uri', '').startswith(path))
assert entry['request']['uri'] == path, 'Query string persisted'
assert 'headers' not in entry['request'], 'Request headers persisted'
assert entry['status'] == 200
assert entry['request'].get('remote_ip'), 'Security IP field unexpectedly removed'
print('Caddy probe passed: query and headers absent; path/status/security diagnostics preserved')
