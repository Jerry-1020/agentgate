# Evaluator

The Evaluator capability owns versioned evaluation definitions, concrete evaluation
methods, and execution. The persistent catalog lets users configure supported methods;
it does not accept uploaded Python, dynamic imports, or arbitrary executable code.

```text
evaluator/
├── evaluator_protocol.py
├── executor.py
├── models.py
├── versioning.py
├── hybrid.py
├── rule/
└── judge/
```

## Catalog lifecycle

An `Evaluator` is one stable catalog identity. An `EvaluatorDraft` is its complete
editable definition, and publishing the draft creates an immutable, content-addressed
`EvaluatorSpec`. The first publication is version `"1"`; later publications increment
without replacing earlier versions.

Built-in identities and specifications are source-controlled, always enabled, and
read-only. They have explicit stable timestamps and are not copied into SQLite. User
identities, their one optional draft, and all published versions use the configured SQLite
or MySQL repository. A
new user Evaluator starts disabled and cannot be enabled until it has a publication.
Deleting a published user LLM Judge or LLM Group archives and disables its identity,
removing it from the catalog and preventing further edits or new Run selection.
Exact-version reads and historical execution remain available. Published Rule and Hybrid
Evaluators cannot be deleted; they can be disabled to prevent new Run selection.

`application/evaluator_management.py` coordinates identity, draft, publication, and
selection workflows. Pure draft transformations live in `evaluator/versioning.py`, while
the repository owns atomic publication and version allocation. Every API, CLI, and worker
composition supplies the same repository used for its Runs; there is no process-global
catalog instance.

## LLM evaluator groups

An `llm_group` parent owns one or more `llm_judge` children. Each child retains the existing
Judge configuration: registered model reference, System Prompt, optional User Prompt,
input selection, rubric, and pass threshold. The current UI presets are relevance,
accuracy, rationality, and conciseness; custom children use the same configuration editor.
Parent metadata includes name, description, enabled state, version, creation time, and
update time. Dates describe the catalog identity; there is no independent publication
timestamp field.

`application/llm_evaluator_groups.py` coordinates group authoring and exact-version reads.
The storage adapters atomically save the parent and all child drafts, then atomically
publish and enable the whole group. Updates use the expected parent draft ID and update
timestamp; the repository also compares the parent identity revision. A conflict leaves
all stored data intact. Discarding the draft uses the same revision protection. If the
parent has never been published, discarding deletes the entire group. Otherwise its
published versions remain available. Removing a child cleans up unpublished data but
preserves published child identities and history.

Ownership is immutable and team-scoped. Children cannot be independently selected,
adopted into another group, or modified through single-evaluator mutation APIs. Nested
groups are not supported. A parent publication pins every child version and weight;
later edits always create another publication, including a new version for each child.

`LLMGroupEvaluator` in `evaluator/hybrid.py` combines independently executed child Results
without making another model request. Positive weights sum to one. Applicable child
scores are averaged by weight; not-applicable children are excluded and remaining weights
are normalized. All children not applicable yields a not-applicable parent. A child error
produces a parent error with no total score; review propagates to the parent unless a
blocking failure takes precedence. Otherwise the aggregate score determines pass/fail
against the parent threshold. Every child's Result and Judge record is retained.

The Run manifest includes parent and child specs, but only the selected parent is a primary
evaluator for metrics. The result UI presents its total followed by expandable child
scores, weights, reasons, and model evidence. Existing `answer_quality@1` single-prompt
evaluators and `answer_quality@2` single-request rubric evaluators remain unchanged.

## Validation and execution

Publishing checks that the configured implementation ID, implementation version, and
Evaluator kind match a deployment-supported implementation. Rule configuration is empty
for the current implementations. Answer-quality Judge configuration is validated against
the process-configured provider without invoking the model. Hybrid definitions must
reference exact published Rule and Judge child versions.

When evaluator IDs are omitted, a new Run retains the default built-in set. Explicit
built-in and enabled user IDs resolve to exact specifications; user IDs use their latest
publication. Those specifications are embedded unchanged in `RunManifest`. A worker
executes the manifest snapshot and never substitutes a newer publication or consults the
current enabled state.

External Judge model access belongs in `integrations/model_providers/`. Runtime execution
and failure isolation remain in `evaluator/executor.py`.

## HTTP API

The clean-break catalog boundary is under `/api/evaluators`:

```text
GET    /api/evaluators
POST   /api/evaluators
GET    /api/evaluators/{evaluator_id}
PATCH  /api/evaluators/{evaluator_id}
DELETE /api/evaluators/{evaluator_id}
GET    /api/evaluators/{evaluator_id}/versions
GET    /api/evaluators/{evaluator_id}/versions/{version}
GET    /api/evaluators/{evaluator_id}/drafts/current
POST   /api/evaluators/{evaluator_id}/drafts
PUT    /api/evaluators/{evaluator_id}/drafts/current
DELETE /api/evaluators/{evaluator_id}/drafts/current
POST   /api/evaluators/{evaluator_id}/drafts/publish
POST   /api/evaluators/llm-groups
GET    /api/evaluators/{evaluator_id}/llm-group
PUT    /api/evaluators/{evaluator_id}/llm-group/draft
POST   /api/evaluators/{evaluator_id}/llm-group/publish
DELETE /api/evaluators/{evaluator_id}/llm-group/draft
```

The group read endpoint accepts `?version=N` for a historical parent and its pinned child
versions. Save, publish, and discard preserve the active draft revision in their request
contracts. See the [LLM persistence guide](llm-persistence-guide.md) for the user workflow.

The POC does not include persistent model-provider administration, custom evaluator code,
or catalog import/export. The catalog uses the current request's team identity for access.

The pre-refactor implementation plan is archived under
[planning history](../history/planning-v1/evaluator-implementation-plan.md). It retains
useful JSON validation and acceptance criteria but is not implementation authority.
Implemented P1 refactor records are under [P1 history](../history/p1-demo/).
