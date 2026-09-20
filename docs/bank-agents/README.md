# 三模式被测智能体：安装与端到端验收

> 2026-09-18 后端更新已纳入本次交付：数据库迁移、回归结果、升级与回退及客户工厂未完成项见 [后端更新与三端验收](upstream-sync-20260918.md)。下文的安装与验收入口继续适用；历史实测记录以对应日期为准。

交付日期：2026-09-17。本文是本次交付的操作入口，旧日期交付和旧能力清单不代表本版本状态。

## 模块和边界

| 目录 | 责任 |
|---|---|
| `frontend/` | 已有工作台与真实目标接入；本次打包不重新设计页面 |
| 仓库根目录 | AgentGate API、任务持久化、Celery 执行、规则/LLM/复合评估、Trace 规范化（原 web-nh `backend/`，已并入根目录） |
| `tested-agents/` | 独立进程：基础编排、LangGraph 工作流、LangGraph Skill 路由三模式 |
| `vendor/trace-sdk/` | 固定的客户 SDK 源码，不依赖开发者机器路径 |
| `scripts/` | 安装、启动、种子和验收 |
| `runtime/` | 本机生成的 SQLite、日志、SDK 文件；不提交 |
| `delivery/2026-09-16/` | 保留的旧历史快照；本次新测试不自动恢复它 |

被测服务执行合成贷款业务，AgentGate 负责评测；AgentGate 不启动客户工厂 Pod。模型真实调用不等于与客户生产行为完全一致。

## 环境

本次实测：macOS ARM64、Python 3.11、Node.js 22+、uv、Redis。同机本地运行；Linux 可使用同一脚本，但本次未在 Linux/Windows 验证，Windows 建议准备 WSL 后另做验收。

必须具备访问模型服务的网络和有效模型配置。被测模型需支持 OpenAI-compatible Chat Completions、tool calling 和 JSON 输出。本次实测模型为 deepseek-v3.2，其他模型需要重新验收。真实验收会调用模型并产生费用。

## 首次启动

```bash
git clone https://github.com/open-fin-sub/agentgate-web-nh.git
cd agentgate-web-nh
bash scripts/setup-bank-integration.sh
cp .env.example .env
chmod 600 .env
# 编辑 .env，取消模型配置四行注释并填写有效值；不要提交密钥。
bash scripts/start-bank-integration.sh
```

也可将配置放在仓库外：

```bash
AGENTGATE_MODEL_ENV_FILE=/absolute/path/to/private-model.env \
  bash scripts/start-bank-integration.sh
```

脚本同时启动六项服务，等待健康检查，然后调用种子脚本。数据库由 SQLite 自动创建；首次生成 3 个评测集、每集 8 条用例，共 24 条。再次启动不会覆盖同名评测集或历史记录。

这条启动路径明确复用 AgentGate 模型连接作为被测模型；不是混淆两者角色。独立模型配置及单独启动方式见 `tested-agents/README.md`。

| 服务 | 地址/作用 |
|---|---|
| 前端 | http://127.0.0.1:5197/#tasks |
| AgentGate API | http://127.0.0.1:8097/docs |
| 被测服务 | http://127.0.0.1:8107/docs |
| Redis | 127.0.0.1:6397 |
| Worker / Scheduler | 后台执行与预约任务 |

端口占用时退出，不停止已有服务。按 Ctrl+C 关闭本次脚本启动的服务。密钥只在本机读取，不需要上传。模型配置缺失、接口不可达或模型异常不会切换为 Mock。

默认仍保留 `start-macos.command` 的原工作台启动方式；完整三模式联调应使用上面的新入口。

## 人工前端验收

1. 打开“评测任务”，点击“发起评测”。
2. 分别选择基础编排、工作流、云虾，确认自动匹配该模式的数据库评测集。
3. 选择最终状态、必需工具、禁用工具三个评估器，超时 300 秒，开始评测。
4. 等待任务完成，检查 8 个样本、输入/输出、规则结果和执行 Trace。
5. 多轮补充用例应有两轮，不同 request_id、同一会话；失败结果必须保留。
6. 基础/工作流没有声明 Skill，静态分析不适用；云虾支持基于固定目标描述的模型静态分析。

当前用例预期每模式 20 项规则通过、4 项不适用；不适用不是通过：low/boundary 未配置禁用工具，missing/status 未配置必需工具。查询行为等检查覆盖仍可加强，不能据此声称全部业务检查完成。

## 自动验收（新数据库、无固定历史 ID）

保持服务运行，在第二个终端执行：

```bash
(cd frontend && npx playwright install chromium)
node scripts/accept-bank-browser.mjs
.venv/bin/python scripts/verify-bank-traces.py
```

浏览器脚本从页面创建三次真实任务，覆盖 24 个用例、27 轮交互；核对页面输入、输出和 Trace 与 API 一致。任何执行失败、规则失败或浏览器错误均以非零状态退出，不自动重跑业务操作来掩盖失败。

Trace 脚本读取本次动态任务 ID，对照平台数据库、业务数据库、SDK 原始文件及 API；检查 request/session/trace 关联、SHA256、输入输出、工具审计及模型 Span。它不修改数据库，也不启动客户原脚本。

输出位于 `runtime/bank-acceptance/`：`browser.json`、截图、`trace-verification.json`。其中可能包含模型回答和调试信息，不应直接公开上传。

旧 `frontend/tests/unified-tasks.spec.ts` 和 `bank-integration.spec.ts` 包含开发历史数据依赖，不是新机器验收入口。

## 自动化单元测试

```bash
.venv/bin/pytest -q tests
(cd tested-agents && .venv/bin/pytest -q)
(cd frontend && npm run build)
```

智能体单元测试会注入 ScriptedModel，不应当成真实模型验收。后端私有 SDK 样本测试默认跳过，提供的客户原始 JSONL 没有纳入公共仓库。

## 数据与追溯

- 平台：`runtime/agentgate.db`，保存评测集、任务、目标快照、规范化 Trace 和结果。
- 业务：`runtime/bank-agents/bank.db`，保存合成客户、会话、请求、申请、工具审计。
- 原始证据：`runtime/bank-agents/traces/bank-tested-agents/<session_id>/<trace_id>.jsonl`。
- 模型附件：相邻 `<trace_id>/spn/<event_id>.json`。
- 日志：`runtime/{api,worker,scheduler,web,bank-agents,redis}.log`。
- API 对 Trace 生成脱敏视图，不修改数据库原始证据；完整 UUID 关联字段已避免银行卡脱敏误伤。

初始化逻辑、依赖锁和代码版本用于复现；旧数据库快照不替代新执行。若需从头测试，另行克隆到新目录并停止原服务，不覆盖正在使用的数据库。

## 架构与接口

详见 [架构与接口](architecture.md)、[交付验证记录](verification.md) 和 [独立服务说明](../../tested-agents/README.md)。

## 已知边界

- 客户工厂 create/delete、身份鉴权、Pod 生命周期、文件上传尚未接入。
- 云虾 config/history/availableSkills 等字段仅支持受限子集；安全围栏并非客户实际安全检测服务。
- SSE 不是逐 token 实时流；HTTP 超时不代表已提交业务自动回滚，禁止无条件重试。
- 当前使用 test-policy-v1 合成业务规则，不连接真实征信、放款系统；并非客户完整提示词和工作流的等价复制。
- 仅监听 loopback，没有生产租户隔离；不适合直接暴露公网。跨机器/容器需要另外设计地址与权限，不是本次已验证范围。
- 前端构建仍有大 bundle 警告；部分依赖有弃用警告，不应与测试失败混淆。
