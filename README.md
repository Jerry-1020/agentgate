# AgentGate

AgentGate 是智能体测评工作台，支持版本化测评集、规则/LLM/复合评估、人工标注、A/B 对比与执行轨迹。工程附带基础编排、工作流和云虾三种合成贷款智能体。

## 新机器快速开始

需要 Python 3.11、uv、Node.js 22.12 或更高版本、npm、Redis。完整启动已在 macOS ARM64 实测；Linux 尚未实测，Windows 请在 WSL 中安装这些依赖。真实模型需支持 OpenAI-compatible Chat Completions 和工具调用。

```bash
git clone --branch integration/baibo https://github.com/open-fin-sub/agentgate.git
cd agentgate
bash scripts/setup-bank-integration.sh
cp .env.example .env
chmod 600 .env
```

在 `.env` 中取消以下配置项的注释并填入自己的模型连接，不要上传密钥：

```dotenv
AGENTGATE_JUDGE_TRANSPORT=api
AGENTGATE_JUDGE_PROVIDER_ID=openai-compatible
AGENTGATE_JUDGE_BASE_URL=https://provider.example/v1
AGENTGATE_JUDGE_API_KEY=your-api-key
AGENTGATE_JUDGE_MODEL_ID=your-model-id
```

模型地址不含 `/chat/completions`。三种贷款智能体默认复用这套连接；需要单独的被测模型时填写 `BANK_MODEL_BASE_URL`、`BANK_MODEL_API_KEY`、`BANK_MODEL_NAME`。DeepSeek v4 Pro 可设 `BANK_MODEL_THINKING=disabled`，具体模型可用性取决于自己的账号。

```bash
bash scripts/start-bank-integration.sh
```

打开 [工作台](http://127.0.0.1:5197/)，选择 **行外 Login**。启动器运行前端、API、Redis、执行 Worker、Scheduler、本地智能体目录、贷款服务和 Trace Server，共八项服务；Ctrl+C 停止本次启动的进程，保留数据。缺少模型配置时会报错，不会回退为模拟模型。

| 服务 | 默认端口 |
|---|---|
| 前端 | 5197 |
| API | 8097 |
| Redis | 6397 |
| 本地智能体目录 | 8119 |
| 贷款智能体服务 | 8107 |
| Trace Server | 8210 |

端口占用会退出，不会关闭别人的服务。可用 `bash scripts/start-bank-integration.sh --port-offset 1000` 同时偏移全部端口。前端独立开发的默认端口是 5198、代理 8098；完整启动器会显式设置为上表端口。启动器统一使用自己启动的 Redis，不使用 `.env` 中的远程 Redis 地址。

配置可放在仓库外：`AGENTGATE_MODEL_ENV_FILE=/absolute/path/private.env bash scripts/start-bank-integration.sh`。仅查看页面及规则配置而不执行真实贷款测评时，可以用 `.venv/bin/python scripts/start-integration.py --no-browser`；不配置 Judge 时仅初始化专项路径规则。

## 下载后自带哪些数据

- **3 套核心专项测评集**：v3，每套 12 个样本、14 轮，共 36 个样本、42 轮。分别检查工具与审批分支、完整工作流路径、Skill 路由与实际调用。
- **7 个专项评估器**：1 个执行路径规则、3 个 LLM、3 个规则＋LLM。完整模型配置存在时，启动器自动发布，使用接收方自己的模型；已有配置和用户编辑不会被覆盖。
- **9 个历史验收任务的结果快照**：旧 v2、DeepSeek v4 Pro，72 次样本执行，67 通过、5 失败。打开 [历史报告](examples/loan-core/history/index.html)，或查看 [JSON 和说明](examples/loan-core/README.md)。历史文件不会伪装成本机新执行的任务。

在页面“测评集”搜索“核心专项”，新建任务即可选择专项评估器。也可一次创建三种智能体 × 三种评估方式共 9 个新任务（会真实调用模型并产生费用）：

```bash
.venv/bin/python scripts/run-loan-core-evaluations.py
# 快速连通性验收：每个任务只运行一个低风险样本
.venv/bin/python scripts/run-loan-core-evaluations.py --smoke
```

新任务可以在页面查看；脚本保存任务 ID 和结果至 `runtime/loan-core-acceptance/`。连接性验收不等同于全量业务通过，失败和待复核结果应按页面证据处理。

## 数据保存和备份

测评集/评估器定义在 `src/agentgate/demo/loan-core-*.json`，历史只读报告在 `examples/loan-core/history/`，随源码分发。运行后新建数据默认存储在 `runtime/agentgate.db`；贷款业务数据库、SDK 轨迹在 `runtime/bank-agents/`。智能体通过认证HTTP上传JSONL事件及模型请求附件；Trace Server独立保存到 `runtime/trace-server/received/`，查询不读取发送端目录。

启动器首次生成 `runtime/credential.key`（仅当前用户可读），API 和 Worker 共享用于加密密钥库；若手动指定 `AGENTGATE_API_KEY_ENCRYPTION_KEY`，请自己保存该值。备份前停止服务，完整备份 `runtime/` 并妥善保管密钥文件；删除运行目录会丢失本机新增数据，种子文件不能还原个人修改。`.env`、`runtime/` 和模型密钥不提交 Git。

## 行内与行外

默认使用 SQLite/Celery 行外联调；已有 BJS 配置仍使用独立调度进程，不启动 Redis/Celery Worker，已有 MySQL 配置不会被覆盖，也不会初始化本地专项数据。行外目录使用本地 `localAgentDirectory` 和 `local` 令牌；行内使用配置的网关与真实会话令牌。行内部署不使用本地初始化脚本，应按机构环境配置数据库、调度和网关。贷款测试使用 `test-policy-v1`、合成客户，不连接生产征信或放款系统。

## 目录与验证

`frontend/` 是 Vue 前端，`src/agentgate/` 是后端，`tested-agents/` 是贷款服务，`vendor/trace-sdk/` 和 `vendor/trace-server/` 保存上游 SDK/查询服务及来源说明，`scripts/` 提供安装与验收入口。

```bash
PYTHONPATH=src .venv/bin/pytest -q tests
(cd tested-agents && PYTHONPATH=src .venv/bin/pytest -q)
(cd frontend && npm run lint && npm run test:unit && npm run build)
```

自动化单元测试使用模拟模型，真实模型验收使用上述 `run-loan-core-evaluations.py`。更详细的 [安装与验收](docs/bank-agents/README.md)、[架构](docs/architecture.md)、[项目进展](docs/project-progress.md) 和 [文档索引](docs/README.md) 均在仓库内。后端许可证见 LICENSE；不能将该许可证自动扩展至客户 SDK/Trace Server，来源声明在对应 vendor 目录。

本次[新目录及真实模型验收记录](docs/bank-agents/delivery-verification-20261008.md)保留运行ID、实际分数及验证范围。

六类智能体现支持[主动 Trace 上报与分机部署](docs/trace/trace-reporting.md)。可运行 `.venv/bin/python scripts/verify-trace-reporting.py` 新建六项验收任务；三个本地模拟体的轨迹会明确标记为模拟。
