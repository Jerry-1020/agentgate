# AgentGate Implementation Roadmap

> [!NOTE]
> Superseded planning record. Package ownership here is not authoritative for
> `refactor-1`; see [the architecture review ledger](../../architecture-review-ledger.md).


## Purpose

This is the project-level implementation plan. It defines delivery order, module
dependencies, required detailed plans, parallel-development boundaries, and phase
completion gates.

It does not replace module plans. Detailed plans own the domain model, behavior, API,
files, tests, and acceptance criteria for one implementation increment. Running code and
automated tests remain authoritative; `docs/progress.md` records only verified work.

## Design-First Workflow

The roadmap covers the complete POC, not only the next implementation phase.

```text
Simplified product requirements
        |
        v
Complete project roadmap
        |
        v
Detailed plan for every POC capability
        |
        v
Cross-plan contract review
        |
        v
Implementation workstreams
        |
        v
Full POC acceptance
```

Implementation dependencies do not block writing or reviewing a plan. For example,
Dataset generation depends on TargetSnapshot in code, but its detailed plan can and
should be completed before TargetSnapshot is implemented.

Do not treat completion of one or two early delivery stages as the planning objective.
The planning objective is a coherent, reviewed design for the entire POC. Delivery stages
are used later to sequence coding and integration.

## Product Boundary

AgentGate owns evaluation assets and execution:

```text
Dataset + DatasetVersion + Case
Evaluator + EvaluatorVersion
Run + RunSnapshot
Trace
Result + Metric + Gate
Experiment and optimization analysis
```

AgentGate does not own external Agent or Skill assets:

```text
External Agent Platform
  Agent + AgentVersion
  Skill + SkillVersion
            |
            v
AgentGate adapter
  external object ID
  external version ID
  immutable evaluation-time snapshot
```

Demo Agents and Skills validate AgentGate independently. They must not become the
production asset-management model.

## End-to-End Target

```text
External Agent Platform
  |
  +--> read Agent/Skill snapshot
  |          |
  |          +--> static Skill analysis
  |          +--> automatic Dataset generation
  |
  v
Dataset draft -> review -> published DatasetVersion
                                   |
EvaluatorVersion ------------------+
                                   v
                           create evaluation Run
                                   |
                           queue/scheduler adapter
                                   |
                                   v
                           execute Agent or Skill
                                   |
                                   v
                        ingest and normalize Trace
                                   |
                    +--------------+--------------+
                    v                             v
             Rule evaluators               LLM Judge
                    +--------------+--------------+
                                   |
                                   v
                      Result -> Metrics -> Gate
                                   |
                    +--------------+--------------+
                    v                             v
             Result center                 Badcase optimizer
                    +--------------+--------------+
                                   |
                                   v
                      update Case or external Agent
                                   |
                                   v
                        regression / A-B evaluation
```

## Planning Status

Plan status values:

- `recorded`: existing implemented behavior is documented;
- `drafted`: a detailed plan exists and is under review;
- `next`: the next detailed plan to write and discuss;
- `pending`: required POC plan has not been written;
- `post_poc`: intentionally outside POC acceptance.

Implementation status remains in `docs/progress.md` and must not be inferred from this
planning table.

| Capability | Detailed plan | Plan status | Implementation dependency |
| --- | --- | --- | --- |
| Evaluator kernel | `evaluator/refactor-plan.md` | recorded | none |
| Dataset and Case management | `dataset/implementation-plan.md` | drafted | evaluator contracts |
| JSON Schema/output Rule | `evaluator/implementation-plan.md` | drafted | evaluator kernel |
| External target integration | `run/external-target-plan.md` | drafted | target boundary |
| Canonical Trace ingestion | `trace/ingestion-plan.md` | drafted | Run/correlation identity |
| Instrumented Demo Agent | `run/demo-agent-plan.md` | drafted | target + Trace contracts |
| Static Skill analysis | `analysis/skill-static-analysis-plan.md` | drafted | target descriptor |
| Automatic Dataset generation | `dataset/generation-plan.md` | next | Dataset schema + target |
| Dataset import/export | `dataset/import-export-plan.md` | pending | Dataset/Case schema |
| Evaluator asset management | `evaluator/management-plan.md` | pending | evaluator domain contracts |
| Hybrid evaluator composition | `evaluator/hybrid-plan.md` | pending | Rule + LLM Judge semantics |
| Run execution lifecycle | `run/execution-lifecycle-plan.md` | pending | target + Trace contracts |
| Result center and regression | `result/result-center-plan.md` | pending | Dataset versions + Results |
| LLM Judge runtime | `evaluator/llm-judge-plan.md` | pending | Rule ordering + credentials |
| Credential management | `security/credentials-plan.md` | pending | authentication decision |
| Badcase optimizer | `optimizer/implementation-plan.md` | pending | real Results + Trace |
| A/B experiments | `experiment/ab-test-plan.md` | pending | reproducible Runs |
| Queue/scheduler | `queue/scheduler-adapter-plan.md` | pending | Run lifecycle |
| Version lineage | `lineage/implementation-plan.md` | pending | stable identities |
| Persistence and schema evolution | `storage/persistence-plan.md` | pending | stable domain identities |
| Control panel integration | `control-panel/implementation-plan.md` | pending | all POC workflows |
| Multimodal evaluation | `evaluator/multimodal-plan.md` | post_poc | artifact model + Judge |
| CI/CD integration | `control-panel/release-integration-plan.md` | post_poc | stable Gate/API |

A listed path may not exist yet. Every `pending` POC plan must be written and reviewed
before the project declares its POC design baseline complete.

## POC Design Completion Gate

Planning is complete only when:

1. every required POC capability has a detailed plan;
2. terms and ownership boundaries agree across plans;
3. shared domain contracts have one owner and compatible field semantics;
4. cross-module flows cover creation, execution, telemetry, evaluation, result correction,
   optimization, comparison, scheduling, and lineage;
5. every plan contains a file map, error rules, security limits, delivery checkpoints, and
   acceptance tests;
6. parallel work boundaries and merge order are explicit;
7. the total end-to-end POC acceptance scenario can be traced to module-level tests;
8. unresolved decisions are listed explicitly rather than hidden as “future extension.”

## Implementation Sequence After Design Baseline

### Delivery Stage 0: Verified Evaluation Kernel

Objective: establish stable contracts and one deterministic end-to-end evaluation.

Delivered baseline:

- immutable domain models and RunSnapshot hashing;
- canonical Trace model and basic OTLP/HTTP ingestion;
- deterministic Rule evaluators;
- Result, Metric, Gate, CLI, API, and Vue demo;
- risky and fixed Demo Agent versions.

Completion gate:

- Python and frontend acceptance tests pass;
- evaluator ERROR is distinct from Agent FAIL;
- a Run is reproducible from its snapshot.

Status: implemented.

### Delivery Stage 1: Evaluation Assets

Objective: replace hard-coded Cases and incomplete output validation with reusable
evaluation assets.

Parallel workstreams:

```text
Dataset/Case workstream              Evaluator workstream
  Dataset identity                     JSON Schema operator
  immutable versions                   final-output Rule evaluator
  draft/publish workflow               execution phase
  CRUD/API/editor                      validation and tests
  canonical JSON import/export
```

Detailed plans:

- `docs/dataset/implementation-plan.md`;
- `docs/dataset/import-export-plan.md`;
- `docs/evaluator/implementation-plan.md`;
- `docs/evaluator/management-plan.md`.

Completion gate:

- a user creates and publishes a Dataset through real APIs/UI;
- a Run selects a published Dataset version;
- RunSnapshot embeds immutable Dataset content;
- JSON structure and field values are deterministically evaluated;
- historical Runs cannot be changed by later Dataset edits.
- canonical JSON and Excel imports preserve multi-turn Cases and report row-level errors;
- evaluator definitions can be versioned, reused, and fixed into a RunSnapshot.

### Delivery Stage 2: Production Integration Foundation

Objective: replace Demo-only assumptions with explicit external-platform and telemetry
contracts.

#### External Target Integration

Plan: `docs/run/external-target-plan.md`.

It must define:

- Agent/Skill target type and external object/version identity;
- immutable TargetSnapshot;
- metadata/catalog and execution adapters;
- HTTP, process, Python, trace-only, and Demo implementations;
- authentication references, timeout, retry, cancellation, and errors;
- telemetry correlation IDs.

#### Canonical Trace Ingestion

Plan: `docs/trace/ingestion-plan.md`.

It must define:

- `run_id`, `case_id`, and future `turn_id` correlation;
- Trace identity and lifecycle;
- merge of multiple OTLP batches;
- span deduplication and deterministic ordering;
- late, missing, malformed, and partial telemetry;
- OTLP/HTTP and OTLP/gRPC boundaries;
- raw payload retention and canonical persistence.

#### Instrumented Demo Agent

Plan: `docs/run/demo-agent-plan.md`.

It must define:

- deterministic risky/fixed loan behavior;
- HTTP target invocation through the common adapter;
- OpenTelemetry SDK routing/tool/state/terminal spans;
- standard OTLP/HTTP protobuf export to AgentGate;
- W3C and Run/Case/Turn/invocation correlation;
- Trace completeness waiting before evaluator execution.

#### Run Execution Lifecycle

Plan: `docs/run/execution-lifecycle-plan.md`.

It must define:

- Run and CaseRun state machines;
- single-turn and multi-turn execution ownership;
- timeout, retry, cancellation, concurrency, sampling, and idempotency;
- snapshot freeze time and evaluator start conditions;
- the boundary between AgentGate execution and an external scheduler.

Completion gate:

- a non-Demo target can be selected, invoked, correlated, and evaluated;
- repeated telemetry delivery cannot duplicate or overwrite evidence;
- one Case has a deterministic canonical Trace after multiple batches.
- the Demo end-to-end path uses real OTel SDK export, not manual canonical Trace
  construction.

### Delivery Stage 3: Authoring and Debugging

Objective: support generation, static analysis, result correction, and regression.

#### Static Skill Analysis

Plan: `docs/analysis/skill-static-analysis-plan.md`.

It must define:

- input snapshot contract;
- conflict, confusion, overlap, and Prompt-alignment terms;
- deterministic and optional LLM-assisted checks;
- evidence, confidence, severity, and suggestions;
- creation-time and evaluation-time invocation;
- read-only behavior with no external asset mutation.

#### Automatic Dataset Generation

Plan: `docs/dataset/generation-plan.md`.

It must define:

- reading Prompt, Skill descriptions, tools, and I/O definitions;
- positive, negative, boundary, single-turn, and multi-turn generation;
- difficulty, tags, provenance, and deduplication;
- generation into a draft with human review before publish;
- no security-compliance category or Token estimate in current scope.

#### Result Center and Regression

Plan: `docs/result/result-center-plan.md`.

It must define:

- expected-versus-actual and Trace drill-down;
- editable difficulty and notes;
- correcting a Case from a Result;
- creation of a new Dataset draft/version;
- single-Case rerun and regression-set workflow;
- filters and confusion-matrix source data.

Completion gate:

- a developer can correct a failed Case, publish a version, and rerun it without editing
  Python or SQL;
- static analysis and generation consume real external target snapshots.

### Delivery Stage 4: Model-Based Evaluation

Objective: add LLM-as-a-Judge without weakening deterministic guarantees.

Plans:

- `docs/evaluator/llm-judge-plan.md`;
- `docs/evaluator/hybrid-plan.md`;
- `docs/security/credentials-plan.md`.

They must define:

- provider interface and endpoint shape;
- Prompt/rubric snapshots and structured Judge output;
- public/private Key references and encryption boundary;
- timeout, retry, rate limit, and redaction;
- deterministic Rule prerequisites;
- Hybrid child ordering, short-circuiting, weights, and outcome aggregation;
- malformed Judge output and ERROR behavior;
- variance, repeat judging, and reproducibility.

Completion gate:

- structural Rules run before Judge calls;
- malformed Judge output cannot become an Agent FAIL;
- secrets never appear in snapshots, Results, Traces, APIs, or logs;
- Prompt, rubric, model request, and resolved model are auditable.

### Delivery Stage 5: Optimization and Comparison

Objective: convert Results into improvement guidance and controlled version decisions.

Plans:

- `docs/optimizer/implementation-plan.md`;
- `docs/experiment/ab-test-plan.md`.

They must define:

- Badcase clustering and stable categories;
- confusion-matrix semantics;
- representative Cases and evidence-backed hypotheses;
- reviewable suggestions with no automatic Agent mutation;
- controlled variants and control-variable enforcement;
- paired comparison, significance, side-by-side differences, and winner decision.

Completion gate:

- Badcases are clustered with traceable evidence;
- route Results produce a correct confusion matrix;
- target versions are compared under identical evaluation inputs;
- optimization suggestions require human review.

### Delivery Stage 6: Scheduling, Lineage, and Operations

Objective: operate evaluation with constrained resources and auditable versions.

Plans:

- `docs/queue/scheduler-adapter-plan.md`;
- `docs/lineage/implementation-plan.md`;
- `docs/storage/persistence-plan.md`.

They must define:

- integration with the external Java scheduler;
- queued, reserved, cancelled, terminated, and retry states;
- public-resource concurrency and private-resource bypass;
- retry/cancellation ownership and idempotency;
- relationships among target, Dataset, evaluator, model, Run, Result, and experiment;
- SQLite transaction and migration rules;
- PostgreSQL migration, retention, and operational observability.

Completion gate:

- queued Runs cannot execute twice;
- cancellation/retry ownership is explicit;
- historical Results resolve every exact input/configuration version;
- production telemetry exposes queue and execution health.

### Post-POC Extensions

- file and multimodal artifact evaluation;
- public benchmark adapters;
- CI/CD release integration;
- distributed workers;
- PostgreSQL scale and retention;
- third-party evaluator/provider integrations.

Do not move these earlier unless a current acceptance gate requires them.

## Dependency Graph

```text
Evaluator kernel
   +--> JSON/output Rule -----------------------------+
   +--> Dataset/Case versions ------------------+      |
                                                |      |
Target integration -----------------------------+------+
   +--> Trace ingestion ------------------------+
   +--> Static Skill analysis                   |
   +--> Dataset generation -------------> Result center/regression
                                                |
JSON/output Rule + credentials ----------------> LLM Judge
Rule + LLM Judge ------------------------------> Hybrid evaluator
Target + Trace contracts ----------------------> Run lifecycle
Result center + Trace -------------------------> Optimizer
Reproducible Run + versions -------------------> A/B experiment
Run lifecycle ---------------------------------> Queue/scheduler
Stable identities -----------------------------> Lineage
Stable identities -----------------------------> Persistence/schema evolution
```

## Two-Person Allocation

Current allocation:

| Member | Owns | Must avoid |
| --- | --- | --- |
| Dataset member | `domain/case.py`, `case/`, Dataset persistence/API/UI | evaluator algorithms |
| Evaluator member | `domain/evaluation.py`, `evaluator/`, JSON operator/tests | Dataset persistence/API/UI |

Shared contract: `domain/expectation.py`.

Rules:

1. Each member uses a separate branch and worktree.
2. Never run two coding agents in the same worktree.
3. Commit documentation reorganization before branching.
4. Freeze or merge shared domain-contract changes before both branches depend on them.
5. Consume another module through its public contract; do not add hidden behavior there.
6. Unit tests stay with the implementation branch; cross-module tests follow integration.

Suggested allocation after Delivery Stage 1:

```text
Member A: Target integration -> static analysis -> Dataset generation support
Member B: Trace ingestion -> Result center -> LLM Judge foundation
```

Rebalance according to merge dependencies, not directory size.

## Detailed Plan Template

Every module or vertical-slice plan must contain:

### 1. Goal

- one concrete user-visible or integration outcome;
- a short end-to-end ASCII flow;
- a measurable completion statement.

### 2. Current State and Gap

- implemented and verified behavior;
- scaffold-only behavior;
- missing behavior;
- disposable or incompatible existing data.

### 3. Scope and Non-Goals

- exact increment boundaries;
- explicitly deferred features;
- no vague extensibility claim replacing a real contract.

### 4. Terms

- define overloaded words;
- distinguish identity, version, snapshot, status, outcome, error, and failure;
- avoid multiple names for one product concept.

### 5. Ownership and Dependencies

- owning module;
- consumed public contracts;
- forbidden dependency directions;
- shared files requiring coordination.

### 6. Domain and Data Model

- persisted fields;
- immutable versus editable objects;
- identity/version rules;
- serialization, hashes, and migration.

### 7. Behavior and State Transitions

- main workflow and state machine;
- deterministic ordering;
- timeout, retry, cancellation, and idempotency where applicable.

### 8. Error and Outcome Semantics

- user/configuration errors;
- external dependency failures;
- internal errors;
- measured product failures;
- retryable versus terminal behavior.

### 9. Security and Resource Limits

- credentials and redaction;
- untrusted input handling;
- network/filesystem boundaries;
- size, depth, time, concurrency, and retention limits.

### 10. API and UI

- REST, CLI, and event operations;
- request/response concepts;
- UI workflows and states;
- authorization boundary;
- no domain rules duplicated in Vue or route handlers.

### 11. File Change Map

Use:

```text
[ADD]  create
[MOD]  modify
[DEL]  delete
[KEEP] reuse without modification
```

List source, tests, Web, docs, dependencies, and migrations.

### 12. Parallel Development Boundary

- files owned by this workstream;
- files owned by another active workstream;
- shared contracts and merge order;
- branch/worktree names.

### 13. Delivery Checkpoints

- small independently testable increments;
- each checkpoint leaves the branch runnable;
- no “implement everything, then test” checkpoint.

### 14. Acceptance Tests

- unit truth tables;
- API integration;
- persistence/restart behavior;
- browser scenario when user-facing;
- failure/security cases;
- deterministic regression expectations.

### 15. Deferred Work

- explicit capabilities not implemented;
- the future plan owning each item.

## Architecture Rules

1. `domain/` contains immutable data meaning, not I/O or service algorithms.
2. Dataset/Case owns expected data; Evaluator owns judgment behavior.
3. Run owns orchestration, not Dataset, evaluator, Trace, or Result logic.
4. Trace adapters normalize provider data before evaluators consume it.
5. Result owns aggregation and Gate decisions, not evaluator execution.
6. External Agent/Skill assets remain externally owned.
7. RunSnapshot stores exact immutable evaluation content or stable external references
   plus required snapshots.
8. Published versions and historical Runs are never mutated.
9. ERROR is not Agent FAIL; configuration errors are rejected before execution.
10. Order, dependency, severity, metric weight, and Gate threshold remain separate.
11. Importers deserialize formats; they do not implement evaluator algorithms.
12. UI/API layers delegate to application services and do not duplicate domain rules.
13. Scaffolding does not count as implementation.
14. Status becomes complete only after acceptance tests pass.
15. Public docs contain no private source documents, customer names, internal requirement
    identifiers, credentials, or environment secrets.

## Documentation Rules

- `docs/README.md` is the documentation index.
- this roadmap owns cross-module sequence and dependencies;
- `docs/arch.md` owns stable architecture;
- `docs/product-requirements-zh.md` owns simplified requirements;
- `docs/capability-mapping.md` maps capabilities to ownership and verified status;
- `docs/progress.md` records tested implementation evidence;
- module directories own detailed plans and design records;
- update progress/status only after verification;
- never copy private source requirements into the repository.

## Immediate Next Actions

1. Treat the current roadmap, Dataset, Evaluator, Target, Trace, and Demo documents as
   draft design inputs, not the complete POC plan set.
2. Write `docs/dataset/generation-plan.md` next.
3. Continue through every `pending` POC plan in the table, regardless of implementation
   dependency.
4. Review shared contracts after each plan and record conflicts immediately.
5. Write `docs/control-panel/implementation-plan.md` after all backend workflow plans so
   it can compose the complete POC experience.
6. Run the POC Design Completion Gate before starting new-module implementation.
7. Existing implementation work may continue only within already reviewed plans and
   separate worktrees; it must not silently decide contracts owned by pending plans.
