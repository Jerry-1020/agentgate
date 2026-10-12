# AgentGate Project Progress

Last updated: 2026-10-08

## LLM 评估器保存、发布与按版本运行 — 2026-10-08

用户批准并授权完成后推送 GitHub。当前实际入口 JudgeSystem 已接通服务端草稿、发布启用与版本历史；
保存后刷新可恢复完整维度配置，保存失败保留编辑内容，写成功而刷新失败时保留已完成操作的状态。
删除原前端临时草稿/历史状态。发布后旧版本保持不变，任务配置区显示当时的模型、维度提示词、权重与阈值。

新增 `answer_quality@2`，单次模型请求返回逐维度分数、置信度、依据和复核标记；后端用十进制算法
计算加权总分，前端同步严格校验权重合计。保留原 `answer_quality@1`，历史按其原协议运行。
非法响应最多纠正一次，超时、错误和纠正均保留实际请求/响应证据，不能变为通过。
复用 Catalog/SQLite/RunManifest，没有新增持久化表或迁移别名。

单任务、平台 A/B 和稳定性任务均贯通精确版本引用，行内真实 Token、行外 local Token 与目录分流保持不变。
复合评估器子项仅作为执行依赖，主评估器来自用户明确选择，避免重复参与总分计算。
基线参考与职责记录在 [Catalog 实施计划](evaluator/catalog-implementation-plan.md)，
用户验收步骤见 [LLM 持久化操作指南](evaluator/llm-persistence-guide.md)。

后端全量回归：1550 项通过、40 项跳过（两条既有依赖弃用提示）。
前端验收：88 项单元测试、6 项真实后端保存发布浏览器测试、5 项任务版本及登录分流浏览器测试通过；
栈检查、lint、类型检查与生产构建通过。浏览器使用独立临时 SQLite，模型执行使用确定性客户端验证；
本次未访问付费模型或真实行内网关。

## In-bank complete evidence and BJS dispatch integrity — 2026-10-08

- Autonomous Goal scoped to complete in-bank Trace retrieval and truthful BJS failures. User explicitly deferred in-bank Skill static analysis because no real version-definition API is available; the existing unavailable UI remains unchanged.
- ChatABC base/workflow and Yunxia now require per-turn SSE Trace references, fetch configured project evidence and model attachments, validate session/Pod/input/output/completeness, and reuse SDK normalization. Missing evidence fails instead of becoming output-only success. Query credentials remain separate from login credentials; no conversation replay on query failure. Yunxia requests debugTrace.
- Removed BJS transport-error simulated success. Tests verify waiting/retry/exhausted-failure transitions and no retry inside the dispatcher. Remote exactly-once acceptance/cancellation is not claimed.
- Validation: full backend 1469 passed/40 skipped, including positive/negative tool-rule checks and Case input aliases (28 evidence tests total); loan runtime 32 passed; unchanged frontend 82 tests, lint, typecheck/build passed using the identical frontend source in the existing dependency worktree. Seven pre-existing Ruff diagnostics in the legacy adapters/execution tests remain; new evidence and changed BJS/query files pass Ruff. Existing dependency and frontend chunk-size warnings remain.
- Verified real local HTTP Trace query transport with fixture gateways, not a real in-bank deployment. See [configuration and acceptance](inbank-evidence-acceptance.md), [implementation ownership](inbank-evidence-implementation.md).
- Restarted the full local acceptance stack with the current source and preserved/backed up the existing database. All nine external loan smoke runs (three agents × rule/LLM/hybrid) completed with passing evaluation results, numeric scores and remote Trace evidence; model records identify DeepSeek v4 Pro. Real in-bank integration remains unverified. After autonomous implementation concluded, the user explicitly authorized committing and merging/pushing this work to `origin/integration/baibo`.

## Six-target HTTP Trace reporting — 2026-10-08

- Added authenticated complete-bundle upload and independent receiver storage without modifying original vendor sources. The three loan targets transmit actual SDK events and LLM attachments; three protocol peers transmit explicitly simulated traces, including simulated failure status.
- Local full startup enables strict reported evidence and shared private reporting credentials; in-bank gateway/Trace query configuration stays separate. The UI labels simulated traces. Remote sender endpoints require HTTPS; physical cross-machine/TLS deployment is documented, not claimed as tested.
- Six tasks/nine turns passed real HTTP acceptance (three actual DeepSeek v4 Pro loan executions). Receiver queries still returned all nine traces and nine LLM attachments while sender evidence was temporarily moved aside. Files were restored.
- Verification:1398 backend tests passed,35 skipped;32 tested-Agent tests;82 frontend unit tests;lint/typecheck/build passed. See [protocol, deployment and run IDs](trace/trace-reporting.md). Current feature work is on `feature/trace-reporting`; no merge or remote push is included in this Goal.

## Portable local delivery — 2026-10-08

- Completed the local eight-process launcher with the bundled upstream Trace Server file backend and local Agent directory. Unified Redis6397 and persistent runtime paths; retained BJS scheduling and configured in-bank gateway/Trace routing.
- Shipped seven loan evaluators using the recipient's model, alongside the existing three v3 datasets. Added read-only v2 historical results/report and a command that creates nine fresh rule/LLM/hybrid tasks.
- Replaced stale installation instructions. Removed automatic global process termination from service-start commands; pre-existing services are preserved.
- Verified clean-directory installation, all nine real DeepSeek v4 Pro smoke runs, browser Trace/LLM scores, shutdown/restart persistence, and wheel seed resources. Two LLM-only tasks scored85 below the existing95 task gate; evidence is retained, not converted to pass.
- Validation:1385 backend tests passed (35 skipped),29 tested-Agent tests,82 frontend tests,lint/typecheck/build. See [delivery evidence](bank-agents/delivery-verification-20261008.md).

## Annotation v2 per-turn editor — 2026-09-26

- Enabled per-turn forms for the template's selected annotation objects. Dataset review shows original input, actual output and source expectations beside compact dimension scores, tags, a single-line comment and a human expected-answer field.
- Added independent v2 object records with local persistence, range validation, draft/completed status and unsaved-change protection. Original datasets, runs and automatic evaluation evidence remain unchanged.
- Verification: 53 frontend unit tests, typecheck/build and affected-file ESLint passed; browser checks covered selected objects, multiple turns, range rejection, save/reopen and completed state. See [implementation record](annotation/implementation-plan.md).

## Task and dataset names — 2026-09-26

- Task creation starts with a required name. Names persist with platform tasks and appear in task lists, result headings and v2 annotation task filters. Visible historical tasks are named once using Agent name plus the original Shanghai-calendar month/day (for example 924).
- Dataset creation starts with its existing name field; cards keep using stored dataset names and historical dataset names are unchanged.
- Verification: 1333 backend tests passed, 35 environment-dependent skips; 50 frontend unit tests, typecheck, build and affected-file ESLint passed. Browser-created named task completed and displayed its configured name in the list and result page. See [implementation details](task-names/implementation.md).

## Annotation v2 template and conversation list — 2026-09-26

- Added independent v2 template creation with three optional annotation groups, default 0–100 range, and separate details/start actions on cards. Existing v1 behavior is retained.
- Added a dedicated v2 conversation list with evaluation task, aggregate score, evaluation time, content-based column filters, score interval and Bad Case shortcut. Exemption is browser-persisted and reversible.
- The user confirmed this stage covers the list, filters and exemption; the three v2 scoring forms remain a later stage. Loading retains the existing limit of 200 completed runs.
- Verification: 50 frontend unit tests, typecheck, build and affected-file ESLint passed. Browser checks covered 36 conversations, 17 Bad Cases, score ranges, combined filters, pagination, conversation details and exemption reload/recovery. See [implementation plan](annotation/implementation-plan.md).

## Human annotation feedback loop — 2026-09-24

- Connected annotation templates to the existing login-aware platform directory picker; target matching pins environment, team, Agent, branch and version. Added a completed-run source entry for historical Demo/tool traces.
- Added per-tool-span scores, tags, comments, explicit call/argument expectations and completeness checks. Inputs and actual Trace evidence remain unchanged; human scores are audit notes, while explicit expectations become existing rule contracts.
- Added previewed export to a new dataset draft and writeback to the original dataset draft. Existing checks at unrelated paths, other cases, published versions and historical reports are preserved. Deleted/changed source cases and changed preview drafts require manual reconciliation. Writes use current dataset APIs; multi-user atomic concurrency is not claimed.
- Resolved template-library refresh inconsistency by deriving the library from persisted task snapshots; fixed its route display. Annotation persistence remains browser-local, with no cross-browser/team synchronization claim.
- Browser acceptance completed on 5197: external Cloudshrimp branch/version selection; message/tool score validation; refresh recovery; export and publish; Demo A/B automatic grading (risky output fails, fixed version passes Final Output/Required Tool/Tool Arguments); follow-up annotation/writeback, published v1 hash unchanged. Restarted stopped Redis/Worker/Scheduler so actual jobs complete.
- Verification: 1327 Python tests passed, 35 environment-dependent skips, two dependency warnings; 44 frontend unit tests passed; frontend typecheck/build and affected-file ESLint passed with existing bundle-size warning.
- See [end-to-end operation guide](annotation/end-to-end-guide.md) and [implementation plan](annotation/implementation-plan.md). Changes remain uncommitted on `feature/annotation-feedback`; pre-existing task-deletion edits are preserved.

## Agent platform local acceptance — 2026-09-22

- Requirement 001 is implemented end to end on `feature/agent-target-selection`; the user's final instruction waived remaining approval checkpoints. Local UI, directory mock, exact target snapshot, encrypted credentials, real task persistence, worker execution, scheduling and result pages are connected.
- Workflow retains agentId + agentVersion. Cloudshrimp branch creation is explicitly mock-only. Dataset/execution selections survive target changes; missing graph/static-analysis metadata is explained in the UI.
- Live workflow, base reservation and Cloudshrimp stability tasks completed successfully. Original Demo A/B also completed and displayed comparison results. Fixed the form's unsupported A/B parameters and single-task detail identity coupling.
- Verification: 1237 Python tests passed, 25 environment-dependent skips, two dependency warnings; 36 focused browser tests passed; frontend typecheck/build passed with the existing bundle-size warning.
- Ready at http://127.0.0.1:5199/#/tasks . See [local acceptance instructions](../script/agent-platform-mock/README.md) and [completed implementation record](agent-platform/implementation-plan.md). No commit, push or merge performed. Earlier checkpoints below are historical.

## Agent platform submission route — 2026-09-21

- Implemented the approved HTTP route in isolation: strict target/task input checks, separate transient token header, explicit application callable, caller/team separation, safe errors and the agreed 202 task/run response.
- Verification: 84 new route scenarios and 44 existing related regressions passed (128 total); Ruff lint/format checks passed. Existing dependency deprecation warnings remain. Tests use fake submitters and verify response-envelope integration without real platform calls.
- Route registration and production application submission remain pending. No task persistence, runtime execution, local peer or proxy is claimed. No commit, push or merge performed.

## Agent platform task form — 2026-09-21

- User approved the implemented and verified form checkpoint. The responsibility of `src/agentgate/server/routes/agent_platform.py` is also approved. Its detailed design is approved and isolated implementation is complete; see the newer route checkpoint above.

- Implemented the approved `EvaluationTaskForm.vue` design: the single-task path now uses the platform picker/provider; platform target changes preserve dataset/evaluator/execution settings and source-prefilled cases. A/B retains its existing endpoint and association behavior, including Demo availability when the registered bank catalog fails.
- Submission takes one target/token/form snapshot, locks controls before asynchronous validation, sends the token only in a request-specific header and validates the returned task/run association. Refresh failure preserves confirmed task identity; uncertain creation is reported without retries or raw server detail.
- Verification: 36 focused browser scenarios passed across the complete 35-test run and the added A/B catalog-failure regression; affected A/B tests were rerun after that compatibility adjustment. Frontend typecheck/build, lint and formatting passed, with the existing large-bundle warning. Tests intercept HTTP locally and do not demonstrate backend execution.
- Backend task creation, proxy, local peer and execution loop remain pending their per-file reviews. New-platform static analysis/graph are explicitly unavailable until matching metadata exists. Workflow instance creation remains `agentId + agentVersion` with taskId. No commit, push or merge performed.

## Agent platform directory API — 2026-09-21

- Implemented the approved `frontend/src/api/agent-platform.ts` provider for interfaces 2–6, with per-call tokens, separate platform origins, complete pagination, explicit type normalization, branch-version consistency checks and sanitized failures. Existing AgentGate Axios requests are unchanged.
- Verification: 23 browser tests passed (11 new HTTP/provider tests and 12 picker regression tests); frontend typecheck/build, API lint and formatting passed. The picker/provider integration test intercepts HTTP locally and does not claim real bank execution.
- At this API checkpoint, production form wiring, proxy configuration, local peer and task execution remained pending. The newer form checkpoint above supersedes the frontend wiring status. No commit, push or merge performed.

## Agent target picker component — 2026-09-21

- On `feature/agent-target-selection`, implemented the approved isolated selection component with an explicit directory input: temporary token login/logout, team/type/agent/branch/version selection, exact-target submission reads and stale-response rejection.
- Verification: 12 focused browser tests passed; frontend typecheck/build, component lint and formatting passed. Existing large-bundle warning remains.
- At that component checkpoint the production task form, network provider, local peer and execution integration remained pending their file reviews; A/B and dataset/execution controls have not been modified. See [implementation plan](agent-platform/implementation-plan.md) and [requirement 001](requirements/001-agent-target-selection.md).

## Upstream 33db48a integration — 2026-09-18

- Integrated the new open-fin-sub/agentgate refactor-1 backend into an isolated delivery copy, retaining the existing UI, local-bank adapter, SDK, task links and UUID redaction fix.
- Added safe legacy table-prefix/identity migration; verified all 16 old tables and 112 historical runs on a read-only-source SQLite backup.
- Adapted task/sample/stability visibility and effective concurrency snapshots. Explicitly reject unsupported raw per-run API keys and nonfunctional BJS dispatch. Retain explicit external model environment loading.
- Backend: 1033 passed / 1 skipped; tested agents: 19 passed; frontend build passed. Three live browser runs covered 24 cases / 27 turns, with 297 raw SDK/database/API evidence checks passing. Live Judge, composite, static analysis and root-cause reports also persisted successfully; Judge review outcomes remain unchanged.
- Full checkpoint, delivery upgrade instructions and customer factory limitations: workspace-root docs/bank-agents/upstream-sync-20260918.md. Customer Pod create/readiness/upload/delete are not wired into the current local adapter and remain unverified in the customer environment.

## Reproducible bank-target delivery — 2026-09-17

- Repository-local Trace SDK dependency, separate locked Python environments, automatic 24-case database initialization, and fresh-run browser/Trace acceptance scripts are included.
- Current handoff instructions and validation are in workspace-root docs/bank-agents/. Older checkpoint references to developer-local audit documents below are historical records, not prerequisites for installing this delivery.
- Customer factory lifecycle, full cloudshrimp protocol and production equivalence remain outside the verified scope.

## Trace API correlation-ID redaction fix — 2026-09-17

- Preserve full UUIDs only in request/session/trace/span correlation fields (including namespaced keys); explicit sensitive-key policies still take priority. Other values still undergo recursive credential/PII redaction.
- Reproduced the historical Luhn/UUID collision before the fix. Added 29 regression cases including the real UUID, nested attributes, sensitive values in ID fields, explicit policy overrides, and an HTTP route/storage-invariance test.
- Verification: focused suite 83 passed / 1 skipped; full backend 1023 passed / 1 skipped (private SDK fixture), with two existing dependency deprecation warnings.
- Restarted the idle local stack. Across the existing three conformance runs, all 27 request IDs now match canonical storage; all 24 canonical Trace payloads and 27 raw JSONL file digests remain unchanged. No frontend, tested-Agent or original evidence changes; no model rerun.
- Evidence: workspace-root BANK-CONFORMANCE-AUDIT-20260917.md, follow-up section; runtime/conformance-20260917/trace-api-redaction-fix.json. Original audit evidence is retained.

## Full-stack real-target integration — 2026-09-17

- Existing UI layout retained; creation now binds the three live targets, published database cases, capability limits and exact descriptor fingerprints. Static analysis no longer routes these targets through Demo or aliases unrelated v1 descriptors.
- Added safe model metadata, pinned descriptor lookup, partial samples for non-completed runs, real-target stability and scheduled launches; one supervisor can launch all six local processes.
- Fixed SDK UUID/phone masking collision through a narrow public SDK rule override, retaining actual phone masking. Judge invalid JSON values get at most one correction; both responses/fingerprints persist and invalid results remain errors.
- Live tests include actual model execution, composite propagation, static report/reanalysis, scheduled dispatch, stability rounds, notes writeback and a versioned negative-control regression. Real model business failures and an optimizer invalid-confidence edge case remain visible, not coerced into passes.
- Workspace-root `FULLSTACK-ACCEPTANCE-20260917.md` supersedes older frontend-not-bound checkpoints below and records exact run IDs and production boundaries.
- Final verification: 994 backend tests passed / 1 skipped; 19 tested-Agent tests passed; 16 unified UI tests and 4 new target UI tests passed; production frontend build passed. All three modes completed a final live low-risk smoke run after restart. Services remain local and running.

## Independent bank-tested Agent checkpoint — 2026-09-17

- Added a separate `tested-agents/` service: real model tool-loop, LangGraph workflow, and LangGraph Skill-router/cloudshrimp modes. Shares synthetic SQLite loan tools and the supplied actual Trace SDK, not replayed model answers.
- Added loopback HTTP Target adapter, `/api/bank-targets`, `/api/bank-evaluations`, and Celery dispatch. Pinned descriptors include code hash; request/session/Trace output are cross-checked. Actual turn inputs come from SDK evidence.
- Added three persisted eight-case datasets. Full live-model runs cover low/high risk, rejection, amount boundary, over-limit review, missing fields, multi-turn completion and status query.
- Verification: 18 independent-service tests and 991 backend tests including the private SDK fixture. Live results and exact run IDs are in workspace-root `BANK-TESTED-AGENTS-20260917.md`.
- Frontend source/layout unchanged in this checkpoint; existing report pages render these tasks, but create-form target selection and global Demo wording are not yet rebound.
- This implements a reference-compatible local tested Agent, not the bank's undisclosed production internals or remote factory lifecycle. See `tested-agents/README.md` for unsupported protocol fields and operational limits.

## Customer SDK integration checkpoint — 2026-09-17

- Added strict customer SDK JSONL normalization and a hash-pinned replay Target adapter using the unchanged refactor-1 runtime/Trace contracts (upstream e3760d1).
- Added explicit ChatABC/cloudshrimp request and SSE protocol translation; no customer HTTP calls or resource operations are wired yet.
- Verified the supplied private city-research archive through RunManagement, RunEngine, existing rule evaluators, and isolated SQLite. The archive is not a loan-agent acceptance test and is not copied into this repository.
- Verification: 29 focused tests including the private archive; 982 full backend tests passed. Frontend unchanged in this checkpoint.
- Still pending: exact customer loan Target/version, request-to-SDK Trace correlation, live HTTP adapter, worker/catalog composition, resource lifecycle ownership, and UI data binding. See workspace-root `CUSTOMER-AGENT-API-CONTRACT-20260917.md`.

## Local UX integration checkpoint — 2026-09-17

These changes are in the local unified-task integration worktree, not a claim of an upstream merge.

- Task identities and run/static-report associations are persisted in SQLite. Single, A/B, and stability launches save runs and their task associations atomically before dispatch.
- Stability launches support 2–20 independent runs with an identical manifest. Summary excludes failed/error/unscored runs from numerical statistics and preserves every round's status.
- Optimization reports are persisted by evidence/model/analyzer fingerprint. Analyzer v3 restricts model citations to the same Span allowlist enforced by the report domain and uses representative evidence with one bounded contract retry.
- Registered composite v1 supports all, any, and weighted scores while preserving blocking failures, errors, and review outcomes.
- Frontend task relations use server data. Reanalysis replaces the active task-to-static-report link without deleting older reports. Existing layout and the three-column tuning workbench remain.
- Verification: 953 backend tests, frontend production build, and the unified-task browser suite. Exact live run IDs and remaining boundaries are recorded in the workspace-root `INTEGRATION-20260917.md`.
- Model connection editing/team authorization still requires a choice between local single-user management and a multi-user identity/authorization system. Existing service-managed model execution is verified; there is no claim of production tenant isolation.

## Status Legend

- `[x]`: implemented and covered by the current test suite.
- `[ ]`: not implemented or not yet accepted as complete.
- Paths marked **new** do not exist yet.
- This checklist tracks the complete POC direction. Deferred production work is
  listed separately and is not required to finish the initial demo.

## Work Ownership

| Tag | Scope | Status |
|---|---|---|
| `[CODEX-EVALUATOR]` | Persistent Evaluator Catalog | Complete and integrated into `refactor-1` |
| `[CODEX-SKILL]` | Static Skill Analysis backend and API | Complete and integrated into `refactor-1` |
| `[CODEX-OPTIMIZER]` | LLM root-cause optimizer backend and API | Implemented and verified on `feature/llm-root-cause-analysis`; delivery pending |
| `[CODEX-SCHEDULE]` | One-time scheduled Evaluation Runs | Complete and uncommitted on `feature/scheduled-runs` |
| `[UNASSIGNED]` | Web pages | Not started |

## Core Foundation

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Domain models | Define Dataset, Case, Run, Trace, Result, Target, and Evaluator concepts | `src/agentgate/domain/` |
| [x] | SQLite storage | Persist the POC domain objects | `src/agentgate/storage/sqlite.py` |
| [x] | Repository contract | Isolate application workflows from storage implementations | `src/agentgate/storage/repository.py` |
| [ ] | Artifact storage | Store files, screenshots, reports, and generated outputs | `src/agentgate/storage/artifacts.py` **new** |
| [x] | Storage cleanup | Remove obsolete or empty storage code after migration | `src/agentgate/storage/` |

## Dataset

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset management | Create, edit, archive, publish, and version Datasets | `src/agentgate/application/dataset_management.py` |
| [x] | Dataset loading | Convert external data into Dataset and Case models | `src/agentgate/dataset/loader.py` |
| [x] | JSON format | Import and export complete Dataset structures | `src/agentgate/dataset/formats/json.py` |
| [x] | Excel format | Import existing single-sheet customer files | `src/agentgate/dataset/formats/xlsx.py` |
| [x] | Multi-turn Cases | Store multiple conversation turns in one Case | `src/agentgate/domain/case.py` |
| [ ] | Dataset sampling | Select reproducible smoke, regression, tagged, or risk-based subsets | `src/agentgate/dataset/sampling.py` **new**; planned after 2026-09-15 |
| [ ] | Dataset generation | Generate positive, negative, and boundary Cases from Agent metadata | `src/agentgate/dataset/generation/` **new**; planned after 2026-09-15 |
| [ ] | Public benchmarks | Import selected public evaluation datasets | `src/agentgate/dataset/benchmarks/` **new**; planned after 2026-09-15 |

## Evaluator And Result

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Rule evaluation | Evaluate routing, Tool use, state, policy, and output | `src/agentgate/evaluator/rule/` |
| [x] | Metrics | Aggregate Case Results into Run metrics | `src/agentgate/result/metrics.py` |
| [x] | Release gate | Decide whether a version passes evaluation | `src/agentgate/result/gate.py` |
| [x] | Report | Build the complete evaluation report | `src/agentgate/result/report.py` |
| [x] | Evaluator structure | Separate protocol, executor, runtime models, and Rule responsibilities | `src/agentgate/evaluator/` |
| [x] | JSON Schema Rule evaluation | Validate structured values with Draft 2020-12 structure, required-field, value, and composition keywords; allow safe local JSON Pointers; and reject invalid schemas during Run preflight for output, state, routing, and Tool-argument expectations | `src/agentgate/evaluator/rule/json_schema.py`, `src/agentgate/evaluator/rule/operators.py`, `src/agentgate/application/evaluator_management.py` |
| [x] | LLM Judge | Perform redacted case-level semantic answer-quality evaluation through configured models | `src/agentgate/evaluator/judge/` |
| [x] | OpenAI-compatible model transport | Call preconfigured public or private Chat Completions endpoints using resolved credentials | `src/agentgate/integrations/model_providers/` |
| [x] | POC Judge environment configuration | Build one optional process-level model connection from four environment variables, remain Rule-only when absent, and reject partial configuration | `src/agentgate/integrations/model_providers/environment.py` |
| [ ] | Persistent model provider configuration | Store allowlisted endpoints, managed secrets, and production credential resolution for application use | Design required before implementation |
| [ ] | Multimodal evaluation | Evaluate files, images, and other Artifacts | `src/agentgate/evaluator/judge/multimodal.py` **new**; planned after 2026-09-15 |
| [x] | Result comparison | Compare two compatible EvaluationRuns and expose the comparison API | `src/agentgate/result/comparison.py`, `src/agentgate/server/routes/comparisons.py` |

## Trace And Target Execution

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Trace model | Represent normalized Agent behavior | `src/agentgate/domain/trace.py` |
| [x] | OTel capture | Capture real demo Agent spans | `src/agentgate/integrations/observability/in_memory.py` |
| [x] | OTLP receiver | Receive external OTLP JSON traces | `src/agentgate/integrations/observability/otlp_http_receiver.py` |
| [x] | Demo Agent adapter | Execute the Loan Agent | `src/agentgate/integrations/targets/demo_loan.py` |
| [x] | Target protocol | Standardize one Case execution | `src/agentgate/run/target_protocol.py` |
| [x] | Trace redaction | Remove secrets and private data before evaluation or display | `src/agentgate/trace/redaction.py` |
| [ ] | HTTP Agent adapter | Invoke Dify, Coze, or customer Agents | `src/agentgate/integrations/targets/http_agent.py` **new** |
| [ ] | Local process adapter | Execute CLI-based Agents | `src/agentgate/integrations/targets/process_agent.py` **new** |
| [ ] | Trace replay adapter | Evaluate an existing Trace without reinvoking an Agent | `src/agentgate/integrations/targets/trace_replay.py` **new** |
| [x] | Trace cleanup | Remove obsolete Trace scaffolds after migration | `src/agentgate/trace/` |

## Run, Queue, And Scheduler

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Run Engine | Execute every Case and invoke selected Evaluators | `src/agentgate/run/engine.py` |
| [x] | Reproducible Case subset | Pin ordered Case IDs in the RunManifest and execute only that selection without changing the Dataset version | `src/agentgate/domain/run.py`, `src/agentgate/run/engine.py` |
| [x] | Worker claiming | Prevent two workers from executing the same Run | `src/agentgate/storage/sqlite.py` |
| [x] | Incremental persistence | Save each Case's Results as soon as evaluation finishes | `src/agentgate/run/engine.py` |
| [x] | Dispatcher protocol | Define whole-Run submission and cancellation through `submit(run_id)` and `cancel(run_id)` | `src/agentgate/integrations/job_dispatchers/protocol.py` |
| [x] | Dispatch workflow | Submit persisted Runs and fail dispatch errors safely | `src/agentgate/application/run_management.py` |
| [x] | Run cancellation | Atomically cancel pending/running Runs, revoke queued delivery, and cooperatively stop active execution | `src/agentgate/storage/sqlite.py`, `src/agentgate/application/run_management.py`, `src/agentgate/run/engine.py`, `src/agentgate/integrations/job_dispatchers/celery.py`, `src/agentgate/server/routes/runs.py` |
| [x] | Stale-Run recovery | Fail Runs abandoned by an expired worker | `src/agentgate/application/run_management.py` |
| [x] | Progress projection | Calculate completed Cases and Run progress from Results | `src/agentgate/application/result_reader.py` |
| [x] | Activity projection | Return queued, running, and recent terminal Runs | `src/agentgate/application/result_reader.py` |
| [x] | Celery dispatcher | Submit `run_id` through standalone Redis or Redis Cluster selected by environment configuration | `src/agentgate/integrations/job_dispatchers/celery.py`, `src/agentgate/integrations/job_dispatchers/redis_cluster_transport.py` |
| [x] | Celery worker | Load and execute the persisted Run with the same optional Judge catalog and task-local client cleanup | `src/agentgate/integrations/job_dispatchers/celery.py` |
| [x] | Scheduled Runs | Persist one-time future execution, atomically release due Runs, and expose query/cancellation through Run APIs | `src/agentgate/domain/run.py`, `src/agentgate/application/run_scheduling.py`, `src/agentgate/storage/sqlite.py`, `src/agentgate/integrations/job_dispatchers/celery.py`, `src/agentgate/server/routes/runs.py` |
| [ ] | Customer scheduler integration | Accept work from an external Java scheduler through the shared Run boundary | `src/agentgate/server/routes/runs.py` or `src/agentgate/integrations/job_dispatchers/`; planned after POC |
| [x] | Retry mechanics | Retry only classified Target infrastructure failures with bounded backoff and a fresh execution identity; never retry evaluation failures | `src/agentgate/run/retry.py`, `src/agentgate/run/engine.py`, `src/agentgate/application/run_management.py`, `src/agentgate/server/routes/runs.py` |
| [ ] | Local process management | Start, monitor, limit, and stop local Agent processes | `src/agentgate/run/process_manager.py` **new** |
| [ ] | Run Artifact collection | Register files and reports produced during execution | `src/agentgate/run/artifacts.py` **new** |
| [x] | Run cleanup | Remove legacy core, scheduler, lifecycle, model, and adapter placeholder files | `src/agentgate/run/` |

## Application And Server

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset application service | Coordinate Dataset workflows | `src/agentgate/application/dataset_management.py` |
| [x] | Run application service | Coordinate Run creation, dispatch, and execution | `src/agentgate/application/run_management.py` |
| [x] | Result reader foundation | Read persisted Runs, Results, Traces, and reports | `src/agentgate/application/result_reader.py` |
| [x] | FastAPI foundation | Expose current Dataset, Run, Result, and Trace APIs | `src/agentgate/server/` |
| [x] | Target catalog | Register, list, and resolve exact immutable Target descriptors | `src/agentgate/application/target_catalog.py` |
| [ ] | External Target metadata adapters | Read Agent and Skill metadata from Dify, Coze, or customer platforms | `src/agentgate/integrations/targets/`; planned after POC |
| [x] | Evaluator management | Persist user identities and drafts, publish immutable versions, control availability, select exact specifications, and compose supported implementations | `src/agentgate/application/evaluator_management.py`, `src/agentgate/evaluator/versioning.py`, `src/agentgate/storage/sqlite.py` |
| [x] | Evaluator Catalog API | Expose built-in and user identities, drafts, publication, exact versions, enable state, and constrained deletion | `src/agentgate/server/routes/evaluators.py` |
| [x] | Judge API/worker wiring | Create API manifests and reconstruct worker execution from identical optional Judge configuration with process/task lifecycle cleanup | `src/agentgate/application/evaluator_management.py`, `src/agentgate/server/`, `src/agentgate/integrations/job_dispatchers/celery.py` |
| [ ] | Model provider management API | Configure provider endpoints, model options, and secret references without exposing credentials | Design required before implementation |
| [x] | Skill analysis workflow and API | Resolve exact Targets, run static analysis, persist reports, review findings, and expose HTTP endpoints | `src/agentgate/application/skill_analysis.py`, `src/agentgate/server/routes/skill_analysis.py` |
| [x] | Lineage queries | Find Runs by Dataset, Case, Target, Skill, or Evaluator version and construct relationship graphs | `src/agentgate/application/lineage_queries.py`, `src/agentgate/server/routes/lineage.py` |
| [x] | Asynchronous Run API | Create a Run, dispatch it, and return `202 Accepted` | `src/agentgate/server/routes/runs.py` |
| [x] | Run activity API | Expose queue, running status, progress, and history | `src/agentgate/server/routes/runs.py` |
| [x] | Historical Run rerun API | Create and dispatch a new Run from an exact terminal Run manifest without mutating history | `src/agentgate/application/run_management.py`, `src/agentgate/server/routes/runs.py` |
| [ ] | API contract review | Finalize response models and sanitized error behavior | `src/agentgate/server/` |

## CLI

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | CLI refactor | Call the same application services used by FastAPI | `src/agentgate/cli/` |
| [x] | Dataset commands | Import, export, list, publish, and inspect Datasets | `src/agentgate/cli/dataset_commands.py` |
| [x] | Run commands | Execute Runs and inspect queue or execution status | `src/agentgate/cli/run_commands.py` |
| [x] | Result commands | Retrieve reports, metrics, failed Cases, protected Traces, and Gate conclusions | `src/agentgate/cli/result_commands.py` |
| [x] | Legacy cleanup | Remove CLI dependencies on the old Control Plane and Run core | `src/agentgate/cli/`, `src/agentgate/application/` |
| [x] | CLI tests | Verify commands through application boundaries | `tests/test_cli.py`, `tests/test_cli_*_commands.py` |

The CLI now composes the same Dataset, Run, and Result application boundaries used by
the server. Removing the remaining legacy Control Plane test callers is separate cleanup.

## Web

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset workspace foundation | Browse and edit Dataset content | `web/src/pages/DatasetWorkspace.vue` |
| [x] | Web routing | Provide Vue Router navigation for implemented pages | web/src/router/, web/src/layouts/AppLayout.vue |
| [ ] | Overview | Show Dataset and Run status statistics | `web/src/pages/OverviewPage.vue` **new** |
| [x] | Run workspace | Show lifecycle counters plus queued, running, and historical work | `web/src/pages/RunWorkspacePage.vue` |
| [x] | Progress polling | Refresh every two seconds while active work exists and stop at terminal state | `web/src/api/runs.ts`, `web/src/pages/RunWorkspacePage.vue` |
| [ ] | Result center | Browse completed and failed Runs | `web/src/pages/ResultCenterPage.vue` **new** |
| [ ] | Result detail | Show metrics, release gate, badcases, evidence, and Trace attribution | `web/src/pages/ResultDetailPage.vue` **new** |
| [ ] | Evaluator management | Configure Rule, Judge, and Hybrid Evaluators | `web/src/pages/EvaluatorWorkspacePage.vue` **new** |
| [ ] | Model provider settings | Configure provider connections and available Judge models | `web/src/pages/ModelProviderSettingsPage.vue` **new** |
| [ ] | Skill analysis | Display Skill conflicts and prompt mismatches | `web/src/pages/SkillAnalysisPage.vue` **new** |
| [ ] | Optimizer | Display failure clusters and suggestions | `web/src/pages/OptimizerPage.vue` **new** |
| [x] | Browser verification | Verify desktop and mobile workflows against Redis, Celery, FastAPI, and SQLite | `web/tests/` |

Visible Web labels remain Chinese. Source identifiers, API fields, TypeScript names,
and comments remain English.

## A/B Testing

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | A/B definition | Bind two versions of one Agent to the same Dataset and Evaluator configuration | `src/agentgate/application/ab_testing.py` |
| [x] | A/B execution | Create and independently dispatch two ordinary EvaluationRuns | `src/agentgate/application/ab_testing.py` |
| [x] | Two-Run comparison foundation | Compare compatible Runs by metrics, Cases, and failure movement | `src/agentgate/result/comparison.py`, `src/agentgate/server/routes/comparisons.py` |
| [ ] | Significance | Calculate confidence and statistical significance | `src/agentgate/result/statistics.py` **new** |
| [x] | Controlled A/B API | Select exact Evaluator versions, create the pair, and compare it later using the two returned Run IDs | `src/agentgate/server/routes/comparisons.py` |
| [ ] | A/B Web page | Display variants, differences, confidence, and winner | `web/src/pages/ComparisonPage.vue` **new** |

A/B testing composes ordinary Runs. It does not require a broad top-level
`experiment/` package for the POC. The POC persists two ordinary Runs, not an A/B
entity, and does not provide A/B history, experiment identity, or A/B lineage.

## Skill Analysis And Optimizer

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Skill analysis domain | Define static analysis findings and reports | `src/agentgate/domain/skill_analysis.py` |
| [x] | `[CODEX-SKILL]` Skill relationships | Detect overlap, conflict, duplication, and routing ambiguity through bounded pairwise LLM checks | `src/agentgate/skill_analysis/relationships.py` |
| [x] | `[CODEX-SKILL]` Persistence and review | Store immutable reports and one current human review per finding | `src/agentgate/storage/repository.py`, `src/agentgate/storage/sqlite.py` |
| [x] | `[CODEX-SKILL]` Application and API | Run analysis for exact Target descriptors and expose report and review workflows | `src/agentgate/application/skill_analysis.py`, `src/agentgate/server/routes/skill_analysis.py` |
| [ ] | Automatic invocation | Optionally run static checks during Agent creation or evaluation setup | Deferred until external Target integration is designed |
| [ ] | Prompt alignment and deterministic description checks | Compare Agent Prompt, Skill descriptions, Tools, and capability boundaries | Deferred after the simple POC |
| [x] | Optimization domain contracts | Define immutable evidence, clusters, matrix, hypotheses, suggestions, and reports | `src/agentgate/domain/optimization.py` |
| [x] | Failure clustering | Deterministically group failed Results by stable evaluation dimensions | `src/agentgate/optimizer/clustering.py` |
| [x] | Observed routing confusion matrix | Measure expected versus actual Skill routing with explicit exclusions | `src/agentgate/optimizer/confusion_matrix.py` |
| [x] | Root-cause hypotheses | Generate evidence-constrained hypotheses through bounded, redacted LLM requests and strict response validation | `src/agentgate/optimizer/root_cause.py`, `src/agentgate/optimizer/root_cause_prompt.py`, `src/agentgate/optimizer/root_cause_contract.py` |
| [x] | Reviewable suggestions | Derive targeted recommendations from validated LLM hypotheses while requiring human review | `src/agentgate/optimizer/suggestions.py` |
| [x] | Optimizer pipeline | Compose deterministic clustering and routing analysis with an injected model boundary | `src/agentgate/optimizer/pipeline.py` |
| [x] | Optimizer application and API | Load persisted Results and Traces, reuse configured model access, and expose safe provider-failure responses | `src/agentgate/application/optimization_analysis.py`, `src/agentgate/server/routes/optimizer.py` |
| [x] | Optimizer cleanup | Remove the rejected generic service wrapper | `src/agentgate/optimizer/service.py` |

Optimizer backend implementation and LLM root-cause integration are complete on
`feature/llm-root-cause-analysis` and documented in
`docs/optimizer/implementation-plan.md`. The full regression passes and the feature is
committed and pushed; review and merge remain.

## Verification And Delivery

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Current backend regression | Verify the integrated backend including LLM root-cause analysis | `tests/` - 909 passing, 1 existing warning |
| [x] | Redis/Celery integration | Verify standalone configuration plus real three-master Redis Cluster broker delivery, worker consumption, and same-slot broker keys | `tests/test_celery_dispatcher.py`, `tests/test_redis_cluster_transport.py`, `tests/storage/test_redis_cluster_queue.py`, `web/tests/`, operational smoke |
| [x] | Browser verification | Verify all currently implemented desktop and mobile workflows | `web/tests/` - 8 passing |
| [x] | Documentation | Explain setup, APIs, Redis, Celery, and demo operation | `README.md`, `web/README.md`, `docs/` |
| [ ] | Repository cleanup | Delete obsolete placeholders and compatibility code | Entire repository |
| [ ] | Demo packaging cleanup | Move standalone demo behavior out of the reusable AgentGate package if still appropriate | `src/agentgate/demo/`, `examples/` |
| [x] | Async slice regression | Run backend, frontend, and browser suites for the asynchronous vertical slice | Entire repository |
| [ ] | Delivery | Commit, push, and tag the completed refactor POC | Git repository |

## Deferred Production Capabilities

- PostgreSQL migration and high-availability Redis.
- Authentication, authorization, tenant isolation, quotas, and audit integration.
- Dependency-based evaluator short-circuiting with explicit blocked/skipped Results and
  `blocked_by_evaluator_id` provenance.
- Priority queues, tenant fairness, multiple worker pools, and resource-aware routing.
- Recurring schedules, scheduling priorities, and calendar rules.
- Immediate interruption of arbitrary blocking Target calls and persisted per-attempt
  cancellation history.
- Customer-specific Java scheduler and Agent-platform adapters.
- Production observability platform integrations and external Result callbacks.
- Automated resume or retry of partially completed Runs.
- Persisted per-attempt retry history and retry events in Traces; the POC stores only the
  successful execution Trace.
- Persisted A/B identity, pair history, and A/B-specific lineage after the POC.
- Semantic or embedding-based failure clustering.
- Persisted Optimization Reports and cross-Run history.
- Suggestion review and application lifecycle.
- Automatic regression Run creation from accepted suggestions.

### 2026-09-27 · V2 逐评估器人工标注

完成本次运行快照驱动的评估器列表、规则证据/结果/关键代码与左右联动折叠、LLM 实际请求提示词留存和历史重建标识、逐评估器评分与提示词保存。操作步骤见 docs/annotation/end-to-end-guide.md。后端全量回归 1337 passed / 35 skipped，前端 60 项测试及构建通过；规则浏览器闭环通过，LLM 使用录制模型验证，尚无本地历史 LLM 会话供真实页面验收。


### 2026-09-29 · 样本执行轨迹与完整 JSON 联动

样本详情的测评模块下方接入 TraceExplorer：左侧按父子关系展示执行节点、状态和时间条，右侧展示接口返回的完整只读 Trace JSON。点击节点展开相关折叠范围、滚动并高亮对应 Span；切换样本重置选中状态。trace-presentation 仅整理显示数据，保留原始 JSON 顺序和未知字段，处理缺失父节点、循环关系、缺失或无效时间。

验证：17 项相关单元测试、类型检查、局部 ESLint/Prettier 和生产构建通过；隔离浏览器验证覆盖折叠展开、只读、重置及窄屏，当前本地应用已有样本通过全部节点展示、JSON 完整性、点击定位和高亮检查。仅可展示接口已返回的节点，不补造缺失链路。

### 2026-10-06 · 历史标注功能恢复（隔离分支）

从 10 月 5 日遗留的 Git stash 快照恢复 V2 模板创建、会话列表与标注、评估器证据、测评集反馈及 Trace 图。恢复分支 `feature/restore-annotation-v2` 以 `refactor-1` 为起点并对齐 `integration/baibo` 的已提交进度；现有工作区的未提交 Agent 拓扑改动未纳入。数据集创建页面沿用当前已更新的行内/行外目录与图谱实现，不覆盖为旧快照。V2 模板继续保存在浏览器本地存储，旧 V1 数据使用原有存储键。

验证：前端类型检查、lint、生产构建和 75 项单元测试通过；后端全量回归 1348 passed / 35 skipped。隔离页面 `http://127.0.0.1:5198/#/annotations` 已完成行外登录、选择本地智能体与版本、创建 V2 模板、刷新后重新登录验证卡片恢复，并进入 V2 会话工作台。隔离数据库没有已完成运行，所以逐轮标注的页面闭环尚未实测。分支尚未合入 `integration/baibo`。


### 2026-10-06 · 历史改动二次核对与弹窗宽度恢复

核对来源：`recovery/annotation-v2-snapshot`（`d18301f`）、其未跟踪文件快照、当前 `integration/baibo` 提交、Git reflog 中的遗留提交，以及「记录并优化需求描述」历史会话。历史快照的 60 个已跟踪改动文件和 21 个新增文件在恢复工作树中均存在；恢复时已适配的目录、类型、存储与行内模型修复单独检查，未用旧文件覆盖新实现。`origin/goal/p1-demo` 与 `origin/integration/p1-new` 没有当前前端样式文件，本轮使用当前前端及用户历史要求恢复，不变更架构。

| 核对项 | 发现与处理 |
| --- | --- |
| 创建测评集弹窗 | 后续表单替换丢失了原 800px 样式；恢复为 `min(800px,96vw)`，内容区域保持 68vh 上限。 |
| 标注模版、详情等弹窗 | 全局 `width: min(400px,92vw) !important` 压过各组件声明宽度；改为遵循 Element Plus 的宽度变量，未声明宽度仍默认 400px，限制不超过 96vw，全屏弹窗排除普通尺寸限制。移除任务、样本向导、LLM 设计中已无必要的强制宽度补丁。 |
| 创建测评集字段 | 恢复“01 测评集名称”、名称下方单行选填描述、“02 关联智能体”，场景标签明确选填；清除残留的“数据集”页面文案和一个多余的 > 字符。 |
| 标注模版默认描述 | 恢复历史快照中“通用消息与工具评分维度，复制后可调整评分范围与标签。”，不改写用户已保存模板。 |
| Agent 目录与图谱 | 保留 10 月 6 日新实现及行内／行外路由；主工作区尚未提交的任务拓扑改动仍在原处，没有混入恢复分支。 |
| V2、Trace、样本期望、评估器证据 | 对照快照，相关新增实现和测试均存在，未发现进一步的整文件遗漏；这不替代真实模型及所有历史需求的端到端验收。 |

浏览器实测：1440px 视口下创建测评集 800px、创建 V2 模版 1080px，均按声明宽度生效；默认窄窗口下 V2 为视口的 96%，弹窗无横向溢出。名称顺序、描述单行和选填文案已检查。前端 75 项单元测试、类型检查、lint 和生产构建通过；本轮没有修改后端。代码仍位于 `feature/restore-annotation-v2` 的隔离工作树，尚未合入主工作区。


### 2026-10-06 · 验收页面加载历史测评数据

5198 页面此前使用 `/private/tmp/agentgate-annotation-restore.db`，仅含自动初始化的 1 个贷款演示测评集，无运行记录。只读核查发现原工作区 `runtime/agentgate.db` 保留 11 个测评集、21 个版本、26 个当前格式任务记录、38 次运行和 98 条 Trace。通过 SQLite backup 创建独立副本 `/Users/baibo/915-HN-AgentGate/runtime/recovery-preview/agentgate-history-20261006.db`，完整性检查为 ok，随后将 8098 验收后端的 `AGENTGATE_DB` 切到该副本。原库及此前临时库均保留；页面此后的编辑仅影响副本。

新版接口实际返回：测评集 11 条、任务记录 26 条、运行 38 条，均 HTTP 200。浏览器已确认测评集列表共 11 个；任务默认近 7 天只有 1 项，切到近 30 天后为 32 项（26 个任务以及 6 个未绑定任务的历史运行）。该切换为当前页面筛选，没有改动用户之前要求的近 7 天默认值。历史记录可继续用于 V2 与 Trace 验收，此前“隔离库没有已完成运行”的限制已解除。

另发现独立模拟环境 `runtime/agent-platform/local/agentgate.db` 中有 2 个测评集、10 个任务、12 次运行，以及旧交付快照 `delivery/2026-09-16/agentgate.db` 中有 18 个测评集、53 次运行。它们属于不同环境/旧结构，本次未混合或覆盖到主历史副本。默认启动只初始化贷款测评集和目标定义，不自动生成历史任务；平台模拟和三种贷款模式另有种子脚本。


### 2026-10-06 — 历史智能体接入关联目录

行外 localAgentDirectory 组合 8119 的三类平台模拟智能体与 API 本地目录：Loan Agent 两版本、8107 的贷款基础编排/工作流/云虾三模式，共 7 个逻辑智能体。贷款服务不可达时显示离线条目；行内仍使用 agentDirectory 和行内 token。版本选项传递真实描述符与明确执行类型，贷款云虾无需平台分支。新建任务分别提交到 platform、bank 或 demo 执行入口；测评集拓扑使用本地真实描述符；V1/V2 标注保存 source/adapter 并按历史身份匹配会话。已通过 UI 创建“接入验收 · 贷款云虾”V2 模板，匹配 12 条既有会话。

运行环境沿用独立历史副本，新增隔离队列 6398、Worker、贷款服务 8107、读取本次 SDK 输出的 Trace Server 8218。原有 8210 服务保持不动。模型复用旧工程外部环境文件，密钥未写入代码；上游 glm-5.3 请求返回 HTTP 403，三种贷款新运行诚实记录 failed，真实模型验收尚未通过，需要可用模型配置。平台模拟基础两版本、工作流及云虾两分支共 5 次运行 completed，内置 Demo 两版本共 2 次 completed，7 次成功运行均可读取新 Trace。验收结果保存在主目录 runtime/recovery-preview/local-agent-verification.json。

验证：前端 lint、typecheck、76 项单测及生产构建通过；后端 1349 passed、35 skipped。新增测试覆盖本地目录真实来源/版本、离线条目、任务名称、标注来源与登录模式隔离。当前变更保留在恢复工作树，未合并、未覆盖原工作区未提交内容。

补充页面验收：直接在“新建测评任务”选择 Loan Agent → loan-agent-v2-fixed → 高风险贷款策略评估 v1，提交“接入验收 · 页面选择 Loan Agent”。运行 1a738eda-cc31-40e4-87b8-88fb47f21d59 完成，manifest adapter_type=demo_loan，页面显示 1/1、100 分。截图保存在主目录 runtime/recovery-preview/all-local-agents.png 和 loan-history-associated.png。


### 2026-10-06 — 三种贷款智能体切换 DeepSeek v4 Pro

已使用环境中的有效 DEEPSEEK_API_KEY（不落库/不写源码）连接 https://api.deepseek.com，模型 deepseek-v4-pro，BANK_MODEL_THINKING=disabled。原 8107 服务已重启，基础编排、工作流、云虾的描述符和实际 Trace 均报告 deepseek-v4-pro。保留旧运行及旧描述符，不修改历史证据；原 glm-5.3 403 阻塞已通过本次模型切换解除。LLM 评估器连接不在本次范围内。

LiveModel 支持显式 thinking 参数并校验取值，工具消息保留 reasoning_content 以满足 DeepSeek 协议；未配置 thinking 时不发送该参数。tested-agents 全部 23 项测试通过（含三种配置、工具循环协议、JSON 输出及密钥不进入 Trace）。参考官方 Chat Completions / Thinking Mode 文档： https://api-docs.deepseek.com/api/create-chat-completion/ ，https://api-docs.deepseek.com/guides/thinking_mode/ 。

真实验收：三模式各跑 high 和 multi 两个合成样本，共 6 样本、9 轮，3 任务全部 completed、综合分均 1.0、18 项评估器结果均 pass。逐个检查新 Trace 的 trace_sdk.model=deepseek-v4-pro；高风险结果 pending_review，多轮补齐结果 approved。

- base：aec9ffe7-9e78-480b-8aa5-a49c89bb688f
- workflow：1f4c78f8-783d-4a47-916e-ce90978bcc33
- cloudshrimp：8e375007-4d9e-49de-bd1f-157bea38dd86

本机启动脚本：主目录 runtime/recovery-preview/run-bank-deepseek.py（从环境读取密钥）；验收记录 deepseek-v4-pro-verification.json，页面截图 deepseek-v4-pro-tasks.png。测评任务页搜索“DeepSeek v4 Pro 验收”即可查看三条结果和样本 Trace。上述 100 分仅代表这组规则验收样本。


### 2026-10-06 — 贷款云虾 LLM 评估器配置

复用现有 answer_quality 实现、Evaluator Catalog 版本发布、full_trajectory 证据选择及 Judge 严格 JSON 契约，未新增执行框架或修改被测智能体。创建并启用“贷款云虾 · 回答可信度与审批解释”（113ee56f-3136-4d7d-9b43-ab47dfaeea06），当前发布 v3。评分提示词定义事实一致性40%、审批原因解释30%、请求与多轮处理20%、测试边界10%，通过阈值0.85、最低置信度0.75；原因混淆最高0.79，关键事实矛盾/编造审批/真实放款最高0.49，关键证据不足转review。权重由LLM依据评分提示计算，后端目前仅持久化一个整体score，不提供独立的维度得分字段。

v1试运行发现模型把信用评分的 [redacted] 当成事实矛盾；v2明确脱敏值不属于可核验数值，不据此扣分或反推出值。后续发现“因为高风险（存在阻断标记）”被过宽解释，v3加入并列归因、括号归因、简洁正确归因等评分锚点。7类校准样例全部符合预期：原历史混淆回答与括号变体均0.79/fail，两种正确回答均1.0/pass，虚构审批及提示注入均fail，独立证据缺失review。这些是开发者构造的校准样例，尚非人工标注一致率或泛化准确率。

本地预览API/Worker的默认Judge连接已由旧GLM切换为 https://api.deepseek.com / deepseek-v4-pro，密钥只读环境 DEEPSEEK_API_KEY，通过 env:AGENTGATE_JUDGE_API_KEY 引用，不写入配置JSON。此默认连接也由当前预览的Skill分析和根因分析复用；不修改行内网关或登录Token路由。被测目标使用行外local_bank云虾，synthetic token=local。所有验收数据来自内置合成测试客户；发送前沿用工程脱敏，不解除脱敏。

配置与验收证据位于主工作区 runtime/recovery-preview/：cloudshrimp-loan-judge.json（可重建的创建请求）、cloudshrimp-loan-judge-published.json（v3快照）、cloudshrimp-judge-calibration.json（7类校准结果）。保留v1/v2任务作为校准试运行，不改历史结果。最终v3验收任务 a730b7ed-ec57-4660-b34a-e4176e025f85 使用贷款云虾测评集v1全部8个场景，并同时运行 final-state、required-tool、forbidden-tool 和本LLM评估器。

最终验收完成：a730b7ed-ec57-4660-b34a-e4176e025f85 全部8样本完成，耗时174.3秒，无执行或评估异常。8项LLM结果均留存deepseek-v4-pro真实Judge请求/响应，7通过、1失败、0复核，LLM均分89.875；阻断样本因拒绝原因混淆得到79分/fail。规则检查20通过、4不适用，无失败。页面综合分96.6包含规则分，不等于LLM均分；独立维度分数未返回，页面诚实显示“—”，样本详情“评估结论与依据”显示LLM整体分与问题证据。完整输出 cloudshrimp-judge-v3-report.json、摘要 cloudshrimp-judge-verification.json、截图 cloudshrimp-judge-v3-result.png 均保存在主目录 runtime/recovery-preview/。已通过浏览器确认自建评估器启用、最终任务8/8完成及失败样本79分原因。此次仅配置和文档变更，未改业务源码，未进行无关全量回归；现有行内目录/Token路由保持不变。


### 2026-10-06 — 修复LLM结果分数列为空

结果表曾将LLM rubric的每条标准展开成独立分数列，而Judge契约只返回评估器整体score，导致已有79分等真实评分未在主表展示。现按运行快照中的主评估器各生成一列，直接读取对应EvaluationResult.score；任务结果、样本详情评分条及CSV共用逻辑。评分区改称“评估器得分”，不虚构独立维度分数，不改变历史分数和总分算法。任务a730b7ed-ec57-4660-b34a-e4176e025f85页面已验证LLM列依次显示79/85/100/85/85/100/85/100，样本详情显示79分。7项结果逻辑测试、前端typecheck与lint通过。截图：主工作区runtime/recovery-preview/llm-score-columns-fixed.png。


### 2026-10-06 — Skill 静态分析页面接通与真实验收

复用现有 skill_analysis 职责关系分析、不可变报告、人工复核与任务关联接口，接通当前 TaskResults 的“Skill 静态分析”页签。按本次运行的精确 TargetDescriptor 分析，读取历史报告并持久关联任务；不重新执行测评用例。新建任务支持对行外本地已注册描述符预先分析并保存报告关联，切换智能体/版本/模式会清理过期结果；行内不回退到本地 Demo，运行后可按任务描述符分析。少于两个 Skill 时明确不适用。未新增目录或后端抽象。

页面展示逐对关系、模型置信度、完成数量、问题依据/建议、人工复核和原始报告，明确只覆盖职责描述重叠/冲突/重复/歧义，不表示代码安全、Prompt-Tool 一致性或实际路由准确率。云虾任务 a730b7ed-ec57-4660-b34a-e4176e025f85 已通过 DeepSeek v4 Pro 真实分析：3 Skills、3/3 比较、completed、0 findings、0 errors，三对关系均 none（模型置信度0.95）。报告 54d4b198-5a50-4ee8-9f13-ca3d94962076 已持久关联，切换页签后可重新读取。

验证：前端 lint、78 项单测、类型检查及生产构建通过；Skill 分析模型/应用/存储/API及任务关联相关后端57项测试通过。证据：主工作区 runtime/recovery-preview/cloudshrimp-skill-static-verification.json 与 cloudshrimp-skill-static-analysis.png。验收入口：任务详情 → Skill 静态分析。


### 2026-10-07 — 贷款工作流图谱区分完成

runtime.py 共用执行与导出的 StateGraph 定义，保持7个业务节点、开始/结束、10条连线及 workflow.* Trace 名称。/agents 返回 workflow topology；local_bank.py 校验节点ID、类型和连线端点后固定到描述符，异常图拒绝，不回退为工具图。

TargetStructure.vue 对工作流按有向层级展示，标注LLM/规则/工具/起止、箭头和三条条件分支。基础编排仍为 Agent → Tool（7节点/6边），云虾为 Agent → Skill → Tool（10节点/10边），工作流9节点/10边。点击节点显示职责及关联条件；循环图保留关系并提示不作线性排序。此轮只区分结构图，没有新增编辑画布或Trace到JSON联动。

本地预览8107、8098及Worker已更新。三类图谱已逐项页面验证，历史任务1f4c78f8-783d-4a47-916e-ce90978bcc33保留原图快照，行内/行外目录与token路由不变。入口：测评任务 → 新建测评任务 → 贷款智能体 · 工作流 → v1 → 智能体图谱。

验证：贷款服务29项、适配器相关133项、前端81项测试通过；前端lint、类型检查与构建通过。主工作区 runtime/recovery-preview/workflow-topology-verification.json 保存实际目录及历史快照证据；workflow-agent-topology.png 为页面截图。


### 2026-10-07 — 三类贷款智能体核心专项测评完成

按用户授权直接完成实施和验收。复用当前多轮 Case/Expectation、状态/工具/Skill 路由规则、answer_quality full_trajectory、已发布评估器和 composite(all)；新增 ExecutionPathExpectation 与 execution_path 规则实现，未扩展默认内置评估器列表，使用已发布的用户规则配置。规则逐轮检查工具顺序/次数/额外调用、完整工作流路径、真实 Skill 执行及工具祖先归属，要求成功的轮根节点和成功的执行状态；根据开始时间排序，避免完成事件顺序误判。local_bank 将真实 workflow.* / skill.* SDK spans 规范化，未构造执行证据。前端保存、JSON/Excel 导入导出保留新断言，样本编辑页展示只读明细。

基线评估：本地未能解析 goal/p1-demo 与 integration/p1-new，不能声称已比较其实现；本次采用当前恢复分支既有领域、适配器、评估器与数据集契约，新增路径能力独立于目录查询，未改变行内/行外目录和 Token 分流。真实验收在行外本地预览进行，行内依赖回归测试，未连接实际行内网关。

创建3套专项集，每套8样本、10轮：基础编排覆盖审批三分支、缺资料、多轮补齐、查询和绕过政策；工作流覆盖全部7业务节点与10条图连线（含逻辑起止边），包括完整申请、查询、缺资料/咨询短路；云虾覆盖 loan_application/application_status/general_help 三个 Skill、跨轮路由切换、禁止未注册 Skill 和工具归属。三类申请后查询样本均从实际状态核实申请编号连续。只统计这组核心场景，不代表所有输入或异常路径完整覆盖。

初次配置校验发现 tool_argument 路径应为 arguments.amount / arguments.purpose，已发布数据集v2，旧任务改名“配置校验 v1”并保留结果，未篡改历史。最终任务全部锁定v2，每个智能体各运行规则、LLM、规则＋LLM三种配置，共9任务、72样本、90轮；被测模型与48条真实 Judge 记录均为deepseek-v4-pro。全部任务 completed，无执行/评估异常、无待复核；67样本通过、5样本失败。

| 智能体 | 规则 | LLM | 规则＋LLM |
| --- | --- | --- | --- |
| 基础编排 | 8/8 | 7/8 | 8/8 |
| 工作流 | 8/8 | 7/8 | 7/8 |
| 云虾 | 8/8 | 7/8 | 7/8 |

以上为通过数。五条失败均为阻断客户回答的原因混淆，LLM给79分：正确执行拒绝，但未明确 blocked 是决定性原因。独立任务重新执行智能体，输出不同，基础编排联合任务通过不代表与LLM任务共享同一回答。联合任务使用 all 门禁，子LLM失败即整体失败；均分仍沿用现有聚合算法，云虾失败样本综合97分也显示未通过，不将高均分当作通过。

入口：测评集搜索“核心专项”；测评任务搜索“核心专项验收”。主目录 runtime/recovery-preview/loan-specialized-v1-index.json 保存3集、7个发布评估器、9任务ID（文件名历史保留，内容数据集v2）；loan-specialized-summary.json 为完整摘要；loan-specialized-coverage.json 为逐轮路径、Skill、模型与编号连续性审计；loan-core-*-results.json 为结果。create-loan-specialized.py 已同步正确参数路径。前端截图 loan-specialized-final.png。

验证：后端1380通过、35跳过（2条现存告警）；前端82项测试通过，lint、类型检查和生产构建通过（既有包体积提示）。页面核实工作流路径对照、云虾第二轮 Skill 切换、联合任务真实分数和失败门禁。临时增加的两个 Worker 在任务完成后停止，常驻预览API/Worker/贷款服务保留，未提交或合并已有恢复分支改动。


### 2026-10-07 — 核心专项测评集随源码分发

复用 demo/bootstrap.py 的启动初始化职责，新增包内 loan-core-datasets.json 保存三套最新v2合成样本（24样本30轮），无本机路径、模型连接、任务或凭据。SQLite API启动自动原子写入缺失的数据集及发布版本；已存在ID完全保留，包括归档、用户修改和后续版本。MySQL启动不自动写入测试集，未改变行内/行外智能体目录和token路由。空数据库API测试已确认原示例加三套专项集可见，重启持久化测试验证无重复、无覆盖。README补充下载和查看方法；本次未提交或推送，分发需使用包含这些变更的源码。

最终验证：后端全量1381通过、35跳过（2条既有告警）；新安装API可见性及重复启动保护6项针对性测试通过。


### 2026-10-07 — 金额审批策略用例v3

读取本地贷款测试数据库：已有5万拒绝、8万三种结果、20万通过、30万转人工记录；profiles只有test-low(720/low/未阻断)、test-high(580/high/未阻断)、test-blocked(400/high/阻断)。审批函数先判blocked拒绝，再判高风险或评分<650或amount>200000转人工，否则通过。三套核心集发布v3：保留原场景，将阻断样本改5万，新增199999/200000/200001/300000元低风险案例，每套12样本14轮。199999和200001为依据规则新增的边界输入，不声称原数据库已有记录。同步参数金额、状态和工具路径断言、源码种子及README；历史v2和既有任务结果保留。本次验证用例配置与真实决策函数，不重新执行付费模型测评。


### 2026-10-08 — 提交至 integration/baibo

用户授权将当前恢复分支成果提交并推送到远程baibo分支，实际目标为origin/integration/baibo。包含标注v2恢复、完整Trace展示、贷款图谱与Skill分析、核心专项规则与v3种子数据，以及样本详情结果栏加宽与单轮轮次目录统一。主工作区另存的EvaluationTaskForm.vue与agent-topology.ts未纳入本次提交；不包含运行数据库、依赖软链接或凭据。提交前后端1381通过/35跳过，前端82通过，贷款运行时29通过；前端lint及生产构建通过。
