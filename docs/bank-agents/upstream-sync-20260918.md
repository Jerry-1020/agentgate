# 2026-09-18 后端更新与三端联调验收

## 结论与边界

已将 `open-fin-sub/agentgate` 默认分支 `refactor-1` 的后端增量适配到当前项目，并在保留历史数据库的副本上跑通前端 → AgentGate → 本地独立被测智能体 → 真实模型 → SDK Trace → 评测结果 → 前端。

**没有完成客户工厂的七步全流程实测。** 本次证明的是三类本地被测智能体的对话与评测闭环，不是客户 Pod 环境或行内生产实现完全一致。

- 上游基线：`e3760d16602c9423b54be968ea97839a5144d691`
- 本次上游：`33db48afcb83b0331e6e012abbd100c823268313`
- 来源：<https://github.com/open-fin-sub/agentgate/tree/33db48afcb83b0331e6e012abbd100c823268313>
- 本地集成基础：已交付版本 `03d9103bc959051794dd316236f56856186bdc90`
- 工作分支：`feature/upstream-bank-sync-20260918`
- 本次交付包含后端集成、配套脚本与测试；未改变前端源码、被测智能体源码或 vendored SDK。

## 一、客户文档调用顺序核对

依据客户提供的《行内工作流接口文档.md》及当前 `local_bank.py`，不是仅凭页面显示成功判定。

| 文档步骤 | 客户接口/约束 | 当前状态 | 本次证据或缺口 |
|---|---|---|---|
| 创建智能体 Pod | `POST /web/agent_endpoint/createAgent?taskId=…`，提交 agentId/agentVersion | 未接通客户工厂 | 当前使用预先启动的本地服务，不调用创建接口 |
| 等待 Pod 就绪 | `GET /agent-api/{agent_name}/chatabc/health_check` | 未验证客户接口 | 本地 `/health` 仅是进程健康检查，不能替代 Pod 就绪验证 |
| 建立客户端 | 使用创建结果中的动态 agent_name | 部分对应 | 本地固定三个 agent_name；HTTP 客户端刻意只允许 loopback，不是可直接换地址的生产适配器 |
| 初始化会话 | `POST /chatabc/init_session`；同一 session 只初始化一次 | 本地已验证 | 基础编排、工作流每个案例初始化一次；多轮复用会话；云虾使用自身 message 协议 |
| 上传文件 | `POST /chatabc/upload_file` multipart file/session_id | 未实现 | 当前案例仅支持 txt，chat 的 files 为空；不能声称附件流程已通过 |
| 多轮流式对话 | `POST /chatabc/chat`；按轮串行，解析 message/done/failed | 本地已验证 | 基础编排读取 content；工作流读取 end 节点 additional_kwargs.node_output.output；校验 request/session/Trace 关联 |
| 删除 Pod | `GET /web/agent_endpoint/deleteAgent?agentName=…` | 未实现客户资源清理 | 当前没有客户创建的 Pod；停止本地服务不等于调用删除接口 |

还有需要客户确认的契约差异：文档描述初始化成功字段是 `data.data.session_id`，当前本地服务/适配器使用 `resCode` 与 `data.session_id`，且本地初始化要求返回会话 ID 与请求 ID 对应。真实环境须用脱敏成功/失败响应样例确认，不应默默兼容或猜测。

需要客户提供：工厂、Pod API、健康检查、删除接口的测试地址及鉴权安全配置，允许使用的 taskId/agentId/agentVersion，以及创建/删除测试 Pod 的明确授权。还需要可上传的测试附件和上述实际响应样例。本次没有运行客户原始脚本中的远程资源或数据库管理操作。

## 二、上游改动与本地适配

| 更新 | 上游现状 | 本次处理 |
|---|---|---|
| 用户/团队 | 数据集、评估器及任务新增 user_team_id、user_id、user_name；从同名请求头读取 | 接入对应字段；补齐本地任务列表、样本、目标快照、稳定性接口的团队可见性；批量任务保留创建者；请求结束清理上下文 |
| 数据表 | 13 个核心表加 `agentgate_` 前缀 | 补充旧库迁移；同步任务关联与调优缓存外键、原始 Trace 验证及交付脚本；冲突双表状态拒绝自动合并 |
| 新列 | 上游没有完整旧库 ALTER 迁移 | 补齐身份和并发列迁移，保持原始 JSON payload、业务版本摘要、任务关联不变 |
| 并发参数 | 新增 case_max_parallel | 接入 1–32 范围校验；创建时写入实际 manifest；稳定性和重跑保留配置；本地贷款智能体仍只允许串行、零自动重试 |
| 任务 api_key | 上游接受明文并持久化，但没有执行器消费者 | 不落库、不假装生效：字段只接受 null，非空返回 422；继续采用已有服务端模型配置及密钥管理机制 |
| BJS 调度 | submit/cancel 仅记录日志，没有调度实现 | 保留上游模块供对照，但选择 BJS 时明确拒绝启动；使用已验证的 Celery/Redis |
| 日志 | 初始化会移除全部 root handler，单文件 100MB×30，记录用户姓名 | 改为不破坏既有 handler 的幂等初始化；10MB×3；不逐请求记录姓名；日志进入本副本 runtime/logs/agentgate |
| dotenv | 上游隐式加载 .env，且依赖声明未包含 dotenv | 保留现有启动脚本显式加载外部安全配置，不复制上游 .env、不引入隐式配置覆盖 |

团队请求头只是可信网关应注入的上下文，**并非登录认证或完整企业多租户安全系统**；当前本地界面不带这些请求头，沿用空团队的历史数据。不能把这些测试解释成已经完成 SSO、客户网关或所有资产的权限接入。

## 三、数据库保全

原工作目录 `agentgate-unified-tasks-2026-09-15` 未覆盖。当前运行目录为其同级 `agentgate-sync-20260918`。

`scripts/verify-upstream-migration.py` 从原库只读备份，再迁移副本，检查结果：

- 16 张已有表逐表行数、payload 摘要一致。
- 112 条历史任务全部可反序列化，结果仍可读取。
- 外键检查 0 错误。
- 三个已有 8 案例评测集直接复用，没有重新生成并覆盖原案例。
- 被测服务的 SQLite 和原始 JSONL 一并复制到新副本，本次新证据写入新副本。

完整机器检查记录：`runtime/upstream-migration.json`。旧代码、原库和原始日志仍在原目录；回退时应停止新副本并启动原副本，**不能拿已经升级的库直接交给旧代码**。回退前需另行保留本次新增任务。

## 四、实际测试结果

| 测试 | 结果 | 证据 |
|---|---|---|
| 后端全量回归 | 1033 passed / 1 skipped | 其中新增 10 项覆盖迁移、团队可见性、参数范围、未实现调度拒绝、明文密钥拒绝；skip 为原有私有 SDK fixture |
| 独立被测服务 | 19 passed | 三模式及 SDK 集成测试 |
| 前端构建 | 通过 | vue-tsc 与 vite；保留既有大 bundle 警告 |
| 浏览器真实创建三模式评测 | 3 个任务 × 8 案例完成 | `runtime/upstream-acceptance/browser.json`，未 mock 网络请求 |
| 页面输入/输出/Trace | 24 案例逐项一致；0 pageerror | 同上，含截图 |
| 页面与 API 扩展回归 | 13 passed，0 failed / flaky | `runtime/upstream-acceptance/page-tests.json`；涵盖模型配置、历史失败报告、稳定性、A/B、评估器筛选/导入/预选、XLSX 导入、预约、重跑、血缘及页面请求 |
| 原始证据一致性 | 27 轮 × 11 项 = 297 项通过 | `runtime/upstream-acceptance/trace-verification.json` |
| 真实 LLM 与复合评估 | 执行完成，无 error | `runtime/upstream-acceptance/model-services.json` |
| Skill 静态分析 | 新生成报告完成，保存并关联同一任务目标 | 同上 |
| 模型调优分析 | 新生成 3 条根因假设；再次查询复用数据库结果 | 同上；使用明确的 risky Demo 负例提供失败证据，不冒充客户失败案例 |

浏览器创建的新任务：

| 模式 | Run ID | 规则结果 |
|---|---|---|
| 基础编排 | `1a17812e-a839-4436-9758-e25a394ad96a` | 20 pass / 4 not_applicable |
| 工作流 | `23beeb30-f43a-48b4-97f1-458057690b85` | 20 pass / 4 not_applicable |
| 云虾 | `6db14d6d-92e9-4f77-a958-ef9f7553395b` | 20 pass / 4 not_applicable |

12 项不适用不是被隐藏的失败：每种模式的 low/boundary 案例没有 forbidden-tool 约束，missing/status 案例没有 required-tool 约束。规则因此没有可检查项；详见各运行 manifest 与 results。不要将不适用当作通过计数。

模型服务新增证据：

- LLM/复合评估 Run：`556b8de6-1eed-4910-8747-73512bd7ae90`。
- Answer Quality 返回 `review / 0.5`，复合返回 `review / 0.75`，最终状态规则 pass；**服务打通不代表模型判定通过**，真实结论保留。
- Skill 报告：`332f8e28-b8a3-491d-9a70-65134328ed44`，完成，1 条 finding。
- 调优负例 Run：`bdad6cb6-2885-4f8e-9f5f-e6fa0e110213`。

## 五、调用与证据存储

浏览器 `/api/bank-evaluations` 提交固定目标描述和数据集版本 → 新后端写入 `agentgate_runs`、任务关联 → Redis/Celery → `LocalBankAdapter` HTTP 调用独立服务 → 真实模型与合成业务工具 → SDK 生成原始 JSONL → 后端校验证据并规范化 → `agentgate_traces` / `agentgate_results` → 报告、Trace API → 现有前端。

| 内容 | 当前副本内的位置 |
|---|---|
| 评测数据库 | `runtime/agentgate.db` |
| 被测业务库 | `runtime/bank-agents/bank.db` |
| 原始 SDK 文件 | `runtime/bank-agents/traces/bank-tested-agents/{session_id}/{trace_id}.jsonl` |
| 原始下载接口 | 被测服务 `GET /requests/{request_id}/trace` |
| 规范化脱敏接口 | AgentGate `GET /api/runs/{run_id}/traces/{case_id}` |
| 运行日志 | `runtime/api.log`、`worker.log`、`bank-agents.log`、`logs/agentgate/` 等 |

297 项检查包含：关联 ID 脱敏后不变、原始 SHA256、下载字节一致、request/session/trace 关联、原始 root 输出与业务库一致、输入/输出/业务状态与规范化 Trace 一致、工具审计一致、非 replay 标志、模型 span 存在。保留此前 `request_id` 脱敏修复。

## 六、运行和复测

当前服务地址：前端 `http://127.0.0.1:5197/`，AgentGate `8097`，被测智能体 `8107`，Redis `6397`。一组端口只启动一个副本。

使用现有外部模型配置运行 `scripts/start-bank-integration.sh`。密钥不在本文、源码或证据摘要中。

复测入口：

- `.venv/bin/python -m pytest tests`（推荐在仓库根目录运行 pytest）
- `node scripts/accept-bank-browser.mjs runtime/upstream-acceptance`
- `.venv/bin/python scripts/verify-bank-traces.py runtime/upstream-acceptance`
- `.venv/bin/python scripts/verify-upstream-live.py`（会创建测试任务、调用付费模型）
- `frontend/node_modules/.bin/playwright test --config scripts/playwright-upstream.config.mjs`（基于迁移后的历史 fixture；本次执行的子集见运行记录）

客户工厂七步验收仍须单独进行，不能由这些本地证据替代。

## 七、本次代码交付与升级

交付目标：`open-fin-sub/agentgate-web-nh` 的 `main`。更新前 main 为 `03d9103bc959051794dd316236f56856186bdc90`，本次采用普通增量提交，不删除旧代码历史，不复制整套项目到日期目录，不强制推送。

### 影响范围

- 后端：存储表迁移、身份上下文、任务可见性和并发参数，以及原有三模式接入的兼容性适配。
- 配套脚本：数据库迁移验证、数据库种子、Trace 查询、模型服务及页面回归入口。
- 前端、`tested-agents/`、`vendor/trace-sdk/` 及依赖锁文件：与更新前版本相同，无需重复修改；克隆仓库会一并取得它们。
- 不新增上传本机 `.env`、模型密钥、依赖目录、运行数据库或原始运行日志。`delivery/2026-09-16/` 历史快照保留不变。本文列出的 `runtime/` 证据在验证机器本地生成，不是仓库自带附件；同事应使用验收脚本产生自己的记录。

### 已有部署升级

1. 先停止该部署的调度器、Worker、API 和其他写库服务，备份整个 `runtime/`、私密配置及当前 Git 提交号；不要在运行中的 SQLite 上仅复制主 db 文件而遗漏 WAL。
2. 确认工作区无未保存改动后，在 main 执行 `git pull --ff-only`，再执行 `bash scripts/setup-bank-integration.sh`。
3. 保留原外部模型配置，用 `bash scripts/start-bank-integration.sh` 启动。首次打开旧库会执行迁移；初始化种子不会覆盖同名评测集。
4. 执行本文入口文档中的浏览器与 Trace 验收。新机器直接采用入口文档的首次安装流程，不依赖开发者历史运行 ID。

### 回退

停止升级后的服务，另行保存升级期间新增数据，再在独立目录检出更新前提交，恢复与它配套的升级前数据库备份及配置。**仅回退代码不够：旧代码不能直接配合已加表名前缀的新数据库使用。** Git 历史保留的是代码，不替代本机数据库备份。

### 发布前复核（2026-09-18）

- 重新运行后端全量测试：1033 passed，1 skipped（私有 SDK fixture）。
- 重新运行被测智能体测试：19 passed；该单元测试使用脚本模型，不代替真实模型验收。
- 重新构建前端：通过，保留既有大 bundle 警告。
- 对先前真实执行产生的 27 轮证据重新检查：297 项全部通过；本次没有重新发起这 27 轮模型调用。
- 工厂创建、就绪轮询、附件上传、删除 Pod 尚未接入当前适配器；本次没有新增模拟工厂，也没有声称完成客户环境验收。
