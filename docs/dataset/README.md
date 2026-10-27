# Dataset and Case

Implementation sequence: [implementation-plan.md](implementation-plan.md).
Current capability status: [project progress](../project-progress.md).

Dataset and Case ownership is split by layer:

```text
domain/case.py                  Individual Case and multi-turn conversation models
domain/dataset.py               Dataset aggregate, versions, and collection invariants
dataset/                        Reusable loading, export, versioning, sampling,
                                generation, and format mechanics
application/dataset_management.py
                                User-facing Dataset/Case lifecycle orchestration
storage/                        Persistence implementations
server/ and cli/                Transport entry points
```

The pre-refactor implementation plan is archived under
[planning history](../history/planning-v1/dataset-implementation-plan.md). It retains
behavior and acceptance criteria but is not implementation authority.

Automatic generation is a separate application use case that coordinates Target metadata,
`dataset/generation/`, a model provider, and Dataset draft creation.

## Sample initialization UI

The sample editor's **初始变量** section exposes only the **工作流** tab. Users can
manually add, edit, and delete `initial_state.config_variables`; published samples
remain read-only. Other imported initial-state fields are preserved on save.

The agent, branch, and version selectors reuse the evaluation task's
`AgentTargetPicker`. External login uses `localAgentDirectory` and the `local`
token; in-bank login uses `agentDirectory` with the current session token and
team. Selection is temporary editor state and does not change the sample schema.

**自动获取变量** is enabled after a complete selection. It currently only displays
an unavailable notice: it makes no variable-fetch request and does not replace
manually entered values. Variable retrieval and result population await a future
API integration. Manual editing does not require selecting an agent.

Focused acceptance coverage is in
`frontend/tests/dataset-sample-editor.spec.ts`, including both directory routes,
selection invalidation, placeholder behavior, persistence, and read-only values.
