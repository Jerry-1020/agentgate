# Dataset Implementation Plan

Status: backend implementation complete; generation and public benchmarks remain
separate future capabilities tracked in `docs/project-progress.md`

Authority:

1. `docs/architecture.md`
2. `docs/architecture-review-ledger.md`
3. `docs/refactor-implementation-plan.md`
4. This plan

The implementation starts from `refactor-1`. Team branches are review inputs only and
are not merged wholesale.

## 1. Goal

Refactor the working P1 Dataset workflow into clear reusable and application layers:

```text
Web / CLI / API
       |
       v
application/dataset_management.py    user workflow
       |
       +----> dataset/                transformations and formats
       |
       v
storage/repository.py                persistence contract
```

The completed capability supports:

- Dataset catalog create, read, update, archive, and copy;
- one editable draft per Dataset;
- Case add, update, copy, remove, and reorder;
- immutable numbered publication;
- single-turn and multi-turn Cases;
- canonical JSON import/export;
- simple one-sheet Excel `.xlsx` import/export for business-unit data exchange;
- exact published DatasetVersion resolution for Evaluation Runs.

## 2. Terms

- **Dataset**: stable catalog identity and editable display metadata.
- **DatasetVersion**: immutable content snapshot containing ordered Cases.
- **Draft**: editable candidate for the next version; never runnable.
- **Published version**: immutable numbered DatasetVersion selectable by a Run.
- **Case**: one single-turn or multi-turn evaluation scenario.
- **Format adapter**: converts external bytes/rows to plain structured data and back.
- **Loader**: converts format output into validated domain objects.

## 3. Final File Map

```text
dataset/
├── __init__.py
├── loader.py
├── export.py
├── versioning.py
└── formats/
    ├── __init__.py
    ├── json.py
    └── xlsx.py

application/
├── __init__.py
└── dataset_management.py
```

Deferred until a real caller exists:

```text
dataset/sampling.py
dataset/generation/
```

Do not create empty placeholders for deferred capabilities.

## 4. File Changes

| Current | Action | Destination |
| --- | --- | --- |
| `case/import_export.py` | Split | `dataset/loader.py`, `dataset/export.py`, `dataset/formats/json.py` |
| none | Add | `dataset/formats/xlsx.py` |
| `case/service.py` | Split | `dataset/versioning.py`, `application/dataset_management.py` |
| `case/validation.py` | Remove after ownership migration | Domain and application layers |
| empty `case/customer/` | Remove | Recreate only for a real format |
| empty `case/public_benchmarks/` | Remove | Add only implemented benchmark integrations |
| `case/` | Remove | Replaced by `dataset/` |

No compatibility alias from `agentgate.case` is retained.

## 5. Module Contracts

### `dataset/versioning.py`

Pure immutable transformations:

- create a draft from an optional published base;
- add or replace a Case while preserving identity;
- remove a Case;
- copy a Case with a new ID;
- reorder Cases only when every Case appears once;
- build a published DatasetVersion from a draft, explicit version number, publication
  ID, and timestamp;

It performs no repository, SQL, HTTP, or global-state access. IDs and timestamps are
passed in when deterministic behavior matters. Publication rejects a non-draft source
and an empty Dataset.

### `dataset/formats/json.py`

Own the canonical external envelope and JSON byte/string conversion:

```text
format = agentgate.dataset
format_version = 1
dataset = Dataset payload
version = DatasetVersion payload
```

It checks envelope syntax and format version. It does not persist or publish.

### `dataset/formats/xlsx.py`

Implement `.xlsx` exchange with `openpyxl` using one `Cases` sheet. One row represents
one conversation Turn; repeated `case_id` values form a multi-turn Case and `turn_order`
controls conversation order. The columns are:

```text
case_id, case_name, category, difficulty, tags_json, case_notes,
initial_state_json, turn_id, turn_order, input_json, expectations_json, turn_notes
```

Only `case_id`, `case_name`, and `input_json` are required. JSON-valued cells use
canonical JSON. Import errors identify sheet, row, and column. The adapter rejects
formulas, unsafe active workbook content, malformed archives, excessive expansion, and
lossy JSON values. Dataset catalog identity is supplied by the application workflow and
is not encoded in this simple sheet.

Excel is a compatibility and bulk-exchange channel, not the primary Dataset editor.
Users perform full Case, Turn, Expectation, and draft editing through the Web UI.

### `dataset/loader.py`

- select an implemented adapter from an explicit format argument;
- parse external input;
- construct Dataset, DatasetVersion, Case, CaseTurn, and Expectation domain objects;
- reject unsupported versions and expectation kinds;
- return validation errors with stable locations.

It does not save data or decide how identity conflicts are resolved.

### `dataset/export.py`

- verify Dataset and DatasetVersion identities match;
- build the canonical export representation;
- delegate JSON or XLSX encoding;
- return bytes, media type, and suggested filename.

It does not query storage or construct HTTP responses.

### `application/dataset_management.py`

Move the current `DatasetService` workflows here. Review the class name during the file
checkpoint rather than retaining it automatically.

Responsibilities:

- coordinate catalog CRUD, archive, and copy workflows;
- resolve not-found and conflict conditions;
- call pure versioning transformations;
- determine the next published version number;
- require a nonempty valid draft before publication;
- call the repository's atomic draft-replacement operation;
- coordinate import identity policy and persistence;
- coordinate export retrieval and encoding;
- resolve an exact published DatasetVersion for Run manifest creation.

It contains no SQL, XLSX row parsing, Agent execution, or Result calculation.

## 6. Validation Ownership

```text
External syntax / workbook shape       dataset/formats/
External-to-domain conversion          dataset/loader.py
Field and aggregate invariants         domain/case.py, domain/dataset.py
Draft workflow and publication rules   application/dataset_management.py
Evaluator availability/preflight       later Run composition
SQL constraints and atomicity           storage/sqlite.py
```

Remove `case/validation.py` after migrating valid responsibilities:

- duplicate Case, Turn, and Expectation IDs belong in domain models;
- blank typed fields belong in domain models;
- nonempty publication belongs in the application workflow;
- evaluator support for `MatchesJsonSchema` belongs in Run preflight, not Dataset
  validity.

## 7. Implementation Sequence

Follow the project checkpoint rule: approve one file's name/responsibility, then review
classes/functions, implement it, and run focused tests before moving on.

1. [complete] Confirm the final Dataset file map and baseline behavior.
2. [complete] Implement `dataset/versioning.py` pure transformations.
3. [complete] Implement `dataset/formats/json.py` and preserve canonical JSON round trips.
4. [complete] Implement `dataset/loader.py` and `dataset/export.py`.
5. [complete] Add one-sheet `.xlsx` import/export in `dataset/formats/xlsx.py`.
6. [complete] Integrate XLSX parsing into `dataset/loader.py` and XLSX encoding into
   `dataset/export.py`.
7. [complete] Implement `application/dataset_management.py` and migrate all callers.
8. [complete] Integrate the approved atomic Dataset creation and draft-publication
   operations in `storage/repository.py`.
9. [complete] Remove `case/`, duplicate validation, stale imports, and empty scaffolds.
10. [complete] Update existing API/CLI imports only as required; transports and Web were
    not redesigned.
11. [complete] Run focused and complete backend regression suites.

Each checkpoint should produce a small reviewable commit when practical.

## 8. Implementation Decisions

Record the source assessment here before implementing each file. The architecture ledger
tracks only overall progress.

### `dataset/export.py`

Status: implemented; 185 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Reuse the Dataset/DatasetVersion identity check and canonical envelope fields. |
| `goal/p1-demo` | Reject the old `DatasetExport` Pydantic wrapper and combined import/export module. |
| `integration/p1-new` | Adapt its safe attachment filename normalization into a format-independent suggested filename. |
| `integration/p1-new` | Reject HTTP `Content-Disposition` handling here; it belongs in `server/`. |
| From scratch | Add the `ExportedDataset` bytes/media-type/filename output contract and explicit format dispatch. |
| Deferred | Integrate the XLSX adapter through `dataset/loader.py` and `dataset/export.py` in separate approved checkpoints. |

### `dataset/formats/xlsx.py`

Status: implemented; 195 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | No XLSX behavior or code existed to reuse. |
| `integration/p1-new` | Preserve archive limits, active-content rejection, formula protection, located errors, Case grouping, and Turn ordering. |
| `integration/p1-new` | Rewrite the implementation around one responsibility, current domain fields, and plain Case payloads. |
| `integration/p1-new` | Reject obsolete convenience fields, Dataset persistence, HTTP handling, and its three-sheet workbook. |
| From scratch | Add the current 12-column schema, current Expectation payload handling, strict JSON cells, and format-only `parse`/`dump` functions. |

### `dataset/loader.py` XLSX integration

Status: implemented; 197 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | No XLSX loading behavior or code existed to reuse. |
| `integration/p1-new` | Preserve the behavior of parsing Cases before constructing a Dataset draft. |
| `integration/p1-new` | Reuse no code directly; its parsing, domain construction, workflow, and persistence were coupled. |
| `integration/p1-new` | Reject Dataset creation, repository writes, and publication rules from the loader. |
| From scratch | Add `load_cases()` with explicit XLSX dispatch and one current-domain Pydantic `TypeAdapter`. |

### `dataset/export.py` XLSX integration

Status: implemented; 198 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | No XLSX export behavior or code existed to reuse. |
| `integration/p1-new` | Preserve Case/Turn export, the XLSX media type, and safe versioned filenames. |
| `integration/p1-new` | Reuse no code directly; workbook generation now belongs to the approved format adapter. |
| `integration/p1-new` | Reject repository lookup, publication checks, HTTP streaming, attachment headers, ETag, and cache handling. |
| Current refactor | Reuse `ExportedDataset`, identity validation, safe filename normalization, and explicit dispatch structure. |
| From scratch | Add the small XLSX encoding branch and round-trip metadata tests. |

### Atomic Dataset and Version persistence

Status: implemented; 202 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Reject separate Dataset and DatasetVersion saves for imports because they are not atomic. |
| `integration/p1-new` | Preserve the atomic Dataset-plus-draft insertion behavior and transaction shape. |
| `integration/p1-new` | Adapt the operation to the current schema, canonical serialization, and both draft and published versions. |
| `integration/p1-new` | Reject draft-only policy from the storage layer. |
| Current refactor | Reuse `_connect()` transaction handling and existing schema conventions directly. |
| From scratch | Add identity validation plus rollback, draft, and published-version tests. |

### `application/dataset_management.py`

Status: implemented; 203 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve catalog, draft, Case editing, copying, publication, lookup, and JSON exchange behavior. |
| `goal/p1-demo` | Reuse simple repository lookup and orchestration method bodies where they already fit the approved boundaries. |
| `goal/p1-demo` | Rewrite import/export composition and reject local time helpers, the old export wrapper, and duplicate Dataset validation. |
| `integration/p1-new` | Preserve atomic XLSX import into a new Dataset draft. |
| `integration/p1-new` | Reuse no application code directly because it mixes obsolete domain fields and Excel mechanics. |
| Current refactor | Reuse versioning, loading, export, shared UTC time, and repository operations directly. |
| From scratch | Add the `DatasetManagement` application class and focused JSON/XLSX workflow tests. |
| Removed | `seed()`; Demo bootstrap data does not belong to Dataset management. |

### `demo/bootstrap.py`

Status: implemented; 206 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve idempotent startup seeding of the loan demonstration Dataset and publication. |
| `goal/p1-demo` | Move the two existence checks out of `DatasetService.seed()`. |
| `integration/p1-new` | No distinct behavior or better implementation to reuse. |
| Current refactor | Reuse atomic initial persistence when storage is empty and ordinary version persistence for a partial seed. |
| From scratch | Add one bootstrap function plus empty, repeated, and partial-storage tests. |

### `control_plane/service.py` Dataset caller migration

Status: implemented; 206 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve demo bootstrap, launch-time Dataset resolution, overview counts, and Dataset summaries. |
| `goal/p1-demo` | Reuse evaluation behavior and repository queries directly. |
| `goal/p1-demo` | Replace `DatasetService` construction and reject its `seed()` call. |
| `integration/p1-new` | Reuse no code; its unrelated Target registry and legacy domain expansion are outside this migration. |
| Current refactor | Reuse `DatasetManagement` and `ensure_demo_dataset()` directly. |
| From scratch | No algorithm; synchronize the one server caller with the renamed attribute. |

The application attribute is named `dataset_management`, not `datasets`, because
`EvaluationService.datasets()` already owns the Dataset-summary query name.

### `server/routes/datasets.py` Dataset caller migration

Status: implemented; 270 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve Dataset routes and the JSON response used by the current Web UI. |
| `goal/p1-demo` | Adapt route behavior without retaining the monolithic Server module. |
| `integration/p1-new` | Adapt bounded XLSX upload and streamed download behavior only. |
| Current refactor | Reuse `DatasetManagement` JSON/XLSX import and export contracts. |
| From scratch | Add a capability router, typed dependencies, structured errors, and focused route tests. |

### `domain/case.py` recovered Turn-input invariant

Status: implemented; 208 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve the rule that every Case Turn must contain input. |
| `goal/p1-demo` | Reuse no code directly because the old check ran too late during Dataset publication. |
| `integration/p1-new` | No better behavior or implementation to reuse. |
| Current refactor | Reuse `CaseTurn` and its existing Pydantic field-validation style. |
| From scratch | Add one construction-time invariant and one focused domain test. |

### Old `case/` package removal

Status: implemented; 206 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve only behavior already migrated from `service.py` and `import_export.py` into the approved Dataset and application modules. |
| `goal/p1-demo` | Move nonempty Turn input to `domain/case.py`; retain nonempty publication in versioning/application workflows; reject duplicate validation and the obsolete JSON Schema restriction. |
| `integration/p1-new` | Retain no remaining code from its old `case/` package; useful XLSX behavior was already rewritten behind current domain contracts. |
| Current refactor | Migrate repository and multi-turn test setup from `DatasetService` to `DatasetManagement`. |
| Removed | `tests/test_case_validation.py` and the complete `src/agentgate/case/` package; no compatibility alias. |

## 9. Test Plan

### Versioning

- draft from no base starts empty;
- draft from a published base preserves Case IDs and content;
- Case edit preserves identity and Case copy creates identity;
- remove/reorder reject unknown or duplicate IDs;
- publication requires a draft and at least one Case;
- publication receives rather than calculates its version number;
- content hashes remain stable and published versions immutable.

### Formats

- JSON round trips preserve DatasetVersion equality;
- XLSX round trips preserve current Case, Turn, and Expectation payloads;
- multi-turn Cases and each implemented Expectation kind round trip;
- XLSX errors identify sheet, row, and field;
- unsupported format versions fail explicitly;
- JSON-valued spreadsheet cells are canonical and deterministic;
- malformed values fail before persistence.

### Application and Regression

- existing Dataset workflows pass through the new application module;
- identity conflicts and stale drafts fail explicitly;
- existing API and Web contracts remain unchanged;
- risky/fixed demo Runs use exact published DatasetVersions;
- all backend tests pass;
- Web typecheck/build run after required import changes;
- Playwright limitations are reported honestly if host libraries remain unavailable.

## 10. Dependency Rule

This phase may add `openpyxl`. It does not add an ORM, migration framework, Redis,
Celery, PostgreSQL driver, or object-storage SDK.

```text
domain <- dataset <- application -> storage/repository.py
```

`domain/`, `dataset/`, and `application/` never import `storage/sqlite.py` directly.

## 11. Completion Gate

Dataset work is complete when:

- `src/agentgate/case/` no longer exists;
- reusable mechanics live under `dataset/`;
- workflows live under `application/dataset_management.py`;
- JSON and XLSX import/export are real and tested;
- draft publication is immutable and uses the repository's atomic operation;
- Runs resolve exact published versions;
- backend tests and required API/Web checks pass;
- no deferred empty scaffolds are introduced.

## 测评集创建与样本分区（2026-09-26）

- 测评集描述改为名称下方的单行选填输入，与场景标签一起归入 01；取消描述、标签必填校验。
- 样本编辑移除输入字段、分类、场景标签设置。手工新样本继续使用 txt、positive、空标签；编辑已有样本保留原有元数据和结构化输入能力。
- 每轮分为基本测评项和高级测评项。基本项保留原输入/期望输出编辑器，并将输出路径与判定规则组件移入；高级项放工具、Skill，其他状态/工具参数规则和备注继续保留。ExpectationEditor 通过 kinds 限制分区可新增的种类，保存时合并另一分区，避免覆盖。
- 工具文本使用每轮独立输入缓冲，在保存时转换逗号分隔数组，避免依赖失焦事件导致漏存，并保留连续输入多个工具的能力。
- 验证：53 前端单元测试、类型检查、构建、相关 ESLint 通过。浏览器只填名称成功创建；保存并读取实际草稿，确认 txt 输入、正例、空标签、完整输出期望、output 路径正则、Skill 和必需/禁止工具均保留。

### 2026-09-26：基本测评项输出配置精简

- 基本测评项移除期望结果标题、说明、添加期望、最终输出类型、检查名称及重复的期望值输入；直接呈现输出路径和评估方式。
- 复用 ExpectationEditor 的路径、条件选择及范围/容差控件；通过 compactOutput 显式切换精简展示。其他规则编辑保持原有展示。
- 上方期望输出与所选评估方式共同生成一个 output 条件；保存和读取支持文本、JSON、正则、集合、容差、范围及字段不存在。历史额外输出检查保留在高级项中。
- 验证：前端构建、相关 ESLint 通过，58 项单元测试通过；浏览器验证新增正则样本保存与重新打开，公开 API 确认仅生成一条对应路径的输出规则；已有样本的输出、工具及 Skill 条件保存后保留。

### 2026-09-26：支持多条期望评估方式

- 基本项增加“期望评估方式”标题和底部“增加评估方式”按钮，每条配置独立选择路径和条件，可删除但至少保留一条可见配置。
- 按轮次管理输出规则列表；新增配置使用上方期望输出。已有不同期望值在未修改期望输出时保留，其他工具/状态规则不受影响。
- 浏览器验证新增第二条、保存后重新打开、删除第二条并保存、最后一条删除按钮禁用；API 核实删除生效。前端构建、ESLint、58 项单元测试通过。


## 2026-10-06 · 创建表单历史 UI 恢复

二次历史核对发现后续目录/图谱替换保留了新功能，但覆盖了创建表单的名称顺序、单行描述、测评集术语和宽度。按历史会话与 `d18301f` 恢复这些 UI 要求：名称为第一步，描述与标签选填；关联智能体为第二步；弹窗最大 800px，窄窗口不超过 96vw。保留当前行内/行外数据源及 Token 路由、Agent 图谱和会话样例逻辑。浏览器核对 1440px 视口下宽度 800px，标题、顺序、单行输入和选填提示正常。详见 `docs/project-progress.md` 二次核对记录。


## 2026-10-07 · 核心专项数据集与执行路径断言

已新增 execution_path 断言：scope=tool/workflow/skill，expected 为有序路径；Skill要求一个实际执行ID及显式allowed_tools。逐轮隔离，检查成功状态、轮根与工具祖先归属。复用现有 Case/Turn，不新增导入格式；前端类型、保存与JSON/Excel往返保留断言，SampleEditor只读展示明细。

已发布基础编排、工作流、云虾三套核心集v2，各8样本10轮；v2修正工具参数 attributes 的 arguments.amount / arguments.purpose 路径。工作流实际覆盖7节点10连线，云虾覆盖3 Skills；每套关联规则/LLM/联合三项真实任务。验收结果、边界和证据见 project-progress.md 同日专项记录。验证：后端1380通过、前端82通过、lint/typecheck/build通过。


### 2026-10-07 — 核心专项测评集随源码分发

复用 demo/bootstrap.py 的启动初始化职责，新增包内 loan-core-datasets.json 保存三套最新v2合成样本（24样本30轮），无本机路径、模型连接、任务或凭据。SQLite API启动自动原子写入缺失的数据集及发布版本；已存在ID完全保留，包括归档、用户修改和后续版本。MySQL启动不自动写入测试集，未改变行内/行外智能体目录和token路由。空数据库API测试已确认原示例加三套专项集可见，重启持久化测试验证无重复、无覆盖。README补充下载和查看方法；本次未提交或推送，分发需使用包含这些变更的源码。

最终验证：后端全量1381通过、35跳过（2条既有告警）；新安装API可见性及重复启动保护6项针对性测试通过。


### 2026-10-07 — 金额审批策略用例v3

读取本地贷款测试数据库：已有5万拒绝、8万三种结果、20万通过、30万转人工记录；profiles只有test-low(720/low/未阻断)、test-high(580/high/未阻断)、test-blocked(400/high/阻断)。审批函数先判blocked拒绝，再判高风险或评分<650或amount>200000转人工，否则通过。三套核心集发布v3：保留原场景，将阻断样本改5万，新增199999/200000/200001/300000元低风险案例，每套12样本14轮。199999和200001为依据规则新增的边界输入，不声称原数据库已有记录。同步参数金额、状态和工具路径断言、源码种子及README；历史v2和既有任务结果保留。本次验证用例配置与真实决策函数，不重新执行付费模型测评。
