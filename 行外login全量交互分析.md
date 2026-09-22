# 行外Login全量交互分析

> 生成时间：2026-09-22 19:10–19:30（本地时间）
> 方式：Playwright 无头浏览器以真实"行外Login"页面流程驱动，抓取浏览器侧全量报文（435 条），辅以服务端日志、`/mock/evidence` 实录与同参数 curl 重放。
> 被评测任务：`39de3cc6-a498-44a7-a6a5-4db2dd49fa4f`（云虾 · 本地模拟 `agent-claw` v1.0 @ `branch-review`，abcclaw，个人空间）

---

## 一、执行结果摘要

| 项 | 值 |
|---|---|
| 任务/Run | `39de3cc6-a498-44a7-a6a5-4db2dd49fa4f`（kind=single，HTTP 202 Accepted） |
| 目标 | 云虾 · 本地模拟 `agent-claw` v1.0 @ `branch-review`（type_group=abcclaw，个人空间） |
| 评测集 | 平台模拟验收 · 文本与多轮（`d135619b-e6b0-4b49-ab75-4f10629334c3` v1，3 样本） |
| 评估器 | Final Output（规则，v1） |
| 执行结果 | **3/3 全部 pass** |
| 执行耗时 | Worker 任务 36ms（19:10:53.568 received → 53.605 succeeded） |
| 端到端时间线 | 目录选择（11:10:52.0–52.9）→ 提交（53.5）→ 完成（53.6）→ 前台展示（53.6–58.7，UTC） |

**核心结论**：

1. 行外Login 的云虾评测完全运行在**主栈**（5197/8097/6397）上，被测 Agent 为本地虚拟平台（8119 模拟对端）。
2. **trace-server（8210）与被测真实智能体（8107）全程零交互**——运行期间两者日志零新增（基线 diff 验证）。Trace 由 `PlatformAdapter`（`src/agentgate/integrations/targets/agent_platform.py:320-380`）在 Worker 进程内**内联构建**，不经任何取证链路。
3. 行内环境（8099 栈）同样零交互，两种登录模式互不影响。
4. 本次运行同时端到端验证了 `d8be322`（"fix: make external and personal-space platform submissions work end to end"）的三处修复在运行环境全部生效。

---

## 二、参与方与拓扑

```text
前台浏览器 :5197 ──直连(CORS)──> 本地虚拟平台/被测Agent :8119   ← 目录查询跨域直连
前台浏览器 :5197 ──/api 代理──> AgentGate API :8097
                                    │
                                    ├──> Redis :6397 ──> Celery Worker (unified-tasks-20260915@)
                                    └──> SQLite runtime/agentgate.db
                                         + runtime/credential.key（凭据加密主密钥，API/Worker 共享）

trace-server :8210        ✗ 零交互（属 LocalBank 链路）
被测真实智能体 :8107      ✗ 零交互（属 LocalBank 链路）
行内模拟栈 :8099/5199     ✗ 零交互
```

| 组件 | 端口 | 角色 |
|---|---|---|
| 前台（Vite dev） | 5197 | 页面、目录选择、任务提交、结果轮询；`/api` 代理至 8097 |
| AgentGate API | 8097 | 任务受理、目标核验、凭据加密、派发 |
| Redis + Celery Worker | 6397 | 任务队列与执行 |
| 被测 Agent（本地虚拟平台） | 8119 | 目录数据 + 云虾实例创建/对话/删除（确定性回声应答） |
| trace-server | 8210 | 未参与 |
| tested-agents（真实云虾） | 8107 | 未参与 |

---

## 三、全量交互报文（按时间序，UTC 11:10:52–58）

### 阶段 1：行外Login（无网络请求）

点击"行外Login"按钮 → 前端 `loginExternal()`（`frontend/src/stores/modules/auth.ts`）：`loginMode='external'`、`token=''`、`teamId=''`，**仅内存 Pinia 状态，不产生任何网络请求，不落 localStorage**。路由守卫放行进入 `#/overview`。

与行内Login 的差异：无 token 输入、无 `getTeamRole` 团队目录查询、无团队空间选择弹窗。

### 阶段 2：目录选择（浏览器 → 直连 8119，跨域 CORS）

个人空间（teamId 为空串）→ 目录查询**省略 teamId 参数** → 模拟平台返回全部智能体。

```text
GET http://127.0.0.1:8119/web/agent/agents?name=&limit=1000&page=1
  Request Headers:
    Authorization: Bearer local
    Accept: application/json
    Origin / Referer: http://127.0.0.1:5197/
  → 200
  Response Headers:
    Access-Control-Allow-Origin: http://127.0.0.1:5197    ← 模拟平台 CORS 回显
  Body:
    {"records":[
      {"id":"agent-base","name":"基础编排 · 本地模拟","teamId":"team-local","agentType":"base","arrangeType":"base"},
      {"id":"agent-workflow","name":"工作流 · 本地模拟","teamId":"team-local","agentType":"workflow","arrangeType":"workflow"},
      {"id":"agent-claw","name":"云虾 · 本地模拟","teamId":"team-local","agentType":"abcclaw","arrangeType":"abcclaw2"}],
     "total":3,"current":1,"size":1000,"pages":1}

GET http://127.0.0.1:8119/web/abcclaw/v2/branchTree?agentId=agent-claw
  → 200 {"code":"0","data":[{"branchId":"branch-main","branchName":"主分支",
          "children":[{"branchId":"branch-review","branchName":"审核分支","children":[]}]}]}

GET http://127.0.0.1:8119/web/abcclaw/v2/listVersions?agentId=agent-claw&branchId=branch-review
  → 200 {"code":"0","data":[{"agentVersion":"1.0","status":"published","branchId":"branch-review"},
                              {"agentVersion":"2.0","status":"test","branchId":"branch-review"}]}
```

时间点：agents 11:10:52.035 → branchTree 52.462 → listVersions 52.911（每次选择触发下一级联加载）。

### 阶段 3：表单预检与平台兼容性校验（浏览器 → 5197 `/api` 代理 → 8097）

```text
GET /api/datasets                              → 200（评测集列表）
GET /api/evaluators?include_disabled=true      → 200（评估器列表）
GET /api/datasets/d135619b-...                 → 200（读取样本期望 → 推荐评估器）
GET /api/datasets/d135619b-.../versions/1      → 200（提交前校验：用例仍在发布版本，
                                                   且为纯 txt 输入 —— d8be322 新增预检）
```

### 阶段 4：任务提交（浏览器 → 8097）

```text
POST http://127.0.0.1:5197/api/agent-platform/evaluations
  Headers:
    X-Agent-Platform-Token: local
    Content-Type: application/json
  Body:
    {"target":{
       "agent_id":"agent-claw",
       "type_group":"abcclaw",
       "agent_version":"1.0",
       "branch_id":"branch-review"          ← team_id 整体省略（个人空间，d8be322 修复点 1）
     },
     "dataset_id":"d135619b-e6b0-4b49-ab75-4f10629334c3",
     "dataset_version":1,
     "evaluator_ids":["final-output"],
     "max_parallel_cases":2,
     "timeout_seconds":300,
     "max_retries":0,
     "repetitions":1}

→ 202 {"code":"0","message":"success",
        "data":{"id":"39de3cc6-a498-44a7-a6a5-4db2dd49fa4f","kind":"single",
                "run_ids":["39de3cc6-a498-44a7-a6a5-4db2dd49fa4f"]}}
```

### 阶段 5：服务端目标核验与派发（8097 → 8119；同参数 curl 重放抓包）

API 侧 `submit_platform_evaluation`（`src/agentgate/application/agent_platform_evaluation.py`）执行：

1. **模拟平台能力确认**：`GET /mock/capabilities` → `{"mock":true,"protocol":"agentgate-platform-mock-v1"}`
2. **服务端二次核验目录**（防前端伪造选择；team_id=None 故**跳过 teams 校验**）：
   - `GET /web/agent/agents?name=&limit=1000&page=1`（无 teamId，带 `Authorization: Bearer local`）
   - `GET /web/abcclaw/v2/branchTree?agentId=agent-claw`
   - `GET /web/abcclaw/v2/listVersions?agentId=agent-claw&branchId=branch-review`
3. **目标描述落库**（TargetDescriptor，来源 `platform-mock-<sha256[:24]>`）
4. **凭据加密存储**：token `local` 以 `runtime/credential.key`（AES 主密钥，API 与 Worker 共享，d8be322 修复点 2）加密写入 `agentgate_api_keys`（credential_id `4bab675e-7cf3-429c-aba2-f94e3f408be0`）
5. **任务 + Run 落库**（`agentgate_evaluation_tasks` / `agentgate_runs`，manifest 含 invocation_config：`{"agent_id":"agent-claw","branch_id":"branch-review","origin":"http://127.0.0.1:8119","runtime_type":"abcclaw","simulated":true,"team_id":null,"type_group":"abcclaw"}`）
6. **Celery 派发**至 Redis 6397

### 阶段 6：执行（Worker 52169 → 8119）

```text
runtime/worker.log 实录：
  [19:10:53,568: INFO/MainProcess] Task agentgate.execute_evaluation_run[39de3cc6-...] received
  [19:10:53,605: INFO/MainProcess] Task agentgate.execute_evaluation_run[39de3cc6-...] succeeded in 0.036s: 'completed'
```

Worker 通过 `PlatformAdapter._execute` 驱动被测平台。**每个 Case 一个实例生命周期**，云虾（abcclaw）协议序列如下（报文为同参数重放实录，`/mock/evidence` 佐证）：

```text
① POST /mock/abcclaw/instances?taskId=39de3cc6-...
     Body: {"agentId":"agent-claw","agentVersion":"1.0","branchId":"branch-review"}
     → {"code":"0","message":"success","data":{"code":"0","data":{"agentName":"mock-9ec884c7..."}}}

② GET /agent-api/mock-9ec884c7.../chatabc/health_check        （循环等待就绪）
     → {"code":"0","message":"success","data":{"data":{"status":"ok"}}}

③ POST /agent-api/mock-9ec884c7.../api/v1/message             （云虾对话，每轮一次）
     Body: {"sessionId":"<uuid4hex>","custID":"mock-customer","txt":"你好",
            "agentSessionId":"","executionMode":"execute","stream":true,
            "debugTrace":true,"safeGuardrail":"ON_BLOCK",
            "config_variables":[],"appHistory":[]}
     → 200 text/event-stream:
        data: {"event": "message", "data": {"status": "completed",
              "output": "模拟回复[agent-claw|branch-review|1.0]：你好"}}

        data: {"event":"done","data":"[DONE]"}

④ GET /web/agent_endpoint/deleteAgent?agentName=mock-9ec884c7...  （finally 清理）
     → {"code":"0","message":"success","data":{"code":"0","data":{}}}
```

`/mock/evidence` 真实实录（10 事件，3 实例）：

| 实例 | 输入 | 事件 |
|---|---|---|
| mock-9ec884c7… | `你好` | create → chat → delete |
| mock-7e6b7f47… | `查询余额` | create → chat → delete |
| mock-a202a5c3… | `第一轮` + `第二轮` | create → chat ×2 → delete |

### 阶段 7：Trace 构建与存储（Worker 进程内，无外部取证）

- Trace **内联生成**：trace_id 取自 RunEngine 生成的 W3C traceparent（`uuid4().hex`），与被测平台无 ID 关系；
- 每轮对话一个 `platform.chat` span（`operation_type=turn`，attributes 含 `agentgate.turn.id`、`platform.request_id`、`platform.simulated: true`）；
- `turn_outcomes` 记录逐轮 input/output（`state` 恒为 `{}`，平台模拟无业务状态）；
- 落库 `runtime/agentgate.db`：`agentgate_traces` 3 条 + `agentgate_results` 3 条（final-output 全 pass，理由"所有适用检查均通过"）。

### 阶段 8：前台轮询与结果展示（浏览器 → 8097）

```text
GET /api/runs/39de3cc6.../status
  → running  3/3 (11:10:53.607)     ← 首轮轮询即接近完成
  → completed     (11:10:56.637)

GET /api/runs/39de3cc6.../samples   → 200（含 manifest 全量用例与逐样本结果）
GET /api/runs/39de3cc6.../traces/b39866ec-... → 200
GET /api/runs/39de3cc6.../traces/0017aa79-... → 200
GET /api/runs/39de3cc6.../traces/6d3d4dce-... → 200
  （报告页与样本详情页各加载一轮）

Trace 响应样例：
{"code":"0","data":{
   "trace_id":"3b588766244d44ff...",
   "run_id":"39de3cc6-...","case_id":"b39866ec-...",
   "spans":[{"name":"platform.chat","operation_type":"turn","status":"ok",
             "attributes":{"agentgate.turn.id":"37e68f60-...","platform.simulated":true}}],
   "turn_outcomes":{"37e68f60-...":{"input":{"txt":"你好"},
                     "output":{"output":"模拟回复[agent-claw|branch-review|1.0]：你好"},
                     "state":{}}},
   "final_output":{"output":"模拟回复[agent-claw|branch-review|1.0]：你好"},
   "final_state":{}}}
```

---

## 四、行外 vs 行内 Login 全链路对照

| 维度 | 行内Login | 行外Login（本次） |
|---|---|---|
| 运行栈 | 5199/8099/6399 模拟验收栈 | **5197/8097/6397 主栈** |
| 登录动作 | 输入 token `local-demo` → 选团队空间（本地验收团队） | 无 token，点击直接进入 |
| 目录通道 | 5199 `/web` 同源代理 → 8119 | **浏览器直连 8119（跨域，ACAO 回显 Origin）** |
| 目录查询 | getTeamRole → agents(teamId) → branchTree → listVersions | **无 getTeamRole**；agents（无 teamId=个人空间全部）→ branchTree → listVersions |
| 提交 token | `X-Agent-Platform-Token: local-demo` | `X-Agent-Platform-Token: local` |
| 提交体 team_id | `"team-local"` | **字段省略**（个人空间） |
| 目标核验 | 服务端含 teams 校验 | 服务端跳过 teams 校验 |
| Worker | platform-mock@（Redis 6399） | unified-tasks-20260915@（Redis 6397） |
| 数据库 | runtime/agent-platform/local/agentgate.db | runtime/agentgate.db |
| 凭据密钥 | runtime/agent-platform/local/credential.key | runtime/credential.key |
| **相同点** | 被测 Agent 同为 8119 模拟对端；SSE 云虾协议一致；Trace 均为 Worker 内联构建；**trace-server(8210) 与真实智能体(8107) 均不参与** | |

---

## 五、与"真实云虾"链路（LocalBank）的关系

本项目存在两条互相独立的评测执行链路：

| | 平台目标链路（本次，行内/行外 Login 均属此链路） | LocalBank 链路 |
|---|---|---|
| 入口 API | `POST /api/agent-platform/evaluations` | `POST /api/bank-evaluations` |
| 被测 Agent | 本地虚拟平台 8119（确定性回声） | tested-agents 8107 `loan-cloudshrimp-v1`（真实模型 + 客户 trace-sdk） |
| Trace 来源 | Worker 内联构建（仅对话输入/输出） | **trace-server 8210 取证**（detail + llm_requests）→ `normalize_sdk_exports` 规范化 |
| 对账机制 | 信任模拟平台信封（require_mock 能力确认） | SSE 流式答案与 SDK trace 根事件单源强对账（mode/version/request/session/output 全等） |
| 当前 UI 暴露 | 单任务表单（本报告链路） | 当前前端未暴露（仅 API/测试可达） |

若需分析 trace-server 参与的全量交互，应走 LocalBank 链路（`LocalBankAdapter`，`src/agentgate/integrations/targets/local_bank.py`）。

---

## 六、本次运行验证的修复（d8be322）

| 修复点 | 验证结果 |
|---|---|
| 表单不再发送 `team_id: ""`（个人空间省略字段） | ✅ 提交体中 team_id 字段整体省略，202 通过 |
| 主栈 `run.sh` 供给持久化 `runtime/credential.key`，API/Worker 共享 | ✅ 进程环境已确认；凭据 `4bab675e` 加密落库，Worker 成功解密执行 |
| 主栈种子平台兼容数据集（纯 txt 输入） | ✅ `平台模拟验收 · 文本与多轮`（d135619b）存在于 8097 DB，3 样本全部可执行 |

---

## 七、证据产物清单

| 文件 | 说明 |
|---|---|
| `/var/folders/.../opencode/capture-run/external/capture.json` | 浏览器侧全量抓包（435 条：请求/响应头、报文体、时间戳；Authorization 已脱敏为长度） |
| `.../external/01-welcome.png` ~ `05-sample-trace.png` | 页面流程截图（欢迎页、工作台、表单、任务报告、样本 Trace） |
| `.../external/baselines.txt` | 运行前各服务日志行数基线（用于零交互验证） |
| `runtime/worker.log`（主栈） | Celery 任务接收/成功实录 |
| `runtime/api.log`（主栈） | 8097 全部入站请求访问日志 |
| `http://127.0.0.1:8119/mock/evidence` | 被测平台操作实录（create/chat/delete ×3 实例） |
| `runtime/agentgate.db` | 任务/Run/Trace/Result/凭据落库 |

**取证方式说明**：

- 浏览器侧报文、`/mock/evidence`、worker/api 日志、数据库均为**真实实录**；
- 8097→8119 目标核验、Worker→8119 实例调用的逐字节报文为**同参数 curl 重放**（模拟平台关闭访问日志、运行中服务不可注入代理），重放实例已标记 `taskId=capture-replay` 可与真实运行区分；重放前已用 `/mock/evidence` 与代码路径核对语义一致；
- trace-server（8210）与 tested-agents（8107）的"零交互"以运行前后日志行数 diff 证明。

---

## 八、交互流程总结（一图）

```text
[前台 5197]                [API 8097]               [Redis 6397 / Worker]        [被测Agent 8119]        [trace-server 8210 / 8107]
    │ 行外Login(纯内存)          │                          │                            │                        │
    │──目录: agents(无teamId) ──────────── 直连(CORS) ────────────────────────────→ │                        │
    │←──────────────── 全部智能体(个人空间) ──────────────────────────────────────│                        │
    │──branchTree / listVersions ────────── 直连 ────────────────────────────────→ │                        │
    │ 预检: datasets/evaluators/versions → │                          │            │                        │
    │──POST /api/agent-platform/evaluations (X-Agent-Platform-Token: local) →     │                        │
    │                          │─核验: capabilities/agents/branchTree/listVersions→│                        │
    │                          │─token 加密落库 + 任务/Run 落库                    │                        │
    │                          │─Celery 派发 ──────────→ │                       │                        │
    │←── 202 {task, run_ids} ──│                          │─每Case: 实例create ──→ │                        │
    │                          │                          │←─ health_check/SSE ── │                        │
    │                          │                          │─ 对话message ×N轮 ──→ │                        │
    │                          │                          │─ deleteAgent 清理 ──→ │                        │
    │                          │                          │─内联Trace+评估+落库    │      （全程无交互）      │
    │←─ status/samples/traces 轮询 ──│                     │                       │                        │
```
