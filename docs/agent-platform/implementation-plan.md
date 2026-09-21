# Agent platform selection implementation

Branch: `feature/agent-target-selection`, based on updated `refactor-1` at `6e489fe`.

## Approval and progress

- [x] Requirement, UI layout, local simulated execution scope and file names approved.
- [x] `AgentTargetPicker.vue` responsibility and detailed design approved.
- [x] Explicit `directory` input approved to permit isolated implementation before API review.
- [x] Component and focused browser tests implemented.
- [x] `frontend/src/api/agent-platform.ts` responsibility review.
- [x] `frontend/src/api/agent-platform.ts` detailed design approval and implementation; focused HTTP/provider tests passed.
- [x] `EvaluationTaskForm.vue` responsibility and detailed design approved; component connected with separate single-task submission and preserved A/B path.
- [x] Local peer and exact-target task execution implemented under the subsequent autonomous authorization.
- [x] End-to-end verification and required regression completed; local acceptance is ready.

## Approved task form responsibility: `EvaluationTaskForm.vue`

Status: responsibility, detailed design and the implemented/verified form checkpoint approved by the user. Focused verification is recorded below.

Purpose: compose the new platform target picker with the existing single-task form, preserving dataset/evaluator/execution settings and the existing A/B path, and coordinate validated task submission.

Owns:

- Render `AgentTargetPicker` for single-task target selection and pass the implemented `agentDirectory` explicitly; retain the existing A/B target UI and submission behavior.
- Keep new platform target state separate from old demo/local-bank/A/B state. Load the configuration needed by the active path without making unrelated legacy target discovery a prerequisite for the new single-task path.
- Keep dataset/version/case selections and user-entered execution settings stable when the platform target changes. Existing target-mode watchers must not silently overwrite them for the new path. Task-kind-specific A/B constraints remain as before.
- Preserve dataset/evaluator prefill from existing entry points. A source containing only an old targetVersion cannot identify a new team/agent/branch tuple; require explicit target reselection instead of guessing.
- Coordinate form validation, submit locking and one current target/token snapshot from the picker. Submit the exact target and configured dataset/evaluator/execution inputs; validate supported limits and surface unsupported combinations rather than silently changing them.
- Consume the backend creation result, retain the existing task-link/created-event navigation behavior, and distinguish a creation or link-save failure from successful submission. No automatic resubmission after an uncertain creation response.
- Clear or invalidate target-dependent static-analysis results when the target changes, and coordinate analysis/graph availability only from actual matching descriptor data. Platform metadata is unavailable, so single-task static analysis is disabled with an explanation; no demo descriptor is substituted.
- Keep token material transient in the new submission path and out of task-link metadata, persistent frontend stores and user-visible raw error output.

Does not own HTTP directory parsing/pagination, platform authentication, backend credential persistence, target snapshot persistence, scheduling, worker execution, workflow instance creation or mock-service behavior. Workflow `agentId + agentVersion` instance creation remains in the approved backend execution scope, not the Vue form.

Approved frontend boundary: the task request/response below and the unavailable static-analysis/graph presentation are confirmed. Backend implementation remains subject to its own file review.

Expected focused verification after implementation: changing a platform target does not overwrite dataset/execution choices; task submission matches the selected target; invalid/expired selection blocks submission; old A/B behavior remains; entry-point prefill is preserved; stale static reports and secrets cannot leak into new task metadata.

## Approved task form detailed design

### Composition and state

Keep the existing component props (`source`) and events (`close`, `created`) unchanged. Add direct imports of `AgentTargetPicker`, its selection type and `agentDirectory`. Render the new picker only when taskKind is single, supplying directory and submit/loading lock state. Receive its nonsecret selection event and hold a component ref for the approved synchronous submission read.

The existing demo/local-bank target variables and target markup belong only to the A/B path after this change. Platform selections never write selectedAgent/selectedVersion/gitBranchUrl, so the old target watchers cannot rewrite the new path's dataset or execution settings. Guard legacy watchers, validations and static-analysis calls to the legacy path. Preserve the existing A/B unsupported-real-target restriction and candidate-versus-baseline validation.

Initial single-task load obtains datasets and evaluators independently of `/versions` and `/bank-targets`. Load legacy target data upon first entering A/B; isolate its loading/failure state and ignore a late initialization response once the user has switched away. Preserve existing A/B choices on later visits. Changing task kind retains existing A/B mode constraints/default behavior; this design does not introduce separate dataset/execution drafts per mode.

Unmount the picker when entering A/B, clearing its token and target reference. Returning to single requires login and target selection again. Closing the whole form also clears selection; no hidden picker or persistent token store.

Existing source dataset/version/case/evaluator prefill remains intact. A source.targetVersion alone is insufficient for platform identity and must not auto-select a platform agent. It remains available for the existing A/B target initialization.

### Form state and validation

Platform target changes affect only platform target validity and target-dependent analysis state. Do not write selectedDataset, selectedDatasetVersion, selectedCaseIds, selectedEvaluators, concurrency, timeout, retries, repetitions, launchMode or scheduledAt because a team/type/agent/branch/version changed.

Retain existing published dataset/version, nonempty case selection, evaluator coverage confirmation, grading-mode, repetition and reservation checks. The new single path uses current general numeric bounds (concurrency 1–30, timeout 1–3600 seconds, retries 0–5, repetitions 1–20); these are input bounds, not a promise that every backend target supports every combination. Backend capability validation remains authoritative and an unsupported combination is reported without modifying input values. Existing A/B target-dependent limits remain unchanged.

Enable single-task submit only with an effective picker selection and no relevant load/submit in progress. At submit start, synchronously read one `{ target, token }` snapshot and lock the picker and other form controls before any asynchronous validation or confirmation. Read/retain a matching copy of dataset/evaluator/execution inputs for this submission. Release the lock in all completion/error/cancel paths. A cancelled coverage confirmation sends no creation request. Closing/switching task kind is blocked during submission as in the existing form.

### Proposed frontend-to-backend contract

This defines what the form will send and consume, not an implementation of the backend route. It requires the later `server/routes/agent_platform.py` review to honor the same boundary. The directory-only `agent-platform.ts` is not expanded to include task creation.

Proposed endpoint: `POST /api/agent-platform/evaluations`, using the existing shared AgentGate `httpRequest` helper for backend envelope handling and configurable `/api` base.

Token is supplied once in the request-specific `X-Agent-Platform-Token` header (raw token, no Bearer prefix). This separates the upstream credential from any AgentGate Authorization header. The backend may use it as `Authorization: Bearer <token>` when contacting the platform. Do not add it to shared HTTP defaults, the JSON payload, task links or frontend persistence. Backend credential retention for asynchronous/queued runs requires its own approved design.

JSON input:

```json
{
  "target": {
    "team_id": "team-id",
    "agent_id": "agent-id",
    "type_group": "abcclaw",
    "branch_id": "branch-id",
    "agent_version": "1.0.0"
  },
  "dataset_id": "dataset-id",
  "dataset_version": 1,
  "case_ids": ["case-id"],
  "evaluator_ids": ["evaluator-id"],
  "max_parallel_cases": 2,
  "timeout_seconds": 300,
  "max_retries": 0,
  "repetitions": 1,
  "scheduled_for": "2026-09-22T02:00:00.000Z"
}
```

`case_ids` is omitted for all cases; `scheduled_for` is omitted for immediate execution and allowed only under existing single-repeat reservation rules. `branch_id` is omitted for base/workflow and mandatory for abcclaw. No display names, raw platform metadata, Git URLs, demo version aliases or token appear in the payload. The backend must validate target membership/group/version and resolve its own runtime descriptor instead of trusting display data. Workflow instance creation still uses the separately confirmed agentId + agentVersion contract.

Expected success data after the shared helper unwraps the backend response: `{ id, kind, run_ids }`. `kind` is single for one repetition and stability for multiple repetitions; IDs are nonblank and run_ids is unique with the expected count. HTTP acceptance means task creation/submission, not completed evaluation. Never replace missing response IDs with a guessed run or demo ID.

The backend is expected to persist task/run associations atomically before success. Construct the existing `TaskLink` with those IDs and `staticReports: []`, then call the existing `refreshTaskLinks()` to update the frontend cache and notify task-list listeners. Do not redundantly PUT the already-created task association via saveTaskLink for this new path; legacy A/B save behavior remains unchanged. Emit the existing created event for successful navigation.

If refreshing links fails after a valid creation response, keep the known created task ID, emit the created event and show a safe warning that the task exists but the list refresh failed. Do not issue another creation request. For a timeout/network/5xx or malformed creation response, report that creation status must be checked in the task list before retrying; do not auto-retry. For explicit 4xx rejection, show a fixed safe input/access error without reflecting raw response detail or overwriting the form.

### Static analysis and graph proposal

The new directory APIs do not provide a matching TargetDescriptor. Proposed behavior for the platform single-task path: keep the existing static-analysis entry visible but disabled, with a short explanation that the selected platform target has not supplied analysis metadata; show an unavailable graph message instead of a demo/local-bank graph. Normal evaluator selection and task execution remain available.

Clear old reports, outstanding analysis validity and open analysis dialog when changing target identity or leaving a task path. Merely refreshing an unchanged target should not be interpreted as a different target; no previous report may be submitted under another identity. A/B retains its existing analysis/graph availability. Re-enabling platform analysis when full descriptors become available is a future reviewed change, not a fabricated descriptor in this file.

This unavailable-state behavior is a deliberate presentation decision requiring approval with this detailed design; no TaskEvaluatorPicker internals need changing because it already accepts staticAvailable.

### Local functions and implementation boundary

Keep the existing common dataset/evaluator validation and A/B submission logic. Add focused functions for platform selection reception, lazy legacy-target initialization, constructing/submitting the single-task snapshot, validating its creation response and finishing list refresh/navigation. Use local typed objects for the new request/response boundary; no generic service, schema migration, task engine or credential manager in this component.

Implementation changes only this Vue file plus its focused tests and progress documentation. Tests can intercept the agreed backend boundary while the backend route is unimplemented. This demonstrates frontend composition and payload correctness, not an operational end-to-end workflow. The subsequent route/worker/mock implementation remains required before this feature is complete.

### Verification

- Default single mode does not depend on legacy target catalog availability; source dataset/version/case/evaluator selections remain.
- Changes at every platform selection level and logout preserve dataset and execution inputs; old target defaults never fire on the new path.
- Base/workflow request omits branch_id; abcclaw submits the exact original branch_id/version. Token appears only in the per-request header and not in task-link state or UI errors.
- Submission locks before asynchronous confirmation; double clicks create only one request. Invalid selection or cancelled confirmation creates none.
- Success refreshes/navigates without a redundant association PUT. A failed refresh never resubmits; malformed/uncertain creation response never claims success.
- A/B still uses its existing target selection, endpoint, constraints and task association handling; a late A/B catalog response cannot alter a single-task form.
- New platform static analysis/graph are explicitly unavailable; A/B analysis remains unchanged and stale reports cannot cross paths.
- Rerun existing picker/provider checks and applicable A/B/frontend form tests, plus typecheck/build/lint.

## Approved API responsibility: `frontend/src/api/agent-platform.ts`

Status: responsibility and detailed design approved; implementation and focused verification complete. Production task-form wiring is implemented at the following form checkpoint; backend execution remains pending.

Purpose: implement the real directory-query dependency consumed by `AgentTargetPicker.vue`, translating the documented platform responses into the component's normalized options.

Owns:

- Team lookup (interface 3), team agent lookup (interface 4), base/workflow versions (interface 2), abcclaw branch tree (interface 5) and branch versions (interface 6).
- Per-request Authorization from the supplied token; correctly configured platform URLs and original `/web/...` paths, independent of AgentGate's `/api` base and identity context.
- Response envelope handling, required-field validation and complete pagination for team/agent lists. A partially failed query must not be represented as a complete result.
- Mapping platform names and IDs, preserving branch hierarchy and raw type values, and normalizing supported agent groups. Unknown/conflicting types remain explicit instead of falling back to base.
- Reporting sanitized query failures to the caller, retaining HTTP status such as 401/403 without exposing the supplied token or raw credential-bearing errors.

Does not own UI loading/selection state, login sessions, token storage, default selections, dataset/execution settings, A/B, task creation, runtime instance creation/deletion, execution or BJS dispatch. It does not implement the mock peer or supply fallback sample data when a request fails.

Existing `utils/request.ts` automatically unwraps envelopes and uses the AgentGate `/api` base. Its current behavior must remain unchanged for existing consumers. The approved design below defines its separate platform requests, type parsing and pagination.

Scope boundary: despite the general filename, this file is limited to directory queries at this checkpoint. The approved workflow runtime creation contract (`agentId + agentVersion`, with `taskId`) remains owned by later execution integration.

## Approved API detailed design

### Public operations and composition

Implement five plain asynchronous functions matching the existing `AgentDirectory` signatures: `getTeams`, `getAgents`, `getBranches`, `getAgentVersions`, and `getBranchVersions`. Export them as the explicit `agentDirectory` object for later injection into the picker. No factory, registry, global login state or request-on-import behavior.

Reuse the component's exported option/selection dependency types through type-only imports; this does not load the Vue component at runtime. No additional contract file or component changes in this checkpoint.

### Transport and configuration

Use native `fetch` for these read-only platform requests. Do not use or modify the shared AgentGate Axios instance: its `/api` base and automatic envelope unwrapping belong to existing consumers.

The platform origin and abcclaw origin are separately configured by `VITE_AGENT_PLATFORM_ORIGIN` and `VITE_ABCCLAW_PLATFORM_ORIGIN`. Empty values mean same-origin `/web/...` requests for the approved proxy arrangement; explicit values are HTTP(S) origins only, without credentials, query, fragment or path suffix. Configuration is deployment-controlled, not supplied by the token textbox or returned by directory records. No hard-coded bank example hostname and no automatic fallback to a different host after failure.

Every call supplies the token as an argument. Send it only in `Authorization: Bearer <token>`, not in query parameters, cookies or persistent defaults. Use `credentials: omit` so unrelated browser login cookies are not forwarded, and reject redirects rather than silently changing the destination. Required IDs must be nonblank and are encoded with URLSearchParams without changing their values. Reject invalid token input before any network call, using the component's same 512-character/no-whitespace/no-Bearer-prefix rule.

Each complete directory operation has a 30-second deadline, including all pagination requests. Abort its outstanding fetch on expiry and clear the timer in all completion paths. No automatic retry or cross-call cache; the component already owns user-triggered retry and stale-result rejection.

### Exact endpoint handling

| Operation | GET path | Query parameters | Expected response |
|---|---|---|---|
| getTeams | /web/ops/team/getTeamRole | page from 1, limit=300 | ResponseBase.data is a Page |
| getAgents | /web/agent/agents | teamId, name empty, page from 1, limit=1000 | Direct Page, without a data envelope |
| getAgentVersions | /web/agent/getAgentVersionList | agentId | ResponseBase.data is an array |
| getBranches | /web/abcclaw/v2/branchTree | agentId | ResponseBase.data is a tree array |
| getBranchVersions | /web/abcclaw/v2/listVersions | agentId, branchId | ResponseBase.data is an array |

For ResponseBase, require the documented success code string `"0"`; do not depend on message language. Do not accept alternative envelope shapes or synthesize success for malformed JSON. The direct Page endpoint is parsed by its own documented shape.

### Pagination and validation

Read all team and agent pages sequentially. Validate records plus nonnegative integer total/pages, positive integer size/current, and current matching the requested page. Permit an empty first page with total=0 and pages=0 or 1. Follow the server-reported page size and page count, checking their consistency with total rather than assuming that the requested limit was honored.

Stop only after the last reported page and validate the total raw record count. A failed page, early empty page, repeated/missing page, inconsistent pagination metadata or changing totals fails the whole operation; do not return a partial list labeled complete. This does not provide an upstream snapshot guarantee, so the eventual task submission must revalidate its exact target.

Team option identity is teamId, not membership record id. Identical normalized team entries may be coalesced after counting all raw records; duplicate team IDs with conflicting names fail validation. Duplicate identical agent/version options may likewise be coalesced; conflicting records for one option identity fail instead of silently choosing one. Preserve server order.

Validate stable IDs and required names/versions as nonblank strings. Unknown extra fields can be ignored; malformed required data causes an error rather than silent record loss. Optional display fields may be absent, but if present must have the documented type. No filtering of draft/test/published versions.

### Agent type and branch mapping

Preserve raw agentType and arrangeType as platformAgentType and platformArrangeType. Normalize each nonempty recognized value: `base` or `workflow` -> the `base/workflow` group; `abcclaw` or `abcclaw2` -> the `abcclaw` group. The slash denotes the UI group, not an additional accepted raw platform value. The abcclaw2 value is supported because the supplied team-agent example explicitly uses it.

If both fields are present, both must be recognized and resolve to the same group. Base versus workflow still remains visible in the preserved raw fields. If only one field is present, use its recognized group. Unknown values, conflicting groups or both fields missing produce typeGroup=null, retaining the agent for an explanatory UI message. Do not guess new values or add deprecated aliases.

Recursively normalize the branch tree while preserving children and every original branchId. The component, not this API module, flattens it for display. Branch IDs must be unique across the tree; optional branchName becomes null if absent/null; missing children is treated as a leaf, while a non-array children value fails validation. This tree is JSON data and never a Git branch URL.

For branch version responses, a returned branchId must match the requested branch. Return agentVersion/status only after that check; do not merge versions from multiple branches. Interface 2 does not acquire or synthesize a branchId.

### Errors and internal functions

Use ordinary Error objects with typed `status` and `kind` fields rather than a service/error class hierarchy. Kinds: invalid_input, configuration, http, business, protocol, network, timeout. Preserve the actual HTTP status for HTTP failures, including 401/403; local validation, transport and timeout failures use status=0. Successful-HTTP business/protocol errors retain that response's HTTP status without pretending it was an authentication status.

Only fixed safe messages are exposed. Do not attach raw response bodies, platform message text, request objects, token-bearing headers or the original error as a cause. The current component can use status for 401/403 and display its existing generic retry message for other failures.

Internal helpers are limited to URL/input validation, one JSON GET, documented envelope/Page parsing, complete pagination, and team/agent/branch/version transformations. Each public operation orchestrates these functions. No task submission, instance creation, BJS dispatch or local mock fallback is added here.

### Verification scope

Focused tests will cover exact paths/query encoding/Authorization, platform versus abcclaw destinations, both response shapes, multi-page completeness, token isolation between concurrent calls, request timeout, HTTP/business/malformed-response errors without secret leakage, type mapping including abcclaw+abcclaw2, unknown/conflicting types, nested branch IDs, mismatched branch responses, and preserved version statuses.

Use the already approved `frontend/tests/agent-platform-task.spec.ts` for provider/consumer boundary tests; full task execution assertions are deferred until task integration exists. Rerun the existing picker suite with its current fixture, and typecheck/build/lint the frontend as appropriate. No live bank service or credentials are needed for these tests.

## Current component contract

The component exports its required `AgentDirectory` interface and normalized option types. The API module implements this UI dependency; no runtime Vue import is needed for its type-only references.

Inputs: required `directory`, optional `disabled`. Directory calls return complete lists and receive a temporary token plus the current upstream IDs. The provider owns HTTP, pagination and type normalization; unknown or conflicting agent types use a null group and are not runnable selections.

`selection-change` emits a copied `AgentTargetSelection`, or null while incomplete, loading, invalid or failed. `readSubmissionSelection()` returns a separate target copy and the locked token only when valid. No token is included in selection events or persisted by the component.

Queries run on dropdown opening. Changing upstream selections clears dependents before applying the new value. Per-list request sequences and session/context checks prevent obsolete responses from modifying state. Failed queries never fall back to sample data, and raw provider errors are not shown to users. Unmount and provider replacement clear the session.

## Implementation sources

- `origin/goal/p1-demo`: no matching team/branch/token picker was found; no source copied.
- `origin/integration/p1-new`: target catalog code uses a different registration/version contract; not reused for this platform directory.
- Current frontend: adapted its Vue/Element Plus conventions and existing two-column field layout. Kept task execution and dataset ownership outside the new component.
- New work: explicit directory dependency, component state transitions, request invalidation and focused tests.

## Verification

Directory checkpoint: 23 browser tests passed (12 picker tests plus 11 HTTP directory/provider tests), including the picker consuming the real directory module against intercepted HTTP responses. Frontend typecheck/production build, API ESLint and formatting checks passed. Build retains the existing large-chunk warning. No end-to-end platform task execution is claimed.

From repository root, run the independent browser suite:

```sh
frontend/node_modules/.bin/playwright test --config frontend/tests agent-target-picker.spec.ts agent-platform-task.spec.ts --workers=1 --output runtime/agent-platform/results --reporter=list
```

The suite starts and closes its own loopback Vite fixture server, uses the real component and Element Plus, and passes a deterministic in-memory directory. It needs no AgentGate API, credentials, Redis or remote service. It covers token limits, readonly/logout, both base and workflow, nested abcclaw branches, target snapshots, parameter routing, type mismatch, empty/error/retry, removed versions, late responses, unmount, duplicate requests, keyboard/mouse access and narrow layout.

The HTTP directory suite now verifies pagination, exact URLs and token headers, separate origins, invalid configurations, sanitized failures, no credential redirection, branch identity and an operation-wide timeout. HTTP responses are intercepted locally; neither suite requires a live bank service. The later form fixture also exercises single-task submission and existing A/B creation against intercepted AgentGate responses; execution by a real backend remains unverified.

### API implementation sources

Neither `origin/goal/p1-demo` nor `origin/integration/p1-new` contains the documented getTeamRole/branchTree/getAgentVersionList implementation. The new provider follows the approved wire contract; existing AgentGate Axios behavior was inspected and left unchanged. Existing picker types are reused through type-only imports.


### Task form implementation sources and behavior

The existing form is the A/B behavior source: its version selection, validation, comparison endpoint and task-link association are retained. The goal/p1-demo and integration/p1-new references do not provide this platform tuple/header submission contract; the new single-task submission follows the approved design instead. Existing dataset/evaluator APIs, task-links store and shared AgentGate HTTP transport are reused through explicit imports. No backend or proxy change is included.

The platform picker is now rendered on the production single-task path. Legacy catalogs load lazily for A/B, with late-response invalidation. A single submission captures target/token, case scope, evaluators and execution settings before asynchronous checks, locks controls, posts the approved contract and validates task/run identities. Successful creation refreshes links and emits the existing event without a second association write. Failures are sanitized; uncertain creation asks the user to check task state. A confirmed task survives a failed list refresh.

The form also prevents temporary empty dataset lists from erasing source-prefilled case IDs while a dataset loads. New-platform target changes never write dataset or execution controls. Static analysis is disabled with an explanation until matching metadata exists; A/B analysis availability is retained.

Task creation is currently tested using intercepted HTTP responses. The `/api/agent-platform/evaluations` backend route, local peer, proxy and real/simulated execution loop remain pending their file reviews. Workflow instance creation (`agentId + agentVersion`, with taskId) is not modified by the frontend work.


### Task form verification

36 focused browser scenarios passed: 12 picker, 11 directory/provider and 13 form scenarios. The complete run passed all 35 then-existing tests; after preserving the existing A/B catalog-failure fallback, its new regression and both affected A/B tests passed. The selected-case submission lock was additionally checked after explicitly disabling its dropdown. The form tests cover source-prefilled cases, independent datasets/settings, exact workflow/abcclaw payloads, stability and UTC scheduling, preflight locking and cancellation, token isolation, safe rejection/uncertainty messages, refresh failure and legacy A/B association. Typecheck/production build, ESLint and formatting passed; the pre-existing bundle-size warning remains.

The results are scoped to frontend behavior against intercepted HTTP. No backend route, mock peer, runtime instance, persisted task or real bank execution is claimed at this checkpoint.


## Approved route responsibility: `src/agentgate/server/routes/agent_platform.py`

Status: responsibility and detailed design approved by the user. Route implementation and focused verification are complete; awaiting implementation checkpoint review.

Purpose: provide the HTTP boundary between the approved single-task form and the platform-evaluation application use case.

Owns:

- Accept the already agreed task creation request and request-specific platform-token header, validating HTTP input shape and basic field constraints.
- Preserve AgentGate's existing user/team context separately from the external platform team selected as part of the target. An external teamId must not replace the AgentGate caller team supplied by the existing request context; this route does not strengthen or replace the existing identity middleware.
- Pass the exact selected target, dataset/evaluator/execution inputs, temporary credential and caller context explicitly to the application capability. Membership/version/capability checks and task creation belong to that capability and its integrations.
- Translate the confirmed creation result into the agreed task ID, task kind and run IDs; success means accepted task creation, not completed evaluation. The application owns atomic persistence and dispatch semantics.
- Map known failures to safe HTTP responses without returning credentials or raw upstream error/request objects. Keep unexpected or uncertain outcomes distinct from confirmed creation.

Does not own directory HTTP parsing, platform login/authentication, credential encryption/retention, descriptor construction, database transactions, scheduling/worker loops, runtime instance lifecycle, A/B changes or local-peer behavior. Workflow instance creation remains agentId + agentVersion with taskId in the execution integration; it is not implemented inside a route.

Review boundary: confirm this one file's responsibility first. Dependency composition, request/response models, functions, exception mapping and tests will be proposed only at its detailed-design checkpoint. Existing server/app.py registration and other files retain their separate reviews.


## Approved route detailed design

File: `src/agentgate/server/routes/agent_platform.py`. This checkpoint defines the route and its explicit application boundary only. It does not approve application, execution integration or app registration implementation.

### HTTP input models

Two Pydantic transport models, `PlatformTargetInput` and `PlatformEvaluationInput`, use frozen configuration and reject extra fields. They are HTTP-owned validation types, not domain models; application code must not import them. No models are added to a generic shared contracts module.

`PlatformTargetInput` accepts exact nonblank string team_id, agent_id and agent_version plus the literal type_group base/workflow or abcclaw. IDs retain their original text rather than being silently trimmed or translated. abcclaw requires a nonblank branch_id. base/workflow requires branch_id to be omitted; explicit null is also rejected to maintain the agreed wire contract. UI names, Git branch URLs and raw type metadata are not fields.

`PlatformEvaluationInput` accepts target, nonblank dataset_id, positive strict-integer dataset_version, required nonempty unique evaluator_ids, and optional case_ids. Omission of case_ids means all cases; a provided list must be nonempty, unique and contain nonblank string IDs. Explicit null is rejected. Execution values are required strict integers: max_parallel_cases 1–30, timeout_seconds 1–3600, max_retries 0–5 and repetitions 1–20. Booleans, fractional numbers and numeric strings are not coerced. The frontend already supplies these values, so the route does not invent defaults or choose evaluators.

scheduled_for is optional by omission. If present it must be a timezone-qualified ISO datetime string later than the current UTC time; convert it to UTC for the application. Reject null, timestamps supplied as numbers, timezone-free dates and a reservation combined with repetitions greater than one. Application validation rechecks any time-sensitive or target-specific constraint before committing.

### Token and parsing

`read_platform_token(request)` reads exactly one X-Agent-Platform-Token header. Missing, repeated, empty or malformed values are rejected before the submission capability is called. Accept at most 512 characters, reject whitespace, control characters and a Bearer prefix, and do not trim or rewrite the value. Pass the raw token as a separate application argument. Do not read it from JSON, a query parameter, cookies or AgentGate's Authorization header. Do not persist it on request/app state or attach it to models, task metadata or errors.

`read_platform_input(request)` reads JSON and validates `PlatformEvaluationInput` explicitly. This avoids the default validation response echoing input values, including credentials mistakenly supplied in an extra body field. Malformed JSON, wrong shapes, unknown fields and constraint failures receive fixed safe 422 messages. A non-JSON content type receives a fixed 415 response. Do not return Pydantic input/context objects, raw bodies, validator exception strings or upstream text. The model definitions remain available for focused validation tests; request parsing is deliberately explicit rather than relying on FastAPI's automatic request-body error output.

### Explicit application boundary

Use one `SubmitPlatformEvaluation` Protocol at the real route/application boundary. It describes a synchronous keyword-only callable returning the existing domain EvaluationTask. The production application function and recording/failing test callables satisfy it structurally without inheriting or importing the route's types. There is no service registry or class hierarchy.

Arguments are typed stable values: team_id, agent_id, type_group, agent_version, optional branch_id; dataset_id/dataset_version; optional tuple of case_ids and tuple of evaluator_ids; the four execution integers and optional UTC scheduled_for; raw token; and AgentGate user_team_id/user_id/user_name as separate caller fields. Convert validated lists to tuples when passing them. Do not pass an HTTP Request, Pydantic route model or open-ended payload dictionary into application code.

`get_platform_submitter(request)` obtains this explicit callable from `request.app.state.submit_agent_platform_evaluation`. Later, the separately reviewed server/app.py composition root will bind its real dependencies and install it. This is process-lifetime dependency composition, not a credential cache. If it is absent or not callable, return fixed 503 without fallback to a demo. Current-file tests attach a recording callable to a minimal FastAPI instance; no change to ServerDependencies or server/app.py is included now.

`launch_platform_evaluation(request)` is the single async route handler for POST /api/agent-platform/evaluations. Parse inputs, capture the existing get_user_info() context and call the synchronous submission boundary in the framework thread pool so blocking business work does not block the event loop. Preserve the current empty-team/anonymous defaults if no user context exists; do not introduce a new authentication policy. Capture/pass the context explicitly and never call set_user_info with target.team_id. Each valid request invokes the submitter once; the route does not retry or execute evaluations in its HTTP lifecycle.

### Result and errors

`created_task_response(task, repetitions)` accepts only an EvaluationTask with kind single for one repetition or stability otherwise, exactly the requested number of unique nonblank run IDs, and a nonblank task ID. Return only id, kind and run_ids with HTTP 202. Do not serialize credential_id, static reports, descriptors or other domain fields. The existing response-envelope middleware wraps this once when the router is registered in the main app. The standalone test also verifies this middleware behavior.

The submitter's successful return means the application has durably saved task/run associations and accepted responsibility for dispatch or scheduled execution. It does not mean completed evaluation. If persistence succeeded but dispatch has a recoverable failure, application-level handling must retain truthful state; the route must not reinterpret that as a validation rejection or retry creation. Transaction, credential lifetime and dispatch recovery mechanisms remain for the application file's detailed review.

The application callable may use these standard exceptions only for the specified semantics; transport-specific upstream exceptions must be translated at its integration boundary:

- PermissionError -> fixed 403: external target access was rejected before task creation.
- LookupError -> fixed 404: selected target/dataset/version/evaluator was unavailable before task creation.
- ValueError -> fixed 422: business/capability validation failed before task creation.
- TimeoutError or ConnectionError -> fixed 503: submission could not be confirmed; inspect task status before resubmission.
- Other exceptions or an invalid returned task -> fixed 500: submission outcome cannot be confirmed; inspect task status. A general RuntimeError is not assumed to mean a validation failure.

Catch PermissionError before other OSError-derived failures. Do not stringify, chain or log raw callback exceptions, payloads or headers in this route; its safe HTTP errors must not escape to the existing unexpected-error logger carrying an upstream exception. Missing-token syntax errors use 422 (no remote authentication has been performed); remote token/target authorization rejection becomes the safe 403 described above. No new business-exception class is introduced in the route.

### Implementation and tests

After approval, modify only this new route file, the previously approved tests/test_agent_platform_evaluation.py and progress/design records. Tests use a minimal FastAPI app, the existing response envelope/user-context utilities where needed, and explicit fake submitters. They verify:

- Both target groups, original branch/version values, omission rules, integer/list/datetime boundaries, raw header delivery and separate caller context.
- Invalid requests, missing/duplicate/oversized tokens and unknown JSON fields never call the submitter and never echo secret values.
- One call per valid request, safe exception mapping and absent-dependency rejection without real external calls.
- Exact 202 response projection, expected task/run cardinality, invalid output rejection and wrapping once.
- Concurrent submissions keep tokens and caller contexts separate; no credential is retained on shared app state or returned in task data.

No mock peer, route registration, persistent credentials, real application task creation or workflow instance is implemented at this checkpoint. Tests establish an HTTP boundary ready for the later application implementation. The dependency/input/output agreement becomes a constraint for that application review; its internal design is not pre-approved here.


### Route implementation and verification checkpoint

Implemented only src/agentgate/server/routes/agent_platform.py, tests/test_agent_platform_evaluation.py and progress/design documentation. The route uses frozen, extra-forbidden HTTP input models, explicit JSON/token parsing, a callable application dependency, thread-pool execution, separate caller/target team values, safe errors and a minimal 202 task response. It does not import or implement the future application workflow.

Verification: 128 tests passed (84 new route scenarios plus 44 existing server-error, run-route and task-domain regression scenarios). Ruff formatting and lint passed. Two pre-existing Starlette/httpx/AnyIO deprecation warnings remain. Tests cover both target groups, exact values, 512-character token boundary, duplicate headers, malformed/unknown input, missing required fields, numeric/list/date invariants, UTC conversion, anonymous defaults, original caller context, concurrent token separation, all agreed error mappings, invalid returned tasks, missing dependencies and the existing response envelope. Secrets are excluded from responses and route failure logs. Tests use recording/failing submitters and do not prove persistence or execution.

Implementation sources: the goal/p1-demo and integration/p1-new reference layouts have no matching agent-platform submission route. The current FastAPI route conventions, EvaluationTask domain type, request context, thread-pool facility and response envelope are reused; explicit credential-safe parsing and the platform-specific callable contract are new. No legacy route behavior or shared exception handler was modified.

The new router is deliberately not registered in server/app.py yet, and no production submitter is installed. Application creation, credential lifetime, dispatch recovery, local peer, proxy and end-to-end execution remain subject to their approved file-by-file workflow. No commit, push or merge performed.

Reproduce this checkpoint:

```sh
.venv/bin/python -m pytest tests/test_agent_platform_evaluation.py tests/test_server_errors.py tests/test_server_run_routes.py tests/test_evaluation_task.py -q
.venv/bin/ruff check src/agentgate/server/routes/agent_platform.py tests/test_agent_platform_evaluation.py
.venv/bin/ruff format --check src/agentgate/server/routes/agent_platform.py tests/test_agent_platform_evaluation.py
```

## Autonomous completion authorization

The user approved the route checkpoint and explicitly waived all remaining approval checkpoints until local acceptance is possible. Continue implementation, focused tests and end-to-end verification within requirement 001 without intermediate permission requests. No commit, push, merge or external production deployment is authorized.

Completion design: reuse the existing repository, evaluator engine, encrypted credential storage, Celery dispatcher and scheduler. Store only an encrypted per-task credential and its reference in snapshots; preserve credentials for queued/scheduled runs and explicit reruns, never use the legacy plaintext run.api_key. Pin team/agent/type/branch/version into the descriptor and snapshot. Validate the directory selection again before creating runs. Persist task and runs in the existing transaction, then dispatch; retain persisted failed state on dispatch failure.

The local peer supplies the five documented directory operations and deterministic chat responses. Workflow/base instance creation retains agentId + agentVersion with taskId. Since the supplied abcclaw document does not define branch-to-instance creation, the local peer provides a separately named mock-only creation endpoint. Execution in this delivery is explicitly enabled for the local mock origin and advertised mock capability only; it is not an unverified production abcclaw adapter. Observed HTTP turn/output evidence is normalized into actual stored traces without inventing tool or Skill events.

Acceptance will include browser selection and real API task creation, persisted results from the existing engine, all three target kinds, branch/version isolation, multi-turn/stability/scheduled execution, secret isolation and A/B regressions. A separate local database and ports avoid changing the existing running stack.

## Completed local acceptance — 2026-09-22

This completion record supersedes the pending work described in historical file checkpoints above. No commit, push or merge was performed.

Implemented the application submission function, platform client/adapter, app composition, worker integration, local peer fixtures/server, Vite proxy and isolated launcher. Reused the current repository transaction, credential encryption, evaluation engine, dispatcher, scheduler and result views; adapted existing bank payload/SSE parsing. The two reference branches provide useful demo execution behavior but no matching platform directory/selection capability, so platform selection validation and the mock peer were written for this approved scope.

Each target snapshot pins team, agent, runtime type, branch where applicable, and version. The encrypted credential reference supports asynchronous and scheduled execution. Missing credentials and dispatch failures become explicit failed runs; pre-persistence validation failures remove newly created credentials. Task ID equals the first run ID to preserve existing detail-navigation ownership. Instance cleanup runs after success or failure. Current text-only input restrictions are validated before tasks are persisted.

Live isolated stack: UI 5199, API 8099, peer 8119, Redis 6399, with actual Celery worker and scheduler. Workflow task `a0a554f4-2bb3-425f-af78-0391f3b4b00e` completed 3 samples at version 2.0. Cloudshrimp task `c2d6630b-7cb9-459f-a9e1-bcad7fd6ed26` completed 2 runs / 6 samples on branch-review version 1.0. Scheduled base task `450c26fa-668e-48ad-a70d-76ed9362f838` was claimed at its due time and completed 3 samples. Browser checks confirmed results, stability statistics and navigation. Existing Demo A/B completed both sides, with comparison scores 31.3 and 100.0.

The A/B live check exposed two unsupported request fields already emitted by the old form. The form now follows the existing comparison schema and displays fixed concurrency 1 / retries 0 as read-only; no backend A/B contract was expanded. Switching to Demo restores its actual 300-second timeout display.

Verification: full Python regression 1237 passed, 25 skipped (24 external MySQL configuration, one absent private SDK archive), two dependency deprecation warnings. Focused browser suite: 36 passed. Frontend typecheck and production build passed, with the existing bundle-size warning. Live checks complement the browser suite's isolated HTTP fixtures. Evidence is retained under runtime/agent-platform/; reproducible commands and acceptance steps are in script/agent-platform-mock/README.md.

Production boundary remains explicit: local deterministic replies, no real authentication, and a mock-only branch instance-creation endpoint for abcclaw. Static-analysis/graph metadata is unavailable. This delivery does not claim validation against the real bank environment.
