# Run Implementation Plan

Last updated: 2026-10-31

## Release delivery — 2026-10-31

The user subsequently authorized committing, pushing and creating a PR for the two
completed features against `release_20261102`. Use a separate delivery branch based
on `50888af`, with one rerun commit and one concurrency commit. Preserve team-level
dispatch limits, Run timing/recovery, base initialization and the release's selector
and sample validation behavior. Earlier no-commit/no-push notes describe the original
implementation scope; this delivery authorization supersedes them without authorizing
merge. Fresh verification is recorded in project-progress.md.

## Unified Case concurrency — 2026-10-31

Status: implemented and verified; see project-progress.md for full regression counts
and live SDK execution-span evidence. No commit, push or merge has been performed.

Scope approved by the user as an autonomous implementation Goal, without commit,
push or merge. All new tasks use an integer Case-concurrency limit of 1–30, default
1, in both login modes. A/B applies the same limit independently to each Run. Keep
Turns ordered within each Case, existing session boundaries, credential routing,
timeout/retry behavior and immutable source reports. Rerun copies retain the limit.
This supersedes the external/mock A/B and local-bank concurrency-1 restrictions below.

Keep historical RunManifest and CaseExecutionRequest serialization unchanged. Validate
the 1–30 range at new launch inputs and RunManagement before any persistence, so older
immutable reports remain readable. Ownership: reuse Engine and existing input models;
forward the same parameter through all launch paths. Adapt bounded threaded Case
execution inside the three existing external adapters; retain the in-bank adapters.
The Demo adapter owns separate Trace captures for each Case and returns inline Trace
evidence through its existing composition boundary. No new scheduler, generic executor,
base-class hierarchy or module is introduced. Existing tests receive focused additions; tests/test_external_concurrency.py exercises
public provider/client injection boundaries, bounded overlap up to 30, cancellation
and cleanup without replacing private execution methods.

Source assessment: goal/p1-demo supplies synchronous behavior and persistence but no
compatible bounded external execution. integration/p1-new uses different Target/Run
contracts and is not copied. The current refactor supplies in-bank thread lifecycles,
pending-handle rotation, manifest hashing and per-Case session identifiers: reuse these
contracts and adapt the lifecycle in the owning external adapters. New work is limited
to parameter propagation, external scheduling and explicit per-Case Trace ownership.
The prior uncommitted rerun implementation is copied as a dependency into an isolated
worktree; the source checkout and its running services remain unchanged. Remote refresh
timed out, so the worktree starts at local refactor-1 c1f2139.

Verification: focused range/default/API/persistence tests, actual overlap bounded by N,
ordered multi-turn sessions, independent Trace evidence, cancellation and cleanup;
frontend tests cover both login modes, all target types, A/B and editable rerun copies.
Then run the full backend/frontend regression and local real-model concurrency checks.

## Editable task copies and controlled A/B inputs — 2026-10-30

Status: implemented and verified under the user-authorized rerun Goal. Task-list
and single-task-detail rerun entries open the ordinary creation form with exact
saved selections. Submission creates a new task, including a fresh A/B pair, and
preserves the source runs, reports and Trace evidence. Keep source-manifest reads
and UI form hydration in their existing frontend owners; use the current login
mode for all directory and credential routing. No new rerun workflow is added to
the Engine or dispatcher, and the existing in-place API is not used by these UI
entries.

The existing Demo run-comparisons endpoint now accepts case_ids and timeout_seconds
and forwards them through ServerDependencies to create_ab_runs/RunManagement.
Reuse manifest Case validation and the shared-control signature for both sides.
Invalid selections create no task. Existing in-bank concurrency, external A/B
concurrency 1 and retry 0 restrictions remain. API tests execute original and new
pairs, verify separate identities and copied settings, and compare source reports
and persisted runs after execution. See project-progress.md for full regression
counts and local service verification. No commit, push or merge is authorized.

## Frontend-owned concurrency and adapter ownership — 2026-10-19

This request supersedes the backend-owned configuration plan below. Reuse the page's
existing concurrency value and persist it in the existing Run manifest. Ordinary,
stability, and both in-bank A/B variants consume that value. External/mock A/B remains
fixed at 1. Remove the obsolete concurrency environment setting, not the independently
configured timeouts. Preserve data-source/token routing in both login modes.

After approving the application checkpoint, the user authorized implementing the
remaining files directly. The application no longer overrides caller concurrency;
HTTP and frontend A/B wiring reuse the same field, with default 1 and the existing
1–30 range. Ordinary requests retain their original required field. Page selection
and token routing remain isolated between in-bank and external modes. Existing saved
manifests remain fixed, including reservations and reruns. Both A/B Runs can execute
up to the selected count independently; this is not a shared global concurrency cap.

Concrete bounded thread execution now lives directly in the existing ChatABC and
Yunxia adapters. Remove the new shared `inbank/execution.py`, without introducing a
replacement module or wrapper class. Reuse the customer's `ThreadPoolExecutor`
session-group strategy while retaining the platform's existing handles, persisted
results, and cancellation protocol. Keep ordered Turns/shared sessions, failure
isolation, partial evidence, ERROR scoring, cleanup, deadlines, and output contracts.
Do not copy customer Excel/database/export batch orchestration, change existing
Engine/protocol/evaluator ownership, or add the declined malformed-error-marker guard.
The user authorized committing and integrating this work into
`open-fin-sub/agentgate:integration/baibo1017`, with conflict review and regression
verification before publishing. Preserve the destination branch's existing features.

Integration checkpoint: merge destination `a7cbbaf` with PR #57 head `98ff389`
and execution-parity commit `dbe00ca`, retaining both histories and the destination's
platform-only in-bank form. Merged-tree verification passed: 2653 backend tests
(85 skipped), 112 frontend unit tests, 80 platform browser tests, and 31 sample-editor
browser tests. Type checking and production build passed; no live in-bank/BJS
acceptance is claimed.

Verify three agent modes, ordinary/stability/A/B page values and HTTP manifests,
default/invalid concurrency, actual bounded overlap, ordered sessions, cancellation
before Pod cleanup, saved-manifest immutability, and unchanged external behavior.
The obsolete environment example is removed; timeouts keep their independent settings.

## Yunxia final-message output alignment — 2026-10-19

Reuse the customer's last-message selection and keep final responses separate from
customer execution spans. A JSON object from the last `event: message` becomes the
complete turn output, with the last turn supplying Case `final_output`. Keep every
customer field; do not create a fixed four-field projection or legacy output aliases.
Non-object message data uses the existing `{output: value}` object container without
changing the shared Domain contract. Empty objects and valid false/zero/null values
must not be treated as absent data.

Remove the extra `inbank.response.message_data` Span attribute, raw-response observation
fallback, and its special redaction branch. Reuse normal output-field observation and
structured-output redaction. Trace Server polling, tool/Skill evidence adaptation,
Case isolation, and ChatABC output contracts remain unchanged. Verify per-turn/final
output persistence, full-object and field-path scoring, absent-field semantics,
structured redaction, output-only fallback, and local frontend contracts. Existing
expectations that depend on manufactured output fields must be adjusted to customer
field names; historical saved Traces are not rewritten.

The unchanged Domain currently cannot JSON-serialize an object-valued `Equals.expected`
when persisting/publishing the DatasetVersion. Keep this pre-existing limitation separate
from complete customer-response persistence: direct Rule comparisons cover objects,
while the Worker regression uses scalar nested-field expectations. Repairing the
expectation serializer requires a separate scoped change.

## In-bank execution parity — 2026-10-18

The user authorized completing the agreed changes together on a new branch from
PR #57. Attachments, retries of complete in-bank Cases, commits, pushes, and merges
are outside this change.

- Reuse the customer's request builders, SSE parsing, session initialization,
  lifecycle retries, and default request timeouts. Adapt the customer's grouped
  `ThreadPoolExecutor` behavior directly in the existing ChatABC/Yunxia Case adapters;
  no separate execution module or second scheduler is introduced.
- `CaseExecutionRequest.max_parallel_cases` carries the existing manifest limit.
  `CaseExecutionPending` means a local wait interval elapsed, not a failed request.
  Engine rotates pending handles and continues checking persisted cancellation.
- `CaseExecutionResult.error` can accompany a Trace containing actual successful
  and failed turns. A failed chat records its error and does not prevent later turns
  or independent Cases from running. Session initialization failure records all
  turns of that Case as failed. Shared Pod preparation failure remains task-fatal.
- Target execution failures produce scoreless ERROR Results with category
  `target_execution`, not incorrect-answer verdicts or fabricated success. Completed
  Rule checks are preserved; an incomplete Case is not sent to a case-level Judge.
  A COMPLETED Run means all Cases were processed, not that every Case passed.
- No SQL schema, RunManifest hash, agent directory, token routing, or frontend
  business contract is changed. Existing external adapter behavior is preserved.
- Yunxia reuses the customer payload builder: `custID` directly concatenates the
  explicit customer ID (or session ID) and one Run-scoped UUID hex, with no added
  prefix or separator. Same-Run stability and cross-Run isolation remain unchanged.

The overall in-bank deadline starts after Pod readiness, is shared by the Run, and
is checked before each new turn. Zero means unlimited, as in the customer scripts.
In-flight requests retain their independent timeout; their budgets are not reduced
to remaining overall time. Pod readiness has its own wait budget. Lifecycle request
timeouts are configurable in `.env.example` with the customer's defaults: create
60s, init 30s, delete 60s, health request 10s. Existing lifecycle retry counts and
delays remain unchanged.

Source assessment: `goal/p1-demo` provides the persistence and terminal-state behavior
but only has a fail-fast synchronous Run implementation. `integration/p1-new` has
no compatible in-bank executor; its old domain/HTTP contracts are not copied. The
current refactor supplies the manifest limits, adapter protocol, Trace storage,
evaluator finalization, ERROR metric handling, and cancellation boundaries. Only
the exercised runtime glue and failure classification are new.

Focused verification covers three agent modes, single/multiple turns, independent
Cases, explicit Yunxia shared-session ordering, partial failures, init failure,
deadline checks, cancellation/cleanup, complete customer response fields, and whole-output
comparisons against the customer object. Full backend and frontend regression results are recorded in
`docs/project-progress.md`; local mocks do not replace real in-bank acceptance.

Status: core Engine, Target protocol, Demo adapter wiring, atomic Run claiming,
incremental Result persistence, infrastructure retry, and cooperative cancellation are
implemented. Optional process and Artifact mechanics remain pending. Asynchronous
delivery is tracked in
[`../job-dispatcher/implementation-plan.md`](../job-dispatcher/implementation-plan.md).

## 1. Purpose

The Run capability executes one immutable evaluation request. It connects a published
DatasetVersion to a Target adapter, captures the resulting Trace and Artifacts, invokes
the selected Evaluators, persists Results, and records the final EvaluationRun state.

```text
Run request
    |
    v
RunManifest -> RunEngine -> TargetAdapterProtocol -> Target adapter -> Agent
                    |                                |
                    |                                v
                    +-> Trace -> Evaluators -> EvaluationResults
                    |
                    +-> Artifacts
                    |
                    +-> EvaluationRun state
```

`application/run_management.py` owns the complete user-facing workflow. `run/` owns
only deterministic execution mechanics.

## 2. Final Structure

```text
run/
├── __init__.py
├── target_protocol.py
├── engine.py
├── retry.py
├── process_manager.py
└── artifacts.py
```

Modules are created only when exercised by a real caller. Empty placeholders are not
accepted.

## 3. Terms

- **EvaluationRun**: lifecycle record for one complete evaluation execution.
- **RunManifest**: immutable record of the exact Dataset, Target, Evaluators, metrics,
  gate policy, and effective configuration used by an EvaluationRun.
- **Case execution**: one execution of one Case against the Target.
- **Retry**: a new execution of the same Case after an infrastructure failure.
- **Target**: the Agent or Skill being evaluated.
- **Target adapter**: integration-specific implementation that translates the common
  Target Adapter Protocol into a local Python call, process invocation, or remote HTTP
  API.
- **Trace**: structured behavior history used by Evaluators.
- **Artifact**: file-like output such as stdout, a patch, test report, screenshot, or
  generated file.
- **Job dispatcher**: local/Celery/customer infrastructure that starts a whole Run. It
  is outside `run/`.

There are two distinct asynchronous lifecycles:

```text
Demo Celery or customer scheduler   schedules a complete EvaluationRun
TargetAdapterProtocol               controls one Case execution
```

The asynchronous demo will use a real job dispatcher under
`integrations/job_dispatchers/`. A customer
may replace that dispatcher without changing Engine or the Target Adapter Protocol.

## 4. Ownership Boundaries

`run/` owns:

- consuming an immutable RunManifest constructed from already resolved inputs;
- executing selected Cases;
- invoking a Target through one protocol;
- coordinating Trace collection and evaluation;
- infrastructure-only retries;
- local process mechanics when a local adapter requires them;
- execution Artifact discovery and registration;
- legal Run state changes through domain functions.

`run/` does not own:

- Dataset editing or publication;
- external Target discovery and credentials;
- Agent-specific HTTP, CLI, or SDK behavior;
- evaluator algorithms or evaluator selection policy;
- SQL, HTTP routes, CLI commands, Web pages, queues, or enterprise scheduling;
- observability transport or vendor-specific Trace normalization;
- metric aggregation, reports, or release-gate algorithms.

## 5. Module Contracts

### `target_protocol.py`

Defines the smallest common execution protocol used by `RunEngine`. It contains
execution request/result types only when they are runtime-only and do not belong in the
domain model.

Required behavior:

- `start(request) -> handle` starts one Case execution and returns an opaque string;
- `get_status(handle)` inspects its current status;
- `wait(handle, timeout_seconds)` waits for and returns its normalized result;
- `cancel(handle)` requests cancellation;
- return output, Trace correlation information, and Artifact references without
  exposing vendor response objects to Engine.

The protocol must support both synchronous adapters and adapters backed by remote
asynchronous Agent APIs. Concrete adapters live under `integrations/targets/`.

### `engine.py`

Executes one RunManifest:

1. create and persist a running EvaluationRun;
2. select the Cases pinned by the manifest;
3. execute each Case through `TargetAdapterProtocol`;
4. obtain and normalize the correlated Trace through integration boundaries;
5. reject a Trace that is not eligible for evaluation;
6. invoke the evaluator executor;
7. persist Trace, Results, and Artifact references;
8. observe externally persisted cancellation at safe execution boundaries;
9. cancel locally owned active Target handles when cancellation is observed;
10. transition the EvaluationRun to completed, failed, or cancelled.

Engine does not construct vendor requests, poll observability backends directly,
calculate reports, or act as a scheduler.

### `retry.py`

Applies an explicit retry policy only to Target failures classified as `rate_limited`,
`timeout`, or `unavailable`. The Engine applies one shared per-Case retry budget across
Target start and wait failures. Delays follow a bounded 1, 2, 4, 8, 16, then 30 second
schedule.

It never retries wrong answers, policy violations, evaluator exceptions, validation or
persistence failures, or release-gate failures. Every retry uses a new execution and
Trace identity. The current POC persists only the successful attempt's Trace; persistent
attempt history and retry events in Traces remain future work.

### `process_manager.py`

Supports local-process Target adapters. It starts and monitors isolated Agent
processes, enforces the configured concurrency limit, maps executions to PIDs and
Workspaces, captures resource usage and exits, and terminates process trees on timeout
or cancellation.

Commands and arguments remain owned by the concrete Target adapter. This module is not
a queue, scheduler, container platform, or persistent worker pool. Create it only with
a real local-process adapter.

### `artifacts.py`

Discovers and registers execution outputs, calculates metadata and hashes, and hands
content to the storage Artifact interface. Domain and database records retain Artifact
references rather than large file bodies.

Create this module only when a Target produces real files or reports that must be
preserved.

## 6. Error And State Rules

- Domain code owns legal `EvaluationRun` state transitions.
- Engine must persist terminal failure state before propagating an execution exception.
- User cancellation is not reported as infrastructure failure.
- An externally persisted cancellation wins a concurrent completion or failure and is
  returned without rewriting its terminal timestamps.
- Adapter-originated cancellation remains a typed Target failure that Engine persists
  before propagating.
- Cooperative checks do not forcibly interrupt an arbitrary blocking adapter call.
- Adapter failures cross the protocol as typed, sanitized failures; vendor exceptions
  do not leak into domain objects or API responses.
- Evaluator execution errors become EvaluationResults according to the evaluator
  contract; they do not automatically crash the whole Run.
- Partial persistence must be explicit. A completed Run cannot reference missing
  required Results.
- Credentials, authorization headers, and private Target configuration must never enter
  a RunManifest, Trace, Result, log, or Artifact payload.

## 7. Source Assessment

### `goal/p1-demo`

Preserve:

- published DatasetVersion enforcement;
- creation and persistence of a running EvaluationRun;
- Case-by-Case Target execution;
- Trace and Result persistence;
- terminal completion/failure transitions;
- report behavior only until its caller is moved to the Result/application boundary.

Refactor or reject:

- split the monolithic `run/core.py`;
- remove `LocalScheduler` and `ExternalSchedulerAdapter` from Run;
- reject `PythonFunctionTarget`; the demo receives a specific adapter with a clean
  Agent-native invocation contract;
- replace direct `evaluate_case()` composition with the approved evaluator executor;
- remove hardcoded demo TargetSnapshot construction from Engine;
- remove report construction from Engine.

### `integration/p1-new`

Preserve as behavior references:

- selected-Case execution validation;
- invocation IDs and idempotency keys;
- W3C `traceparent` propagation;
- pending Trace correlation;
- Trace completeness checks;
- timeout diagnostics and exact evaluator/Trace version references on Results.

Do not copy directly:

- obsolete `RunSnapshot`, `Run`, `GateSpec`, repository, and adapter contracts;
- polling and `time.sleep()` embedded directly in Engine;
- vendor/integration errors imported into core execution code;
- old module layout and empty integration scaffolds.

### Current Refactor

Reuse directly:

- `domain.EvaluationRun`, `RunManifest`, `RunStatus`, and `transition_run`;
- current Dataset, Target, Evaluator, Trace, Result, Metric, and Gate contracts;
- `storage.AgentGateRepository` abstractions;
- the approved evaluator executor and observability integration boundaries as they are
  implemented.

### From Scratch

- the minimal Target Adapter Protocol compatible with current domain contracts;
- the decomposed Engine orchestration;
- typed runtime failures and focused contract tests;
- optional retry, process, and Artifact modules only after a real caller is approved.

Reuse means preserving validated behavior after reviewing it against current contracts.
It does not mean copying old code.

## 8. File Migration Map

| Current file | Action | Destination |
| --- | --- | --- |
| `run/core.py` | Split and remove | `run/engine.py`, `run/target_protocol.py`, `integrations/targets/demo_loan.py` |
| empty `run/engine.py` | Implement | `run/engine.py` |
| empty `run/snapshot.py` | Remove | `domain.RunManifest` already owns the complete contract |
| empty `run/lifecycle.py` | Remove | Domain state transitions already own this behavior |
| empty `run/models.py` | Remove | Domain and runtime protocol types own the required models |
| empty `run/scheduler.py` | Remove | `integrations/job_dispatchers/` and application own dispatch |
| empty `run/targets/` | Remove | Concrete adapters belong in `integrations/targets/` |
| empty `run/external/` | Remove | Vendor integrations belong in `integrations/` |
| none | Added with an Engine caller | `run/retry.py` |
| none | Add when exercised | `run/process_manager.py`, `run/artifacts.py` |

No compatibility aliases from old Run modules are retained.

## 9. Implementation Sequence

Each file requires a source assessment and explicit approval before implementation.

1. Confirm this Run plan and current end-to-end baseline.
2. [complete] Review and implement `run/target_protocol.py`.
3. [complete] Reject redundant `run/manifest.py` and remove empty `run/snapshot.py`.
4. [complete] Review and implement `run/engine.py` with one synchronous execution
   path.
5. [complete] Review and implement the demo adapter in `integrations/targets/demo_loan.py` after
   Trace capture and the clean Loan Agent invocation contract are implemented.
6. [complete] Migrate `application/run_management.py` and the Server caller to the
   new Engine boundary.
7. [complete] Add `retry.py` after typed infrastructure failures have a real Engine
   caller.
8. Add `process_manager.py` only with a real local-process Target adapter.
9. Add `artifacts.py` only with a real Artifact-producing Target.
10. Remove `run/core.py`, empty legacy files, old target/external folders, and stale
    imports.
11. [complete] Run focused tests, the complete backend suite, and the real demo Run.
12. Implement whole-Run asynchronous delivery through the Job Dispatcher plan.
13. [complete] Observe persisted cancellation at safe boundaries, cancel active handles,
    and preserve cancellation across terminal-state races.

## 10. Test Plan

### Protocol

- synchronous Target completion returns normalized execution output;
- asynchronous status/wait/cancel semantics are deterministic;
- timeout, cancellation, and adapter failure remain distinguishable;
- vendor response and credential data cannot cross the protocol.

### Manifest

- only published DatasetVersions are accepted;
- exact Target and Evaluator versions/hashes are retained;
- selected Case IDs are unique and exist in the pinned DatasetVersion;
- content hash is stable for equal effective inputs;
- construction has no persistence or integration side effects.

### Engine

- a complete Dataset executes every selected Case once;
- multi-turn Case input remains ordered;
- Trace correlation and eligibility are enforced before evaluation;
- Results retain exact Run, Case, Evaluator, and Trace references;
- completion, failure, and cancellation persist legal terminal states;
- persisted cancellation stops new Cases and retries, prevents subsequent Result
  persistence, and cancels active Target handles at the next safe boundary;
- cancellation remains authoritative when it races with Engine completion or failure;
- evaluator errors do not become infrastructure retries;
- creating a new Run from the same manifest uses a new execution identity, while
  duplicate delivery of one existing `run_id` does not execute it twice.

### Optional Mechanics

- retry accepts only typed retryable Target failures, respects its per-Case budget, uses
  bounded delays, and creates fresh execution and Trace identities;
- evaluator failures and measured fail/review outcomes never trigger Target retries;
- local process timeout terminates the complete process tree;
- concurrency never exceeds the configured limit;
- Artifact hashes and metadata are deterministic and large content stays outside the
  relational record.

## 11. Dependency Rules

```text
domain <- run <- application
          |
          +-> evaluator protocol/executor
          +-> storage repository interface

run/target_protocol.py <- integrations/targets/
application/run_management.py <- integrations/job_dispatchers/
trace/ <- integrations/observability/
```

`run/` must not import FastAPI, Celery, SQL implementations, Web code, or concrete
vendor adapters. Concrete integrations may depend on Run protocols; Run must not depend
on them.

## 12. Completion Gate

Run refactoring is complete when:

- `run/core.py` and all empty legacy Run scaffolds are gone;
- Engine depends on one approved Target Adapter Protocol;
- `domain.RunManifest` owns manifest invariants and hashing, while the application layer
  constructs it from exact resolved assets;
- demo execution preserves P1 behavior through the new boundaries;
- Traces and Results retain exact reproducibility references;
- application code, not Engine, owns the complete user workflow and report retrieval;
- optional modules exist only where exercised;
- focused tests, the complete backend suite, and a real demo Run pass.

## 13. Implementation Decisions

### `run/target_protocol.py`

Status: implemented; 218 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve synchronous execution behavior behind the new lifecycle protocol. |
| `goal/p1-demo` | Reuse none of `Target`, `LocalScheduler`, or `ExternalSchedulerAdapter`; they are forwarding abstractions with mixed ownership. |
| `integration/p1-new` | Adapt request/result correlation, W3C Trace context, adapter identity, and typed failure categories. |
| `integration/p1-new` | Reject obsolete Domain execution models and the credential resolver; credentials belong to concrete integrations. |
| Current refactor | Reuse `Case`, `TargetSnapshot`, `Trace`, and shared validation helpers. |
| From scratch | Implement `CaseExecutionStatus`, immutable request/result records, `TargetExecutionError`, and `TargetAdapterProtocol`. |

### `run/manifest.py`

Status: rejected as redundant

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve RunManifest construction behavior, but move hardcoded demo composition out of Engine. |
| `integration/p1-new` | Reject the obsolete RunSnapshot model; selected-Case execution may be reconsidered only with a real requirement. |
| Current refactor | Reuse `domain.RunManifest` directly; it already owns immutability, validation, exact references, execution limits, and hashing. |
| From scratch | No code justified. A builder would only forward arguments to the Domain constructor. |
| Removed | Empty `run/snapshot.py`; no replacement module and no compatibility alias. |

### `run/engine.py`

Status: implemented; retry-focused regression passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve sequential Case execution, Trace/Result persistence, and terminal Run transitions. |
| `goal/p1-demo` | Remove manifest construction, report building, scheduler forwarding, and hardcoded demo Target details from Engine. |
| `integration/p1-new` | Adapt execution identity, Trace context, strict Trace identity checks, and timeout cancellation. |
| `integration/p1-new` | Reject direct polling, obsolete models, and concrete integration exceptions in Engine. |
| Current refactor | Reuse `EvaluationRun`, `transition_run`, repository operations, and `TargetAdapterProtocol`. |
| `goal/p1-demo` and `integration/p1-new` | Reuse no persisted-state cooperative cancellation; neither reference implements that workflow. |
| Current refactor | Reuse repository Run status, typed Target cancellation, and the adapter `cancel(handle)` boundary. |
| From scratch | Inject Case evaluation and Trace resolution, validate complete Result sets, enforce bounded concurrency, apply typed infrastructure retry, and observe persisted cancellation without crossing ownership boundaries. |
| From scratch | Implement safe-boundary cancellation checks and cancellation-wins terminal race handling. |

### `run/retry.py`

Status: implemented and wired through `run/engine.py`

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve no retry code; its Run Engine fails immediately for every Target exception. |
| `integration/p1-new` | Reuse no Run retry orchestration; the available team reference also has no infrastructure retry implementation. |
| Current refactor | Reuse `RunManifest.max_retries`, typed `TargetExecutionError` codes, and per-attempt execution/Trace identity generation. |
| From scratch | Implement the fixed retryable-code policy, bounded backoff, shared per-Case budget across start/wait failures, and focused no-evaluation-retry tests. |

### `integrations/targets/demo_loan.py`

Status: implemented and wired through `application/run_management.py`

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve Case-by-Case deterministic demo behavior; reject `PythonFunctionTarget` and Agent-side Case iteration. |
| `integration/p1-new` | Preserve W3C Trace context propagation only; reject old execution models and polling. |
| Current refactor | Reuse `TargetAdapterProtocol`, `LoanAgent.invoke()`, and in-memory Trace capture. |
| From scratch | Implement synchronous lifecycle state, Case-to-turn translation, completion spans, and typed adapter errors. |
