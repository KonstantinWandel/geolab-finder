# Privacy operations: 4 October 2026

Applies to the public SOEP Variable Finder and GeoDB on the university VM. This is an engineering
record, not a legal approval or a statement that metadata-only sites are exempt from GDPR.
The corresponding website notice is `../geolab_regiohub/privacy.qmd`. The user required the
university's copied legal accordion, including YouTube/Matomo and its historical finder section,
to remain unchanged. A prominent current GeoLAB addendum identifies the historical text.

## Purposes and separation

| Store | Contents | Retention | Basis/design |
|---|---|---|---|
| SQLite `quality_queries` | Opt-in search text, filters, day, duration, top-five result IDs, query ID, separate quality ID and notice version | 90 days, daily purge; current-ID deletion on withdrawal | Separate consent under Article 6(1)(a), not an unconfirmed public-task basis. No IP/UA/analytics ID. |
| SQLite `service_days` | Finder, UTC day, count of completed searches | Long-term anonymous aggregate | No questions, filters, query IDs, results, exact times or visitor IDs. Includes user-approved migration of the old logs into daily counts. |
| SQLite `feedback` | Query ID, result ID, rank in returned list, vote, UTC day, embedding/reranker model names | 90 days, daily purge; selected rating can be clicked again to delete | Affirmative optional rating with a purpose/retention notice, Article 6(1)(a). Offline evaluation only. No automated live ranking updates. |
| SQLite `visitor_days` | Finder mode, random browser ID, UTC day, visit/search counts, consent version | 90 days, daily purge; current-ID deletion on withdrawal | Explicit analytics consent only. No question, query ID, feedback, IP or UA. |
| Caddy access logs | IP, path without query string, time, status, volume/timing | Existing daily rotation, five old files, maxage six | Security/troubleshooting. No request headers/referrer/user agent in new entries. Older entries expire normally. |

The two finders share `/opt/geolab/logs/privacy.sqlite3` but every key/query is scoped by app mode.
Browser IDs are independently generated per origin. Operators must not correlate query records,
access logs and analytics IDs to reconstruct browsing histories. The new quality-purpose ID is
separate from usage analytics and is used for deletion, not visitor counting.
Monthly statistics count consenting browsers, not actual people or all visitors. Returning means
an ID appeared on at least two different UTC days within the month. Counts cannot be extended
beyond the rolling 90-day window without an explicit policy decision; truly anonymous monthly
totals may later be retained separately, but that is not implemented here.

## Browser storage

- `geolab_privacy_<mode>`: three independent booleans, notice version `2026-10-04.2`, decision expiry 180 days; no ID. Existing `2026-10-04` history/analytics grants remain valid but never grant the new quality purpose. The analytics API's own purpose version remains `2026-10-04`.
- `geolab_history_<mode>`: opt-in only; last 12 messages, expiry 30 days after saving a search.
- `geolab_visitor_<mode>`: opt-in only; crypto-random 128-bit ID, fixed 90-day expiry, not renewed on visits.
- `geolab_withdrawal_<mode>`: previous ID retained only for deletion retry, maximum seven days.
- `geolab_quality_<mode>`: random 128-bit ID only after the quality opt-in; independent from analytics. Kept while consent remains active, so renewing other choices cannot rotate away deletion access. Withdraw/expired consent requests deletion before removing this ID.
- `geolab_qualitywithdrawal_<mode>`: equivalent seven-day retry for quality deletion.
- Manual language/theme choices remain functional without analytics; no visitor ID from OS theme detection.

New builds remove old, unconsented history instead of silently importing it. Search results remain
in memory after withdrawal; existing exports and filters are unchanged. Preferences are checked
again before saving a completed asynchronous search or sending queued telemetry. With unavailable
storage, optional features fail closed and search remains usable. Storage events sync another tab;
open tabs check expiry each minute. Browser-closed storage can only be cleaned on next use.

The consent panel is a nonblocking bottom bar with measured reserved page space. All three
options start off; Allow all and Decline all have equal styling. Choose individually reveals
independent checkboxes and Save selected choices. The footer reopens the same choices. No
consent wall or account requirement was introduced.

## API and feedback integrity

- `POST /api/analytics/event` requires explicit `consent: true`, current notice version, valid ID and event.
- `POST /api/analytics/withdraw` deletes the current ID's rows in this finder only. Minimal ID/day withdrawal records block delayed/replayed events for 90 days; these records are not counted in usage statistics.
- Advice requests save raw queries only with `quality_consent: true`, the separate current quality notice version, and a valid quality ID. Legacy clients omit these and cannot log raw questions.
- `POST /api/quality/withdraw` deletes this quality ID's queries/linked ratings. A minimal ID/day revocation record is retained for 90 days solely to prevent in-flight searches from recreating withdrawn records.
- `POST /api/soep/feedback` verifies a per-search HMAC token and returned result membership.
- Extra fields (including question/visitor ID in the wrong purpose) and disallowed cross-site Origins are rejected.
- There is deliberately no public statistics, raw-query-log or database download endpoint.
- Performance debug output never includes a query snippet, including when `SOEP_RAG_TIMING` is enabled.

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
only telemetry filenames from the known live mirror and dated archive directories. No metadata
or service backups are deleted. On the user's explicit instruction, pre-consent raw query JSONL
files are replaced with daily counts by `scripts/redact_legacy_queries.py --apply`. Run preview
first and stop both backends while applying. A SQLite filename-only ledger makes this idempotent
after interruption; raw text is never put in a rollback backup. Legacy feedback JSONL is removed
too. New quality records live in SQLite only.

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
or expiry. Raw-query withdrawal is handled automatically using the separate quality ID. Individual
queries can also be located by query ID; do not request additional identification unless necessary.
`privacy_admin.py service-metrics` prints anonymous daily search totals independently of optional
consenting-browser metrics.

## Verification

```bash
/home/researcher/miniconda3/envs/geolab-rag/bin/python -m unittest discover -s tests -v
/home/researcher/miniconda3/envs/nodejs/bin/node --test frontend/src/privacy.test.js frontend/src/descriptions.test.js
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

1. Confirm the university controller, authorised staff, consent notice and chosen 90-day necessity.
   Raw-query retention no longer invokes an unconfirmed public-task basis: it is an independent
   optional consent purpose. Consent for analytics never authorises quality logging.
2. The website demonstration map now uses local public-domain Natural Earth data. Its original
   SOEP grid/district polygon calls are unchanged; CARTO calls are removed and the self-contained
   widget has a CSP blocking network subresources. No institutional provider contract was accepted.
   Recheck release permissions separately for the predecessor's GitHub Pages Data Explorer before
   rehosting its derived SOEP regional aggregates; see `../geolab_regiohub/DATAEXPLORER_HANDOFF.md`.
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

## Corrective deployment: bottom bar, opt-in quality, local map

The subsequent deployment on 4 October 2026 supersedes the earlier raw-log and CARTO review
points. Rollback source/public-site copies are in
`/opt/geolab/backups/quality_privacy_20261004-125443/`; no raw logs, SQLite or keys were copied.
`deploy/university/install_quality_privacy.sh` stops both backends while migrating, restarts them
and their retention timer, and keeps old public bundles available. Its `GEOLAB_USAGE_LOG=0`
systemd drop-ins prevent an older-code rollback from re-enabling unconsented JSONL logging.
New consented SQLite quality records are independent of this legacy switch.

User-approved redaction preserved 1,118 August, 1,434 September and 137 October searches as
51 mode/day count rows, then removed all three raw-query files and the legacy feedback JSONL.
The private schema was checked: zero quality-query rows before any explicit opt-in, no raw JSONL
files, and no leftover synthetic ratings. A seven-day journal check found no historic timing
query snippets; the source no longer prints them even if performance logging is enabled.

Verified nine backend/API/migration/display tests, seven Node privacy/description tests, four staged
Playwright mode/viewport runs, selected CSV exports, opt-in query payloads, feedback removal and
quality/analytics withdrawal. Four public before/after query comparisons retained identical
result IDs and scores. Descriptions are frontend-formatted official v41 metadata or source-specific
Regionalatlas sections; original text/export content and retrieval documents are unchanged.
The API retains line breaks separately in `description_original` for this display; existing
normalized search/reranker text remains unchanged. Six public desktop/mobile checks covered
official income and education notes and life-satisfaction question wording. The final description
deployment uses build `202610041510`, with its prior-code/site copy at
`/opt/geolab/backups/quality_privacy_20261004-133100/`.

The website map preserves all original polygon/legend calls and map bounds exactly. Two
Playwright viewport runs verified visible paths, local Berlin/Potsdam labels, no tile layers,
no external requests after pan/zoom, and no browser exceptions. Natural Earth sources are
public domain with pinned revision/checksums; no CARTO tiles were obtained or contract accepted.
The copied university privacy accordion remains unchanged. This resolves these technical
dependencies without representing a complete institutional legal approval.

Separately, `DESCRIPTION_REVIEW.md` records an offline three-representation embedding comparison
on 23,855 analysis variables and 59 existing gate queries, including limitations of that gate.
Both alternatives regressed; production embeddings and reranker inputs remain unchanged.
