# Privacy operations: 4 October 2026

Applies to the public SOEP Variable Finder and GeoDB on the university VM. This is an engineering
record, not a legal approval or a statement that metadata-only sites are exempt from GDPR.
The corresponding website notice is `../geolab_regiohub/privacy.qmd`. The user required the
university's copied legal accordion, including YouTube/Matomo and its historical finder section,
to remain unchanged. A prominent current GeoLAB addendum identifies the historical text.

## Purposes and separation

| Store | Contents | Retention | Basis/design |
|---|---|---|---|
| `queries-YYYY-MM.jsonl` | Search text, filters, time, duration, count, top five result IDs/scores, random query ID | 90 days, daily purge | Existing research-quality purpose, not anonymous: free text may identify someone. Public-task basis must be confirmed by the university. No IP/UA/browser ID. |
| SQLite `feedback` | Query ID, result ID, rank in returned list, vote, UTC day, embedding/reranker model names | 90 days, daily purge | Voluntary rating tied to one search, not a persistent browser. Offline evaluation only. No automated live ranking updates. |
| SQLite `visitor_days` | Finder mode, random browser ID, UTC day, visit/search counts, consent version | 90 days, daily purge; current-ID deletion on withdrawal | Explicit analytics consent only. No question, query ID, feedback, IP or UA. |
| Caddy access logs | IP, path without query string, time, status, volume/timing | Existing daily rotation, five old files, maxage six | Security/troubleshooting. No request headers/referrer/user agent in new entries. Older entries expire normally. |

The two finders share `/opt/geolab/logs/privacy.sqlite3` but every key/query is scoped by app mode.
Browser IDs are independently generated per origin. Operators must not correlate raw query and
access-log timestamps to reconstruct browsing histories, or add visitor IDs to search requests.
Monthly statistics count consenting browsers, not actual people or all visitors. Returning means
an ID appeared on at least two different UTC days within the month. Counts cannot be extended
beyond the rolling 90-day window without an explicit policy decision; truly anonymous monthly
totals may later be retained separately, but that is not implemented here.

## Browser storage

- `geolab_privacy_<mode>`: independent booleans, notice version `2026-10-04`, decision expiry 180 days; no ID.
- `geolab_history_<mode>`: opt-in only; last 12 messages, expiry 30 days after saving a search.
- `geolab_visitor_<mode>`: opt-in only; crypto-random 128-bit ID, fixed 90-day expiry, not renewed on visits.
- `geolab_withdrawal_<mode>`: previous ID retained only for deletion retry, maximum seven days.
- Manual language/theme choices remain functional without analytics; no visitor ID from OS theme detection.

New builds remove old, unconsented history instead of silently importing it. Search results remain
in memory after withdrawal; existing exports and filters are unchanged. Preferences are checked
again before saving a completed asynchronous search or sending queued telemetry. With unavailable
storage, optional features fail closed and search remains usable. Storage events sync another tab;
open tabs check expiry each minute. Browser-closed storage can only be cleaned on next use.

The consent panel is an ordinary inline section, not a blocking overlay. Both options start off;
Allow both and Decline both have equal styling, with a third Save selected choices command.
The footer reopens the same choices. No consent wall or account requirement was introduced.

## API and feedback integrity

- `POST /api/analytics/event` requires explicit `consent: true`, current notice version, valid ID and event.
- `POST /api/analytics/withdraw` deletes the current ID's rows in this finder only.
- `POST /api/soep/feedback` verifies a per-search HMAC token and returned result membership.
- Extra fields (including question/visitor ID in the wrong purpose) and disallowed cross-site Origins are rejected.
- There is deliberately no public statistics, raw-query-log or database download endpoint.

`.feedback-signing-key` is a private 32-byte key persisted under the runtime log directory. It
allows signed feedback to survive backend restarts and is **never committed or generally backed
up**. A lost key invalidates earlier tokens without affecting searches. Votes update once per
query/result; token expiry is 90 days. Model names/rank come from the verified server token, not
untrusted client fields. Feedback is not a training dataset until reviewed against a held-out
evaluation and the corpus/model revision used for each search.

## VM deployment and maintenance

Production is native systemd/Caddy, not the historical Docker/Cloudflare setup. Shared source is
`/opt/geolab/app/destatis-rag`, services are `geolab-soep`/`geolab-inkar`, ports 18001/18002. Do not
change the e5/GTE ONNX models, cached embeddings, or reranking configuration as part of privacy work.

Runtime directory mode is 0750; query logs, SQLite and signing key are 0600. General backups exclude
`geolab/logs/**` and `**/geolab/logs/**`. The exclusion does NOT remove pre-existing copies. The
scoped `scripts/remove_legacy_telemetry_backups.sh` previews by default and, with `--apply`, removes
only telemetry filenames from the known live mirror and dated archive directories. Primary useful
query logs remain available for their retention period; no metadata or service backups are deleted.

Configuration snapshots (no credential bytes) live in `deploy/university/`. Before deployment:
back up changed code/configuration, validate the Caddyfile, install the retention units, run an
initial purge, and enable `geolab-privacy-retention.timer`. Keep older production frontend bundles
when installing the new shell, because already open clients may still request their filenames.

```bash
ssh vm 'sudo systemctl status geolab-privacy-retention.timer --no-pager'
ssh vm 'sudo journalctl -u geolab-privacy-retention.service -n 20 --no-pager'
ssh vm 'sudo -u geolab /opt/geolab/.venv/bin/python /opt/geolab/app/destatis-rag/scripts/privacy_admin.py metrics'
ssh vm 'sudo -u geolab /opt/geolab/.venv/bin/python /opt/geolab/app/destatis-rag/scripts/privacy_admin.py purge'
```

The metrics command prints monthly aggregates only, never IDs or questions. Records are not
backed up, deliberately: losing optional usage statistics is preferable to defeating withdrawal
or expiry. A deletion request about raw queries requires a scoped operator action using the
query ID; do not request additional identification unless necessary.

## Verification

```bash
/home/researcher/miniconda3/envs/geolab-rag/bin/python -m unittest discover -s tests -v
/home/researcher/miniconda3/envs/nodejs/bin/node --test frontend/src/privacy.test.js
bash frontend/build.sh soep
bash frontend/build.sh inkar
```

`tests/privacy_browser.py` uses fixtures on staged localhost builds, never real visitor telemetry.
It verifies desktop 1440x960 and mobile 390x844 for both modes: default-off, decline-and-search,
feedback result identity, one-row CSV export, opt-in persistence, reload, withdrawal, and no
horizontal overflow or browser exceptions. Screenshots are temporary, not committed. New privacy
components/helpers are linted separately; the existing project-wide lint command also checks
generated bundles and already has unrelated unused-variable/environment errors.

## Decisions still requiring institutional review

1. Confirm the university controller, public-task statutory basis for raw query/feedback logging,
   authorised staff and chosen 90-day necessity. Consent for analytics does not authorise other uses.
2. The interactive website demonstration map still loads CARTO tiles automatically. Disclose it,
   but do not call it resolved: terms now require a valid CARTO API key and prohibit bulk downloads,
   server-side caching and proxying. No institutional contract was accepted on the user's behalf.
   Decide provider/transfer arrangements or an appropriately licensed local replacement.
3. Review existing Quarto theme/tab preference storage separately; do not assume every default
   framework write automatically qualifies for the essential-storage exception.
4. Confirm incident-log exceptions, backup access policy and Article 13 disclosures with the DPO.

Primary references checked 4 October 2026:
[device storage, §25 TDDDG](https://www.gesetze-im-internet.de/ttdsg/__25.html),
[Caddy log filtering](https://caddyserver.com/docs/caddyfile/directives/log),
[CARTO basemap terms](https://www.carto.com/legal/basemap-terms/) (updated 29 September 2026).
The copied university text was not pruned to hide these remaining issues.

## Deployment evidence

Installed on the university VM on 4 October 2026, with pre-change code/configuration and public
site copies in `/opt/geolab/backups/privacy_20261004-115401/`. The project website's pre-change
render is `/opt/geolab/sites/_archive/geolab-20261004-135412/`. No query logs or signing key were
copied into these rollback folders. The general mirror's existing query/feedback copies were
previewed and removed with the scoped cleanup; primary August-October quality logs were retained.

Verification completed: five backend/API tests, four browser-storage tests, four Playwright
viewport/mode runs (including selected-row CSV), both production frontend builds and the Quarto
render. New privacy modules/components pass scoped ESLint. Public API before/after comparisons
for SOEP `life satisfaction` / `Geschlechterrollen` and GeoDB `Arztdichte` / `regional unemployment`
returned identical result IDs and scores. Analytics refusal, Origin checks, withdrawal and signed
feedback were also checked against both public APIs. Existing project-wide lint problems were
not represented as a passing check.

The four synthetic production-test ratings were removed afterwards; consenting-browser rows
were deleted by the test withdrawal calls. No fabricated training labels or visitor IDs remain
from verification. The non-personal test search queries remain in the ordinary quality log.

The Caddy filter was validated on installed Caddy 2.6.2 and corrected after a synthetic log probe
showed an over-broad initial expression. The final expression is `[?].*$` (no backslash escaping),
preserving paths while dropping query strings; request headers are removed separately. The
retention job succeeded, its timer is enabled, runtime permissions are 0750/0600, and public
finders/website continue to return HTTP 200. Signed feedback carries the pre-existing e5/GTE
model names; neither inference settings nor embedding files were rebuilt.

A final quota-failure test also verifies withdrawal when an earlier consent grant exists but a
new choice cannot be saved. The old grant is invalidated, analytics fails closed, and deletion
can still be sent using an in-memory retry record. Cross-visit retries require available storage.
