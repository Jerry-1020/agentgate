# Preserve tasks when evaluation summaries are unavailable

Date: 2026-10-23
Branch: dev_sdm_20261015

## Problem

The overview and task-list queries called a team-wide readiness check before
returning any data. One missing run summary or stale completed-run summary could
raise `SummaryNotReady` and make both endpoints return HTTP 503, even when most
tasks were valid. Missing published-dataset sample counts could also block the
overview. Hiding affected tasks would make users think their newly created tasks
had disappeared.

## Solution

- Remove the global readiness gate from these read paths.
- Keep tasks in the list and pagination totals when their summaries are missing,
  stale, malformed JSON, missing required display fields, or have invalid scores.
- Preserve task/run IDs, task names (falling back to IDs), creation time, real run
  status, and detail navigation. Return null for unavailable display fields,
  progress, sample counts, and scores; render these as an em dash.
- Add `summary_pending` to task/run summaries. Show a pending-summary indicator,
  including a partial-summary indication for multi-run tasks.
- Keep all scoped tasks in overview `task_count`. Aggregate scores and completed
  samples only from valid summaries; exclude a group's statistics when any
  current member summary is invalid. Report `pending_summary_task_count`.
- Exclude datasets with missing latest-published sample counts from dataset
  aggregates and report `pending_dataset_count`.
- Validate compact projection fields in SQL for both SQLite and MySQL, without
  loading complete manifests, traces, or result reports for overview statistics.
- Log bounded diagnostic records with counts and at most ten task IDs per task
  page warning. Do not log credentials or report payloads.
- Keep database failures visible: missing tables, connection errors, and SQL
  failures are not converted into empty successful responses.
- Do not delete or repair source data during reads. Existing backfill can restore
  eligibility, as verified by the repair regression tests.

HTTP endpoint addresses are unchanged. Response contracts add readiness counts
and flags and allow null for unavailable summary fields. Frontend and backend
should be deployed together. No schema migration is required.

The frontend regression suite also updates its existing error-recovery mock to
use the current per-task detail endpoint and its existing optimizer-route
expectation to match the current detail redirect.

## Verification

| Check | Result |
| --- | --- |
| Focused SQLite and real MySQL 8.2.0 regressions | 54 passed |
| Full backend pytest suite | 2739 passed, 102 skipped, 2 warnings |
| Frontend browser regression suite | 18 passed |
| Frontend unit suite | 121 passed |
| Frontend production build and type checking | Passed; bundle-size warning remains |
| Query projection module line coverage | 97% |
| Changed executable lines in projection module | 22/22 covered (100%) |
| Ruff on projection, query models, and new degradation tests | Passed |
| git diff --check | Passed |

Focused backend command:

```bash
.venv/bin/python -m pytest \
  tests/storage/test_summary_degradation.py \
  tests/storage/test_mysql_evaluation_summaries.py \
  tests/test_evaluation_queries.py tests/test_evaluation_summary.py \
  --cov=agentgate.storage.evaluation_projection --cov-report=term -q
```

Real MySQL verification supplied `AGENTGATE_TEST_MYSQL_URL`,
`AGENTGATE_TEST_MYSQL_USER`, and `AGENTGATE_TEST_MYSQL_PASSWORD` to the existing
allowlisted test fixture. It used only the local isolated
`agentgate_perf_20261021_test` database, not the business database. The full suite
ran without optional service credentials; its skips include MySQL tests that
were separately exercised by the focused run.

Other commands:

```bash
.venv/bin/python -m pytest -q
# From frontend/, with the installed Chrome path configured:
npm run test:summary
npm run test:unit
npm run build
```

Coverage includes mixed valid/invalid tasks, pagination, team isolation,
independent runs, A/B and stability groups, backfill recovery, missing dataset
sample counts, and genuine missing-table errors. Browser tests verify pending
indicators, real execution status, unknown progress/score placeholders, overview
notices, pagination, and navigation to the detail component.

Initial test failures were resolved before the reported final runs: a reused
stub generated duplicate result IDs, a dataset fixture had inconsistent creation
and publication times, and the missing-table test initially omitted the MySQL
repository's wrapped exception type. Existing browser assertions were aligned
with the current API, route, and status-label behavior.

## Deployment and limits

Deploy the matching frontend and backend. No business data was changed and no
existing service was restarted during this work. Production gateway integration
and production-scale latency were not tested. Corruption of the original task
or run records is outside the summary-degradation guarantee. This change does
not replace upgrading every worker that writes summaries or repairing historical
projections when complete statistics are required.
