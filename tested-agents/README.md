# 独立被测贷款智能体

本服务负责**执行被测业务**，AgentGate 负责发起评测、采集证据和评估。它不是 AgentGate 内置规则评估器，也不是把已有 JSONL 当作新执行结果的回放器。

## 三种模式

| 模式 | 执行结构 | 模型实际参与的位置 |
|---|---|---|
| `base` | 对话 → 模型工具选择 → 执行工具 → 工具结果返回模型，最多 10 轮 | 工具选择、参数提取、最终回答 |
| `workflow` | LangGraph：extract → submit → credit → decide → act → end；缺资料直接追问；查询走 lookup | 提取申请资料、生成最终回答；审批分支由明确测试规则决定 |
| `cloudshrimp` | LangGraph 路由 → 贷款申请 / 申请进度 / 通用咨询 Skill；贷款 Skill 嵌套工作流 | Skill 路由、工作流参数提取、最终回答 |

图编排采用 [LangGraph StateGraph](https://docs.langchain.com/oss/python/langgraph/quickstart)。
所有模式共用 SQLite 业务工具和客户提供的真实 `trace-sdk`。生产启动路径只实例化 `LiveModel`，没有模型不可用时返回预设成功答案的分支。单元测试中的 `ScriptedModel` 仅在测试中注入。

### 与行内参考的关系

参考了提供的接口文档和两个 Python 调用脚本的 ChatABC 初始化/对话、云虾会话、SSE 与 Trace 关联方式。参考材料没有提供行内完整智能体服务源码、工厂实现、模型提示词和真实贷款规则。因此这里是**同类架构、受支持接口子集的独立实现**，不是行内系统源码或生产行为的等价复制。

- 本服务由独立进程启动，承担本地客户侧被测目标；AgentGate 不创建工厂 Pod，也不持有被测业务工具。
- 业务规则均标记 `test-policy-v1` / `test_only=true`，仅使用合成客户。不会连接真实银行系统或放款。
- 不执行参考脚本中的远程工厂创建/删除操作。

## 启动

工作目录为仓库下 `tested-agents`。使用独立 Python 3.11 环境，避免 SDK 与 AgentGate 的依赖互相影响。

```sh
uv sync --locked --python 3.11 --extra test
```

SDK 固定来自本仓库 `vendor/trace-sdk`，不依赖开发者本机目录，也不从公共 PyPI 安装同名包。来源及文件摘要见 `vendor/trace-sdk/PROVENANCE.md`。完整联调步骤见 [交付说明](../docs/bank-agents/README.md)。

在外部环境文件配置 `BANK_MODEL_BASE_URL`、`BANK_MODEL_API_KEY`、`BANK_MODEL_NAME`（OpenAI-compatible chat completions 接口）。不要把真实密钥写进仓库：

```sh
.venv/bin/python run.py --model-env /absolute/path/to/bank-model.env
```

也可明确选择复用现有 AgentGate 模型连接。本次实测使用该方式，不代表评估模型和被测模型必须相同：

```sh
.venv/bin/python run.py --model-env /absolute/path/to/agentgate-model.env --use-agentgate-model
```

默认监听 `127.0.0.1:8107`。Swagger：`http://127.0.0.1:8107/docs`。
健康接口检查进程与配置，不会发送付费模型探测；模型连通性以实际请求为准。
服务启动必须配置模型，缺失配置直接失败。

平台另行启动（仓库根目录）：

```sh
AGENTGATE_MODEL_ENV_FILE=/absolute/path/to/agentgate-model.env .venv/bin/python scripts/start-integration.py
.venv/bin/python scripts/seed-bank-agents.py
```

种子脚本把被测服务数据库中的 24 条案例发布为 AgentGate 三个评测集，各 8 条。相同名称已存在时不覆盖已有数据；不是每次请求临时生成演示结果。

也可由一个命令启动全部本地服务（不要先另起 8107 服务）：

```sh
AGENTGATE_MODEL_ENV_FILE=/absolute/path/to/agentgate-model.env .venv/bin/python scripts/start-integration.py --with-bank-agents
```

## 接口

| 服务 | 方法 / 路径 | 用途 |
|---|---|---|
| 被测服务 8107 | GET `/agents` | 三种模式的版本、提示词、工具 Schema、Skill、模型名称、代码指纹；不返回密钥 |
| 被测服务 8107 | GET `/test-cases` | SQLite 中的 24 个合成案例 |
| 被测服务 8107 | POST `/agent-api/loan-base-v1/chatabc/init_session` | 基础模式初始化；prompt_variables 可指定唯一 custID |
| 被测服务 8107 | POST `/agent-api/loan-workflow-v1/chatabc/init_session` | 工作流初始化；config_variables 可指定唯一 custID |
| 被测服务 8107 | POST `/agent-api/{loan-base-v1或loan-workflow-v1}/chatabc/chat` | 带 session_id / txt 的对话，SSE |
| 被测服务 8107 | POST `/agent-api/loan-cloudshrimp-v1/api/v1/message` | 云虾 sessionId / custID / txt，支持流式封装或 JSON |
| 被测服务 8107 | GET `/requests/{request_id}` | 请求状态与实际结果 |
| 被测服务 8107 | GET `/requests/{request_id}/trace` | 该请求真实 SDK JSONL，未完成返回冲突 |
| 被测服务 8107 | GET `/web/race_eval/workflow_trace?request_id=...` | 本地工作流 Trace 查询封装 |
| AgentGate 8097 | GET `/api/bank-targets` | 注册并读取被测目标描述/快照 |
| AgentGate 8097 | POST `/api/bank-evaluations` | 创建持久化任务，通过现有 Celery Worker 发起真实 HTTP 执行 |

完整字段及约束见两个服务的 `/docs`。ChatABC 信封示例：

```json
{"timestamp":0,"requestId":"example-init-001","data":{"prompt_variables":[{"name":"custID","value":"test-high"}]}}
```

基础模式对话示例（先用上例初始化）：

```json
{"timestamp":0,"requestId":"example-chat-001","data":{"session_id":"example-init-001","txt":"申请8万元贷款，购买农机","files":[],"stream":true}}
```

工作流初始化将 `prompt_variables` 换成 `config_variables`。云虾请求示例：

```json
{"sessionId":"example-cloud-001","custID":"test-high","txt":"申请8万元贷款，购买农机","stream":false,"safeGuardrail":"ON_BLOCK"}
```

云虾通过 `X-Request-ID` 指定请求幂等键；不提供时服务生成 UUID。
AgentGate 启动示例（dataset_id 使用种子脚本返回的对应模式 ID）：

```json
{"mode":"workflow","dataset_id":"<dataset-id>","dataset_version":1,"evaluator_ids":["final-state","required-tool","forbidden-tool"],"timeout_seconds":180}
```

## 数据与可追溯性

- `runtime/bank-agents/bank.db`：profiles、sessions、requests、applications、tool_audit、cases。
- `runtime/bank-agents/traces/bank-tested-agents/<session>/<trace>.jsonl`：客户 SDK 文件导出；LLM 请求附件由 SDK 导出到同目录子目录。
- `runtime/agentgate.db`：评测集发布版本、目标描述与快照、任务、运行、规范化 Trace、评估结果。
- 链路：AgentGate run/case/turn → 独立 session/request → SDK trace/span → 工具审计/业务申请。
- 每请求独立 Collector，避免 SDK 全局上下文跨并发会话串写。
- Adapter 核验 request/session/mode/version、SDK 根输出与数据库结果一致；实际输入来自 SDK 根事件，不拿期望输入冒充实际输入。
- 目标快照包含提示词、工具、Skill、模型名、代码 SHA256。实现改变后旧快照执行会拒绝，需创建新任务；历史结果不会被改写。
- 同一请求 ID、同一内容完成后返回已持久化结果；冲突或运行中不重复执行。同一 session 同时仅允许一条请求。
- 模型、导出或执行失败记录为失败，不伪装成功；业务动作可能已提交，不自动重试或回滚。

## 测试规则和案例

| 客户/条件 | 期望 |
|---|---|
| test-low，信用 720，未阻断，额度 ≤ 200000 | approved |
| test-high，或信用 < 650，或额度 > 200000 | pending_review |
| test-blocked | rejected，优先于转人工 |
| 金额/用途缺失 | 追问，no_application |

三模式均覆盖：低风险、高风险、阻断拒绝、超额转人工、缺资料、多轮补充、20 万边界、未申请查询。工具层再次强制检查规则，模型不能靠提示词绕过；客户身份由服务会话绑定，不接受工具参数切换客户。

```sh
.venv/bin/python -m pytest -q
```

## 当前边界（不能当作已实现）

1. 本地联调服务仅绑定 loopback，无生产认证、租户隔离、客户工厂/Pod 管理。不能直接暴露到公网。
2. 不支持文件上传、任意工具/提示词覆盖、外部 appHistory、自定义 availableSkills、非空 agentSessionId；未支持字段拒绝，不假装已生效。
3. SSE 是协议兼容的事件输出：start 后执行，完成后发送节点/回答结果；不是逐 token 或实时节点推送。
4. Adapter 禁用自动重试，并按 Case 限时；HTTP 超时不等于远端业务被撤销。进程崩溃的 running 请求需要人工核查，暂不自动恢复。
5. 每会话保留最近 40 条对话消息及持久化 slots；每会话一笔申请。业务更新与审计不是统一事务，生产版本还需强化事务保证。
6. 客户 SDK 默认脱敏启用，但它不是完整敏感数据治理系统；仅使用合成数据，模型请求/Trace 文件仍应按敏感调试数据管理。
7. 前端创建表单已接入三个真实模型目标；内置 Demo 另行标注。每个新目标目前只有一个版本，不能做版本 A/B。基础/工作流未声明 Skill，静态职责分析不适用。
8. 规则、LLM、复合、云虾静态分析和真实失败调优均已实际调用；模型可能产生失败、待复核或非法结构，不能把“调用成功”等同“所有案例通过”。具体证据与边界见仓库根目录 `FULLSTACK-ACCEPTANCE-20260917.md`。
