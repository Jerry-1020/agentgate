# AgentGate 生产环境部署操作文档

本手册描述如何将 AgentGate 手动部署到生产环境服务器，使用 `scripts/run.sh` 脚本完成服务的启停操作。

文档涵盖 Celery 和 BJS 两种任务调度模式的完整部署流程。

---

## 目录

1. [部署架构概览](#1-部署架构概览)
2. [前置条件与中间件准备](#2-前置条件与中间件准备)
3. [需要部署的目录与文件清单](#3-需要部署的目录与文件清单)
4. [服务器准备步骤](#4-服务器准备步骤)
5. [环境变量配置说明](#5-环境变量配置说明)
6. [Celery 模式部署](#6-celery-模式部署)
7. [BJS 模式部署](#7-bjs-模式部署)
8. [run.sh 脚本操作手册](#8-runsh-脚本操作手册)
9. [端口清单](#9-端口清单)
10. [日志管理](#10-日志管理)
11. [验证与排障](#11-验证与排障)

---

## 1. 部署架构概览

AgentGate 由以下进程组成，根据调度模式不同，需要启动的进程有所区别：

| 进程 | 说明 | Celery 模式 | BJS 模式 |
|------|------|:-----------:|:--------:|
| **API** | FastAPI 后端服务，提供评测提交、查询、管理等 REST API | 需要 | 需要 |
| **Worker** | Celery Worker，消费任务队列执行评测 Run | 需要 | 不需要 |
| **Scheduler** | 任务调度器，扫描到期 Run 并派发 | 需要（Celery Beat） | 需要（Python 轮询脚本） |
| **Redis** | 消息中间件，Celery 的 broker | 需要 | 不需要 |
| **Web** | 前端服务 | 需要 | 需要 |
| **Bank Agents** | 被测智能体服务（可选） | 可选 | 可选 |

### 两种模式的核心差异

- **Celery 模式**（`AGENT_TASK_DISPATCHER_TYPE=celery`）：AgentGate 内部通过 Redis + Celery 完成任务派发和执行，自包含的异步流水线。
- **BJS 模式**（`AGENT_TASK_DISPATCHER_TYPE=bjs`）：AgentGate 将 Run ID 提交到外部 BJS（Batch Job Scheduler）平台，由 BJS 平台调度执行；BJS 平台在执行时回调 AgentGate 的 `run.sh execute-run <run_id>` 同步执行评测。无需 Redis 和 Celery。

---

## 2. 前置条件与中间件准备

### 2.1 系统环境

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | >= 3.11 | 后端运行时 |
| uv | 最新稳定版 | Python 包管理器，用于 `uv sync` 安装依赖 |
| Node.js | >= 22 | 前端构建运行时 |
| npm | >= 10.7 | 前端包管理器 |
| bash | >= 4 | `run.sh` 脚本依赖 |

### 2.2 中间件

| 中间件 | Celery 模式 | BJS 模式 | 说明 |
|--------|:-----------:|:--------:|------|
| **Redis** | 需要 | 不需要 | Celery 的消息 broker。可使用服务器自带 Redis 或通过 `run.sh redis` 启动内置实例（端口 6397） |
| **MySQL / TDSQL** | 可选 | 可选 | 持久化存储后端，默认使用 SQLite。若需使用 MySQL，设置 `AGENTGATE_DB_TYPE=tdsql` |
| **BJS 平台** | 不需要 | 需要 | 外部批量作业调度平台，需提前在 BJS 侧创建作业模板并获取 Job ID |

### 2.3 外部服务地址（按需配置）

| 服务 | 环境变量 | 说明 |
|------|---------|------|
| Trace Server | `AGENTGATE_TRACE_SERVER_URL` | 行内 Trace 取证服务，评测执行时按 trace_id 获取证据 |
| 被测 Agent 服务 | `AGENTGATE_BANK_BASE_URL` | 银行智能体服务地址，bank-evaluations 路由使用 |
| Agent 平台 | `AGENTGATE_AGENT_PLATFORM_ORIGIN` | Agent 管理平台服务地址 |
| LLM Judge 模型 | `AGENTGATE_JUDGE_*`（四项） | 可选的 LLM 评测 Judge 模型连接 |

---

## 3. 需要部署的目录与文件清单

### 3.1 必须部署的目录和文件

以下目录和文件需要从源码仓库复制到生产服务器：

```
agentgate/
├── src/                      # Python 后端源码（核心）
├── scripts/                  # 启停脚本和工具脚本（核心）
│   ├── run.sh                # 服务启停入口脚本
│   ├── bjs/                  # BJS 模式执行脚本
│   │   ├── run_eval.sh
│   │   └── run_evaluation.py
│   ├── dispatch-scheduled-runs.py
│   ├── seed-bank-agents.py
│   ├── verify-bank-traces.py
│   ├── init.sql              # 数据库初始化 SQL
│   └── ...
├── frontend/                 # 前端源码
│   ├── src/
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── .env.example
│   └── ...
├── tested-agents/            # 被测智能体（可选，需运行 bank-agents 时部署）
│   ├── src/
│   ├── run.py
│   ├── pyproject.toml
│   ├── uv.lock
│   └── ...
├── vendor/                   # 第三方 SDK（trace-sdk）
├── pyproject.toml            # Python 项目配置和依赖声明
├── uv.lock                   # Python 依赖锁文件
├── .env.example              # 环境变量模板
├── README.md
└── LICENSE
```

### 3.2 不需要部署的目录和文件

以下内容属于开发、测试或运行时产物，**不要**复制到生产服务器：

| 目录/文件 | 原因 |
|-----------|------|
| `runtime/` | 运行时生成的数据、日志、Trace，服务器上会自动创建 |
| `.venv/` | Python 虚拟环境，服务器上通过 `uv sync` 重新创建 |
| `tested-agents/.venv/` | 同上 |
| `frontend/node_modules/` | 前端依赖，服务器上通过 `npm ci` 重新安装 |
| `*.db`、`*.db-shm`、`*.db-wal` | SQLite 数据库文件，生产环境重新初始化 |
| `tests/` | 测试代码 |
| `delivery/` | 历史交付快照 |
| `docs/` | 开发文档（可选部署，不影响运行） |
| `.git/` | Git 仓库元数据 |
| `.idea/`、`.pytest_cache/`、`.ruff_cache/` | IDE 缓存和工具缓存 |
| `__pycache__/` | Python 字节码缓存 |
| `.env` | 含敏感信息的环境配置，**在服务器上单独创建**，不要复制 |
| `dump.rdb` | Redis 持久化快照 |
| `agentgate-demo.db`、`agentgate.db` | 开发环境数据库 |

---

## 4. 服务器准备步骤

### 4.1 创建部署目录

```bash
# 在生产服务器上创建部署目录
mkdir -p /opt/agentgate
```

### 4.2 传输文件

将 [3.1 节](#31-必须部署的目录和文件) 中列出的目录和文件传输到 `/opt/agentgate`：

```bash
# 示例：从开发机使用 rsync 传输（排除不需要的文件）
rsync -avz --exclude='runtime/' \
  --exclude='.venv/' \
  --exclude='tested-agents/.venv/' \
  --exclude='frontend/node_modules/' \
  --exclude='*.db' --exclude='*.db-*' \
  --exclude='tests/' \
  --exclude='delivery/' \
  --exclude='.git/' \
  --exclude='.idea/' \
  --exclude='.pytest_cache/' --exclude='.ruff_cache/' \
  --exclude='__pycache__/' \
  --exclude='.env' \
  --exclude='dump.rdb' \
  --exclude='docs/' \
  /path/to/agentgate/ user@server:/opt/agentgate/
```

传输完成后确认目录结构：

```bash
ls /opt/agentgate
# 应看到：src/  scripts/  frontend/  tested-agents/  vendor/  pyproject.toml  uv.lock  .env.example  README.md  LICENSE
```

### 4.3 安装 Python 依赖

```bash
cd /opt/agentgate
uv sync --locked --python 3.11 --extra test
```

此命令会创建 `.venv/` 虚拟环境并安装 `pyproject.toml` 和 `uv.lock` 中锁定的所有依赖。

如需部署被测智能体（bank-agents），还需安装其依赖：

```bash
cd /opt/agentgate/tested-agents
uv sync --locked --python 3.11 --extra test
```

### 4.4 安装前端依赖

```bash
cd /opt/agentgate/frontend
npm ci --ignore-scripts
```

> `--ignore-scripts` 跳过 postinstall 脚本，避免在安装阶段触发不必要的副作用。依赖以 `package-lock.json` 为准。

### 4.5 创建环境配置文件

```bash
cd /opt/agentgate
cp .env.example .env
chmod 600 .env
```

然后编辑 `.env`，按照 [第 5 节](#5-环境变量配置说明) 填写生产环境的配置值。

### 4.6 创建运行时目录

`run.sh` 会自动创建 `runtime/` 和 `runtime/logs/` 目录，无需手动创建。但如需自定义日志路径，请提前创建：

```bash
mkdir -p /var/log/agentgate
```

### 4.7 初始化数据库（可选）

- **SQLite 模式**：首次启动 API 时自动创建数据库文件，无需手动初始化。
- **TDSQL/MySQL 模式**：需提前在 MySQL 中创建数据库，并可使用 `scripts/init.sql` 初始化表结构：

```bash
mysql -h <host> -P <port> -u <user> -p <database> < /opt/agentgate/scripts/init.sql
```

### 4.8 初始化评测数据（可选）

如需初始化银行评测集数据，在服务启动后执行：

```bash
cd /opt/agentgate
bash scripts/run.sh seed
```

---

## 5. 环境变量配置说明

所有环境变量配置在 `/opt/agentgate/.env` 文件中。`run.sh` 在启动 `api`、`worker`、`scheduler`、`web`、`seed`、`verify-traces`、`execute-run`、`dispatch-due`、`dispatcher-type` 等命令时，会自动 source 该文件（可通过 `AGENTGATE_MODEL_ENV_FILE` 指定其他路径）。

### 5.1 通用环境变量（两种模式都需要）

| 变量名 | 必填 | 默认值 | 说明 |
|--------|:----:|--------|------|
| `AGENTGATE_LOG_PATH` | 否 | `runtime/logs` | 日志文件保存目录 |
| `AGENTGATE_DB_TYPE` | 否 | `sqlite` | 数据库后端类型，`sqlite` 或 `tdsql` |
| `AGENTGATE_DB` | 否 | `runtime/agentgate.db` | SQLite 数据库文件路径。API 和 Worker 必须使用相同的绝对路径 |
| `AGENTGATE_TDSQL_URL` | 仅 tdsql 模式 | - | MySQL 连接 URL，格式 `mysql+pymysql://host:port/database`，不含用户名密码 |
| `AGENTGATE_TDSQL_USER` | 仅 tdsql 模式 | - | MySQL 用户名 |
| `AGENTGATE_TDSQL_PASSWORD` | 仅 tdsql 模式 | - | MySQL 密码 |
| `AGENTGATE_TRACE_SERVER_URL` | 是 | - | Trace Server 取证服务地址，必须是绝对 HTTP(S) URL |
| `AGENT_TASK_DISPATCHER_TYPE` | 是 | `celery` | 任务调度类型：`celery` 或 `bjs` |
| `AGENTGATE_SCHEDULER_INTERVAL_SECONDS` | 否 | `10` | 调度器扫描到期 Run 的间隔（秒），最小为 1 |
| `AGENTGATE_MAX_CONCURRENT_RUNS_PER_API_KEY` | 否 | `10` | 每个 api_key 允许的最大并行任务数（PENDING + RUNNING） |
| `AGENTGATE_MAX_DISPATCH_ATTEMPTS` | 否 | `10` | Run 派发失败后最大重试次数，超过后转为 FAILED |

### 5.2 Celery 模式专属环境变量

以下变量仅在 `AGENT_TASK_DISPATCHER_TYPE=celery` 时需要配置：

| 变量名 | 必填 | 默认值 | 说明 |
|--------|:----:|--------|------|
| `AGENTGATE_REDIS_MODE` | 否 | `single` | Redis broker 部署模式：`single`（单机）或 `cluster`（集群） |
| `AGENTGATE_REDIS_URL` | 是 | `redis://127.0.0.1:6397/0` | Redis broker 地址。single 模式用普通 Redis URL；cluster 模式填写任一可访问的集群节点且只能使用 `/0` |
| `AGENTGATE_REDIS_CLUSTER_HASH_TAG` | 仅 cluster 模式 | `{agentgate}` | Cluster 模式下强制所有 Celery broker key 位于同一 hash slot，避免 CROSSSLOT 错误 |
| `AGENTGATE_WORKER_CONCURRENCY` | 否 | `1` | Worker 并发数，默认 1 表示串行执行，保护 SQLite。使用 TDSQL 时可适当调大 |
| `AGENTGATE_TASK_TIME_LIMIT_SECONDS` | 否 | `360` | 单个 Run 任务的最大执行时长（秒），超时硬终止 |

> **重要**：API、Worker、Scheduler 三个进程必须使用相同的 `AGENTGATE_REDIS_URL` 和 `AGENTGATE_DB` 值，否则消息无法正确传递。

### 5.3 BJS 模式专属环境变量

以下变量仅在 `AGENT_TASK_DISPATCHER_TYPE=bjs` 时需要配置：

| 变量名 | 必填 | 默认值 | 说明 |
|--------|:----:|--------|------|
| `AGENTGATE_BJS_SUBMIT_URL` | 是 | - | BJS 测评任务提交接口的完整 URL。`submit()` 会自动追加 `taskId` 和 `jobId` 查询参数。URL 不能含凭据、查询字符串或 fragment |
| `AGENTGATE_BJS_JOB_ID` | 是 | - | BJS 作业模板 ID，由 BJS 平台提供 |

> **BJS 模式不需要配置** `AGENTGATE_REDIS_MODE`、`AGENTGATE_REDIS_URL`、`AGENTGATE_REDIS_CLUSTER_HASH_TAG`、`AGENTGATE_WORKER_CONCURRENCY`、`AGENTGATE_TASK_TIME_LIMIT_SECONDS` 等 Celery 相关变量。

> **重要**：BJS 平台在调度执行时，需要能回调到 AgentGate 服务器执行 `bash scripts/run.sh execute-run <run_id>`。请确保 BJS 平台到 AgentGate 服务器的网络可达。

### 5.4 可选环境变量（两种模式通用）

| 变量名 | 说明 |
|--------|------|
| `AGENTGATE_JUDGE_PROVIDER_ID` | LLM Judge 评测器提供商标识，如 `openai-compatible`。四项全设启用 LLM Judge，全不设则走纯规则评估 |
| `AGENTGATE_JUDGE_BASE_URL` | LLM Judge 模型 API 地址，必须使用 HTTPS，不含 `/chat/completions` |
| `AGENTGATE_JUDGE_API_KEY` | LLM Judge 模型 API Key |
| `AGENTGATE_JUDGE_MODEL_ID` | LLM Judge 模型 ID |
| `AGENTGATE_API_KEY_ENCRYPTION_KEY` | API Key 加密主密钥（URL-safe Base64，32 字节随机数）。不设则 API Key 相关接口返回 503。保持各进程和重启后使用相同密钥 |
| `AGENTGATE_BANK_BASE_URL` | 被测 Agent 服务地址，默认 `http://127.0.0.1:8107` |
| `AGENTGATE_AGENT_PLATFORM_MODE` | Agent 平台模式：`mock`（本地模拟）或留空（真实平台） |
| `AGENTGATE_AGENT_PLATFORM_ORIGIN` | Agent 平台服务地址，默认 `http://127.0.0.1:8119` |

> **LLM Judge 注意**：如启用 Judge，API 和 Worker 进程必须接收完全相同的四个 Judge 变量值。四项要么全设，要么全不设，部分配置会被拒绝。

### 5.5 前端环境变量

前端环境变量配置在 `frontend/.env.local` 文件中（或在 `run.sh web` 命令中通过环境变量传入）：

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FRONTEND_PORT` | `5197`（run.sh 设置） | 前端服务端口 |
| `API_PROXY_TARGET` | `http://127.0.0.1:8097`（run.sh 设置） | API 代理目标地址 |
| `VITE_API_BASE_URL` | `/api` | 浏览器请求前缀，保持同源代理 |

> `run.sh web` 命令已硬编码 `FRONTEND_PORT=5197` 和 `API_PROXY_TARGET=http://127.0.0.1:8097`，无需额外配置。

> **生产环境前端建议**：`run.sh web` 使用的是 `npm run dev`（Vite 开发服务器）。生产环境建议改用 `npm run build` 构建静态文件，然后用 Nginx 等反向代理托管 `frontend/dist/`，并将 `/api` 路径代理到 API 服务。如需保留 `run.sh web` 方式，可直接使用，但性能不如静态部署。

### 5.6 环境变量配置示例

#### Celery 模式 `.env` 示例

```dotenv
# ===== 基础设施 =====
AGENTGATE_LOG_PATH=/var/log/agentgate

# 数据库（二选一）
# SQLite 模式
AGENTGATE_DB_TYPE=sqlite
AGENTGATE_DB=/opt/agentgate/runtime/agentgate.db

# TDSQL/MySQL 模式（如需使用 MySQL，取消注释并填写）
# AGENTGATE_DB_TYPE=tdsql
# AGENTGATE_TDSQL_URL=mysql+pymysql://mysql-host:3306/agentgate
# AGENTGATE_TDSQL_USER=agentgate
# AGENTGATE_TDSQL_PASSWORD=your-password

# Redis broker
AGENTGATE_REDIS_MODE=single
AGENTGATE_REDIS_URL=redis://127.0.0.1:6397/0
# Cluster 模式（如需集群，取消注释并填写）
# AGENTGATE_REDIS_MODE=cluster
# AGENTGATE_REDIS_URL=redis://redis-seed:6379/0
# AGENTGATE_REDIS_CLUSTER_HASH_TAG={agentgate}

# 任务调度类型
AGENT_TASK_DISPATCHER_TYPE=celery

# ===== Trace Server =====
AGENTGATE_TRACE_SERVER_URL=http://trace-server-host:8210

# ===== Celery Worker =====
AGENTGATE_WORKER_CONCURRENCY=1
AGENTGATE_TASK_TIME_LIMIT_SECONDS=360
AGENTGATE_SCHEDULER_INTERVAL_SECONDS=10

# ===== 并行限制 =====
AGENTGATE_MAX_CONCURRENT_RUNS_PER_API_KEY=3
AGENTGATE_MAX_DISPATCH_ATTEMPTS=3

# ===== LLM Judge（可选）=====
# AGENTGATE_JUDGE_PROVIDER_ID=openai-compatible
# AGENTGATE_JUDGE_BASE_URL=https://provider.example/v1
# AGENTGATE_JUDGE_API_KEY=your-api-key
# AGENTGATE_JUDGE_MODEL_ID=your-model-id

# ===== API Key 加密（可选）=====
# AGENTGATE_API_KEY_ENCRYPTION_KEY=

# ===== 被测 Agent 服务 =====
AGENTGATE_BANK_BASE_URL=http://127.0.0.1:8107
AGENTGATE_AGENT_PLATFORM_ORIGIN=http://agent-platform-host:8119
```

#### BJS 模式 `.env` 示例

```dotenv
# ===== 基础设施 =====
AGENTGATE_LOG_PATH=/var/log/agentgate

# 数据库（二选一）
AGENTGATE_DB_TYPE=sqlite
AGENTGATE_DB=/opt/agentgate/runtime/agentgate.db
# AGENTGATE_DB_TYPE=tdsql
# AGENTGATE_TDSQL_URL=mysql+pymysql://mysql-host:3306/agentgate
# AGENTGATE_TDSQL_USER=agentgate
# AGENTGATE_TDSQL_PASSWORD=your-password

# 任务调度类型
AGENT_TASK_DISPATCHER_TYPE=bjs

# ===== Trace Server =====
AGENTGATE_TRACE_SERVER_URL=http://trace-server-host:8210

# ===== BJS 调度 =====
AGENTGATE_BJS_SUBMIT_URL=http://bjs-platform-host/web/eval/job/bjs/submit
AGENTGATE_BJS_JOB_ID=ai11

# ===== 调度间隔 =====
AGENTGATE_SCHEDULER_INTERVAL_SECONDS=10

# ===== 并行限制 =====
AGENTGATE_MAX_CONCURRENT_RUNS_PER_API_KEY=3
AGENTGATE_MAX_DISPATCH_ATTEMPTS=3

# ===== LLM Judge（可选）=====
# AGENTGATE_JUDGE_PROVIDER_ID=openai-compatible
# AGENTGATE_JUDGE_BASE_URL=https://provider.example/v1
# AGENTGATE_JUDGE_API_KEY=your-api-key
# AGENTGATE_JUDGE_MODEL_ID=your-model-id

# ===== 被测 Agent 服务 =====
AGENTGATE_BANK_BASE_URL=http://127.0.0.1:8107
AGENTGATE_AGENT_PLATFORM_ORIGIN=http://agent-platform-host:8119
```

---

## 6. Celery 模式部署

### 6.1 需要配置的环境变量

Celery 模式需要配置 [5.1 通用环境变量](#51-通用环境变量两种模式都需要) 和 [5.2 Celery 模式专属环境变量](#52-celery-模式专属环境变量)。

核心变量：
- `AGENT_TASK_DISPATCHER_TYPE=celery`
- `AGENTGATE_REDIS_URL=redis://127.0.0.1:6397/0`（或实际 Redis 地址）
- `AGENTGATE_DB`（确保 API 和 Worker 使用相同绝对路径）

### 6.2 需要启动的进程

Celery 模式需要按以下顺序启动 5 个进程（如需被测智能体则 6 个）：

| 启动顺序 | 进程 | run.sh 命令 | 说明 |
|:--------:|------|-------------|------|
| 1 | Redis | `bash scripts/run.sh redis` | 消息中间件，必须最先启动 |
| 2 | API | `bash scripts/run.sh api` | FastAPI 后端服务 |
| 3 | Worker | `bash scripts/run.sh worker` | Celery Worker，消费任务队列执行评测 |
| 4 | Scheduler | `bash scripts/run.sh scheduler` | Celery Beat 调度器，扫描到期 Run 并投递到任务队列 |
| 5 | Web | `bash scripts/run.sh web` | 前端服务 |
| 6（可选） | Bank Agents | `bash scripts/run.sh bank-agents` | 被测智能体服务 |

### 6.3 逐步启动操作

每个进程需要在独立的终端中启动，或在后台运行：

```bash
cd /opt/agentgate

# 1. 启动 Redis（如使用服务器已有的 Redis，可跳过此步，确保 .env 中 AGENTGATE_REDIS_URL 指向正确地址）
bash scripts/run.sh redis

# 2. 启动 API 服务
bash scripts/run.sh api

# 3. 启动 Celery Worker
bash scripts/run.sh worker

# 4. 启动 Scheduler（Celery Beat）
bash scripts/run.sh scheduler

# 5. 启动前端
bash scripts/run.sh web

# 6. （可选）启动被测智能体
bash scripts/run.sh bank-agents
```

### 6.4 后台运行方式（推荐生产环境）

生产环境建议使用 `nohup` 或进程管理工具（如 systemd、supervisor）将每个进程放到后台运行：

```bash
cd /opt/agentgate

# 使用 nohup 后台运行
nohup bash scripts/run.sh redis > /dev/null 2>&1 &
nohup bash scripts/run.sh api > /dev/null 2>&1 &
nohup bash scripts/run.sh worker > /dev/null 2>&1 &
nohup bash scripts/run.sh scheduler > /dev/null 2>&1 &
nohup bash scripts/run.sh web > /dev/null 2>&1 &

# （可选）被测智能体
nohup bash scripts/run.sh bank-agents > /dev/null 2>&1 &
```

> `run.sh` 已将各进程的 stdout/stderr 重定向到 `runtime/logs/` 下的日志文件，因此 `nohup` 的重定向仅为防止终端退出时进程被终止。

### 6.5 一键启动（可选）

如需一键启动所有服务（包括被测智能体），可使用集成启动脚本：

```bash
cd /opt/agentgate
bash scripts/start-bank-integration.sh
```

该脚本会检查前置依赖，然后通过 `scripts/start-integration.py` 依次启动所有进程（Redis、API、Worker、Scheduler、Web、Bank Agents），并自动打开浏览器。按 `Ctrl+C` 停止本次启动的所有服务。

> **注意**：`start-bank-integration.sh` 是为本地联调设计的，启动时会检查端口占用。生产环境建议使用 [6.4 节](#64-后台运行方式推荐生产环境) 的方式逐个后台启动。

---

## 7. BJS 模式部署

### 7.1 需要配置的环境变量

BJS 模式需要配置 [5.1 通用环境变量](#51-通用环境变量两种模式都需要) 和 [5.3 BJS 模式专属环境变量](#53-bjs-模式专属环境变量)。

核心变量：
- `AGENT_TASK_DISPATCHER_TYPE=bjs`
- `AGENTGATE_BJS_SUBMIT_URL=http://bjs-platform-host/web/eval/job/bjs/submit`
- `AGENTGATE_BJS_JOB_ID=ai11`

> BJS 模式**不需要**配置 Redis 相关变量，也**不需要**启动 Redis 和 Celery Worker。

### 7.2 需要启动的进程

BJS 模式需要按以下顺序启动 3 个进程（如需被测智能体则 4 个）：

| 启动顺序 | 进程 | run.sh 命令 | 说明 |
|:--------:|------|-------------|------|
| 1 | API | `bash scripts/run.sh api` | FastAPI 后端服务 |
| 2 | Scheduler | `bash scripts/run.sh scheduler` | Python 轮询脚本（`dispatch-scheduled-runs.py`），扫描到期 Run 并提交到 BJS 平台 |
| 3 | Web | `bash scripts/run.sh web` | 前端服务 |
| 4（可选） | Bank Agents | `bash scripts/run.sh bank-agents` | 被测智能体服务 |

### 7.3 BJS 模式的工作流程

```
用户提交评测 Run
      │
      ▼
  API 接收并持久化 Run（状态 PENDING）
      │
      ▼
  Scheduler 轮询扫描到期 Run
      │
      ▼
  通过 BJS API 提交 Run ID 到 BJS 平台
      （POST AGENTGATE_BJS_SUBMIT_URL?taskId=<run_id>&jobId=<job_id>）
      │
      ▼
  BJS 平台调度执行
      │
      ▼
  BJS 平台回调 AgentGate 执行评测
      （bash scripts/run.sh execute-run <run_id>）
      │
      ▼
  同步执行 Run，输出结果到数据库
```

### 7.4 BJS 平台回调配置

BJS 平台在调度执行时，需要在 BJS 作业模板中配置回调 AgentGate 服务器执行以下命令：

```bash
cd /opt/agentgate && bash scripts/run.sh execute-run <run_id>
```

其中 `<run_id>` 是 AgentGate 提交任务时传入的 `taskId` 参数值。该命令会同步执行评测 Run，完成后将结果写入数据库。

### 7.5 逐步启动操作

```bash
cd /opt/agentgate

# 1. 启动 API 服务
bash scripts/run.sh api

# 2. 启动 Scheduler（BJS 模式下运行 dispatch-scheduled-runs.py）
bash scripts/run.sh scheduler

# 3. 启动前端
bash scripts/run.sh web

# 4. （可选）启动被测智能体
bash scripts/run.sh bank-agents
```

### 7.6 后台运行方式

```bash
cd /opt/agentgate

nohup bash scripts/run.sh api > /dev/null 2>&1 &
nohup bash scripts/run.sh scheduler > /dev/null 2>&1 &
nohup bash scripts/run.sh web > /dev/null 2>&1 &

# （可选）被测智能体
nohup bash scripts/run.sh bank-agents > /dev/null 2>&1 &
```

### 7.7 外部调度器替代方案

如果不使用 `run.sh scheduler` 持续运行调度器，也可以使用外部调度器（如 cron）定期触发单次扫描：

```bash
# 每 10 秒扫描一次到期 Run（需外部循环或 cron 定时）
cd /opt/agentgate && bash scripts/run.sh dispatch-due
```

该命令执行 `dispatch-scheduled-runs.py --once`，扫描一次到期 Run 并派发后退出。

---

## 8. run.sh 脚本操作手册

### 8.1 命令语法

```bash
bash scripts/run.sh <command> [arguments...]
```

### 8.2 命令清单

| 命令 | 参数 | 说明 |
|------|------|------|
| `redis` | 无 | 启动内置 Redis 实例（端口 6397，仅 Celery 模式需要） |
| `api` | 无 | 启动 FastAPI 后端服务（端口 8097） |
| `worker` | 无 | 启动 Celery Worker（仅 Celery 模式需要） |
| `scheduler` | 无 | 启动任务调度器。Celery 模式启动 Celery Beat Worker；BJS 模式启动 `dispatch-scheduled-runs.py` 轮询脚本 |
| `web` | 无 | 启动前端 Vite 开发服务器（端口 5197，代理到 API 8097） |
| `bank-agents` | 无 | 启动被测智能体服务（端口 8107） |
| `seed` | 无 | 初始化银行评测集数据到数据库 |
| `verify-traces` | `[args]` | 验证银行 Trace 数据完整性 |
| `execute-run` | `<run_id>` | 同步执行指定 Run（BJS 模式下由 BJS 平台回调调用） |
| `dispatch-due` | `[args]` | 单次扫描并派发到期 Run，执行后退出 |
| `dispatcher-type` | 无 | 打印当前任务调度类型（`celery` 或 `bjs`） |
| `stop` | `[服务名...]` | 停止指定服务，不传参数则停止全部 |

### 8.3 启动服务

每个服务在独立终端中启动：

```bash
cd /opt/agentgate

# 查看当前调度类型（确认配置是否正确）
bash scripts/run.sh dispatcher-type
# 输出：celery 或 bjs

# 按需启动各服务
bash scripts/run.sh redis        # 仅 Celery 模式
bash scripts/run.sh api
bash scripts/run.sh worker       # 仅 Celery 模式
bash scripts/run.sh scheduler
bash scripts/run.sh web
bash scripts/run.sh bank-agents  # 可选
```

### 8.4 停止服务

#### 停止指定服务

```bash
cd /opt/agentgate

bash scripts/run.sh stop api
bash scripts/run.sh stop worker
bash scripts/run.sh stop scheduler
bash scripts/run.sh stop redis
bash scripts/run.sh stop web
bash scripts/run.sh stop bank-agents
```

#### 停止多个服务

```bash
bash scripts/run.sh stop api worker scheduler
```

#### 停止全部服务

```bash
bash scripts/run.sh stop
# 或
bash scripts/run.sh stop all
```

> `stop all` 会停止以下所有进程：API、所有 Celery 进程（Worker 和 Beat）、dispatch-scheduled-runs、Redis、前端。

### 8.5 停止机制说明

`run.sh stop` 通过 `pgrep -f` 按进程命令行模式匹配目标进程：
1. 先发送 `SIGTERM`（`kill`）优雅停止
2. 等待 1 秒后检查进程是否退出
3. 如仍存活，发送 `SIGKILL`（`kill -9`）强制终止

各服务的匹配模式：

| 服务 | 匹配模式 |
|------|---------|
| api | `uvicorn agentgate.server.app` |
| worker | `celery.*agentgate.*--hostname=unified-tasks-20260915` |
| scheduler | `celery.*agentgate.*--beat` 和 `dispatch-scheduled-runs` |
| redis | `redis-server.*6397` |
| web | `vite.*5197\|npm run dev` |

### 8.6 run.sh 的环境变量加载机制

`run.sh` 在启动服务前会按以下顺序加载环境变量：

1. 设置内置默认值：
   - `AGENTGATE_REDIS_MODE=single`（如未设置）
   - `AGENTGATE_REDIS_URL=redis://127.0.0.1:6397/0`（如未设置）
   - `PYTHONPATH=<项目根>/src`
2. 从 `.env` 文件（或 `AGENTGATE_MODEL_ENV_FILE` 指定的文件）加载环境变量，覆盖默认值
3. 设置数据库路径：`AGENTGATE_DB`（如未设置则使用 `<项目根>/runtime/agentgate.db`）
4. 设置日志目录：`AGENTGATE_LOG_PATH`（如未设置则使用 `<项目根>/runtime/logs`）

> 如需指定自定义 `.env` 文件路径，设置 `AGENTGATE_MODEL_ENV_FILE` 环境变量：
> ```bash
> export AGENTGATE_MODEL_ENV_FILE=/path/to/custom.env
> bash scripts/run.sh api
> ```

---

## 9. 端口清单

| 服务 | 端口 | 说明 |
|------|------|------|
| API | 8097 | FastAPI 后端服务 |
| 前端 | 5197 | Vite 开发服务器 |
| Redis | 6397 | `run.sh redis` 启动的内置 Redis 实例 |
| Bank Agents | 8107 | 被测智能体服务 |
| Trace Server | 8210 | 行内 Trace 取证服务（外部服务） |
| Agent 平台 | 8119 | Agent 管理平台（外部服务） |

> 以上端口为 `run.sh` 的默认值。Redis 端口 6397 是 `run.sh` 内置实例的端口，如使用外部 Redis，需在 `.env` 中修改 `AGENTGATE_REDIS_URL`。

> 启动前请确保以上端口未被占用。`start-integration.py` 会在启动前检查端口占用情况。

---

## 10. 日志管理

### 10.1 日志文件位置

各进程的日志文件默认保存在 `runtime/logs/` 目录下（或 `AGENTGATE_LOG_PATH` 指定的目录）：

| 进程 | 日志文件 |
|------|---------|
| API | `runtime/logs/api.log` |
| Worker | `runtime/logs/worker.log` |
| Scheduler | `runtime/logs/scheduler.log` |
| Redis | `runtime/logs/redis.log` |
| Web | `runtime/logs/web.log` |
| Bank Agents | `runtime/logs/bank-agents.log`（通过 `start-integration.py` 启动时） |

### 10.2 查看日志

```bash
cd /opt/agentgate

# 实时查看 API 日志
tail -f runtime/logs/api.log

# 实时查看 Worker 日志
tail -f runtime/logs/worker.log

# 查看最近 100 行 Scheduler 日志
tail -n 100 runtime/logs/scheduler.log
```

### 10.3 自定义日志路径

在 `.env` 中设置 `AGENTGATE_LOG_PATH`：

```dotenv
AGENTGATE_LOG_PATH=/var/log/agentgate
```

设置后日志文件将保存到 `/var/log/agentgate/` 目录下，文件名不变。

---

## 11. 验证与排障

### 11.1 健康检查

启动 API 服务后，验证服务是否正常运行：

```bash
# 检查 API 健康状态
curl http://127.0.0.1:8097/health

# 检查前端是否可访问
curl -I http://127.0.0.1:5197/

# 确认当前调度类型
cd /opt/agentgate && bash scripts/run.sh dispatcher-type
```

### 11.2 确认进程状态

```bash
# 检查各进程是否在运行
pgrep -f "uvicorn agentgate.server.app"       # API
pgrep -f "celery.*agentgate"                  # Worker / Scheduler（Celery 模式）
pgrep -f "dispatch-scheduled-runs"            # Scheduler（BJS 模式）
pgrep -f "redis-server.*6397"                 # Redis（Celery 模式）
pgrep -f "vite.*5197\|npm run dev"            # 前端
pgrep -f "bank_agents.app"                    # 被测智能体
```

### 11.3 常见问题

#### 问题：端口被占用

```
端口 8097 已被占用。不会停止已有服务
```

**解决**：先停止占用端口的进程，或使用 `run.sh stop` 停止旧的服务实例：

```bash
bash scripts/run.sh stop all
# 确认端口已释放后重新启动
bash scripts/run.sh api
```

#### 问题：Redis 连接失败（Celery 模式）

**原因**：Redis 未启动，或 `AGENTGATE_REDIS_URL` 配置错误。

**解决**：
```bash
# 检查 Redis 是否在运行
pgrep -f "redis-server"

# 如未启动，使用 run.sh 启动内置 Redis
bash scripts/run.sh redis

# 或检查 .env 中的 AGENTGATE_REDIS_URL 是否指向正确的 Redis 地址
```

#### 问题：BJS 提交失败（BJS 模式）

**原因**：BJS 平台不可达，或 `AGENTGATE_BJS_SUBMIT_URL` / `AGENTGATE_BJS_JOB_ID` 配置错误。

**解决**：
- 检查 `.env` 中 `AGENTGATE_BJS_SUBMIT_URL` 是否为 BJS 平台的正确提交地址
- 检查 `AGENTGATE_BJS_JOB_ID` 是否为 BJS 平台已创建的作业模板 ID
- 确认 AgentGate 服务器到 BJS 平台的网络可达
- 查看 `runtime/logs/scheduler.log` 中的 BJS 提交日志

> **注意**：当前 BJS 提交在 BJS 平台不可达时会输出 warning 日志并模拟成功响应（mock），使 Run 继续进入 RUNNING 状态。生产环境中 BJS 平台可达后，提交失败将抛出异常。请确保 BJS 平台地址配置正确。

#### 问题：数据库锁或并发错误（SQLite 模式）

**原因**：SQLite 在高并发写入时可能出现锁冲突。

**解决**：
- 保持 `AGENTGATE_WORKER_CONCURRENCY=1`（串行执行）
- 如并发需求较高，切换到 TDSQL/MySQL 模式：设置 `AGENTGATE_DB_TYPE=tdsql` 并配置 MySQL 连接信息

#### 问题：前端无法访问 API

**原因**：前端代理目标配置错误或 API 服务未启动。

**解决**：
- 确认 API 服务已启动：`curl http://127.0.0.1:8097/health`
- 确认 `run.sh web` 设置的 `API_PROXY_TARGET=http://127.0.0.1:8097` 与 API 服务地址一致
- 检查防火墙是否允许 5197 和 8097 端口的本地访问

#### 问题：LLM Judge 不生效

**原因**：LLM Judge 的四个环境变量未完全配置，或 API 和 Worker 进程的配置不一致。

**解决**：
- 确认 `.env` 中 `AGENTGATE_JUDGE_PROVIDER_ID`、`AGENTGATE_JUDGE_BASE_URL`、`AGENTGATE_JUDGE_API_KEY`、`AGENTGATE_JUDGE_MODEL_ID` 四项全部配置
- 确认四项要么全设，要么全不设（部分配置会被拒绝）
- 确认 API 和 Worker 进程使用了相同的 `.env` 文件

### 11.4 验证评测流程

部署完成后，可通过以下步骤验证评测流程是否正常：

```bash
cd /opt/agentgate

# 1. 初始化评测数据（首次部署）
bash scripts/run.sh seed

# 2. 通过前端提交评测
#    打开 http://<server-ip>:5197/ ，在页面上提交评测任务

# 3. 通过 API 查看任务状态
curl http://127.0.0.1:8097/api/runs?status=pending
curl http://127.0.0.1:8097/api/runs/activity

# 4. 验证 Trace 数据（如配置了 Trace Server）
bash scripts/run.sh verify-traces
```

### 11.5 完整停止和重启

```bash
cd /opt/agentgate

# 停止所有服务
bash scripts/run.sh stop all

# 确认所有进程已停止
pgrep -f "agentgate\|celery\|redis-server.*6397\|vite.*5197"

# 重新启动（Celery 模式）
bash scripts/run.sh redis
bash scripts/run.sh api
bash scripts/run.sh worker
bash scripts/run.sh scheduler
bash scripts/run.sh web

# 重新启动（BJS 模式）
bash scripts/run.sh api
bash scripts/run.sh scheduler
bash scripts/run.sh web
```

---

## 附录：run.sh 完整命令速查

```bash
# 查看用法
bash scripts/run.sh

# 输出：
# Usage: bash scripts/run.sh {stop|api|worker|scheduler|web|redis|bank-agents|seed|verify-traces|execute-run|dispatch-due|dispatcher-type}
```

| 场景 | 命令 |
|------|------|
| 启动 Redis（仅 Celery） | `bash scripts/run.sh redis` |
| 启动 API | `bash scripts/run.sh api` |
| 启动 Worker（仅 Celery） | `bash scripts/run.sh worker` |
| 启动 Scheduler | `bash scripts/run.sh scheduler` |
| 启动前端 | `bash scripts/run.sh web` |
| 启动被测智能体 | `bash scripts/run.sh bank-agents` |
| 初始化评测数据 | `bash scripts/run.sh seed` |
| 同步执行 Run（BJS 回调） | `bash scripts/run.sh execute-run <run_id>` |
| 单次扫描到期 Run | `bash scripts/run.sh dispatch-due` |
| 查看调度类型 | `bash scripts/run.sh dispatcher-type` |
| 停止单个服务 | `bash scripts/run.sh stop api` |
| 停止多个服务 | `bash scripts/run.sh stop api worker scheduler` |
| 停止全部服务 | `bash scripts/run.sh stop all` |
