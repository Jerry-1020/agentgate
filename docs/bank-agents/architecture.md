# 架构、接口与依赖

```text
浏览器 5197
  → AgentGate API 8097 → agentgate.db（任务/固定目标描述）
  → Redis 6397 → Celery Worker → LocalBankAdapter
  → 被测智能体 8107
      ├─ base：模型工具循环
      ├─ workflow：提取 → 提交 → 征信 → 决策 → 执行 → 回答
      └─ cloudshrimp：Skill 路由 → 贷款工作流 / 查询 / 咨询
           → 模型提供方 + 合成 SQLite 业务工具
           → bank.db + 客户 Trace SDK 原始 JSONL
  ← request/result + 原始 Trace 下载
  → SDK 规范化 → 规则/LLM/复合评估 → 数据库存储
  → 脱敏 Trace API、报告 API → 浏览器
```

## 源码分工

| 文件 | 责任 |
|---|---|
| `tested-agents/src/bank_agents/app.py` | 服务入口、三模式 HTTP 协议、描述与证据查询 |
| `runtime.py` | 工具循环、LangGraph 编排和 Skill 路由 |
| `model.py` | 真实 Chat Completions 调用，无 Mock fallback |
| `tools.py` / `store.py` | 合成业务规则、数据库状态、工具审计、种子用例 |
| `telemetry.py` | 请求级独立 SDK Collector 和证据落盘 |
| `src/agentgate/integrations/targets/local_bank.py` | HTTP 执行、固定指纹验证、原始结果核对 |
| `integrations/targets/bank_protocol.py` | ChatABC/云虾请求与 SSE 解析 |
| `integrations/observability/trace_sdk.py` | SDK 事件转换到 Domain Trace，不伪造未知业务状态 |
| `server/routes/bank_targets.py` | 目标发现、真实评测创建、运行模型元数据 |
| `trace/redaction.py` | 输出脱敏，保留合法 UUID 关联字段 |

## 主要接口

| 服务 | 方法与路径 | 用途 |
|---|---|---|
| 被测服务 | GET /health、/agents、/test-cases | 健康、目标描述、数据库案例 |
| 被测服务 | POST /agent-api/loan-base-v1/chatabc/init_session | 基础编排初始化 |
| 被测服务 | POST /agent-api/loan-workflow-v1/chatabc/init_session | 工作流初始化 |
| 被测服务 | POST /agent-api/{agent-id}/chatabc/chat | 基础/工作流对话 |
| 被测服务 | POST /agent-api/loan-cloudshrimp-v1/api/v1/message | 云虾 Skill 路由对话 |
| 被测服务 | GET /requests/{request_id} | 实际执行结果 |
| 被测服务 | GET /requests/{request_id}/trace | 原始 SDK JSONL |
| 被测服务 | GET /web/race_eval/workflow_trace | 工作流 Trace 查询封装 |
| AgentGate | GET /api/bank-targets | 发现并注册三个目标 |
| AgentGate | POST /api/bank-evaluations | 创建真实任务，异步执行 |
| AgentGate | GET /api/runs/{run_id}/status、/samples | 进度和已完成样本 |
| AgentGate | GET /api/runs/{run_id} | 完成报告 |
| AgentGate | GET /api/runs/{run_id}/traces/{case_id} | 规范化 Trace 脱敏视图 |
| AgentGate | GET /api/runs/{run_id}/target-descriptor | 历史任务固定版本定义 |

以两项服务运行时的 /docs 为实际请求/响应结构准则。/agents、/requests 及完整 final_state 是本地被测服务的扩展契约，不代表客户现有服务已经提供。

## 版本与依赖

被测服务与 AgentGate 使用不同 Python 环境：避免 SDK/LangGraph 与评估平台依赖互相污染。根目录与 `tested-agents/` 各自维护 Python 依赖，`frontend/package-lock.json` 锁定前端依赖。

目标描述包含模型名、提示词、工具 Schema、Skill 和实现源码摘要。任务固化描述摘要；实现变化后旧任务重跑可能被拒绝，应创建新任务，不能替换旧结果的版本来源。

本包没有提供客户完整内部源码、提示词和业务规则，不能据此宣称已经与行内生产系统完全一致。
