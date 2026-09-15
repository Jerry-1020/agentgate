# AgentGate Web NH

智能体评测工作台，包含 Vue 前端和 AgentGate Python 后端。此仓库整理自 2026-09-15 的 5196 联调版本，保留当前功能，不包含本机数据库、真实密钥或安装依赖。

## 目录结构

```text
.
├── frontend/              # 当前 Vue 3 + TypeScript + Element Plus 工作台
├── backend/               # AgentGate API、执行引擎、存储与测试
│   ├── src/agentgate/
│   ├── tests/
│   ├── docs/
│   └── web/               # 上游自带参考界面；不是本仓库默认前端
├── scripts/               # 启动及进程管理
├── docs/                  # 当前能力边界、来源和验证说明
├── .env.example           # 模型配置模板，不含凭据
└── start-macos.command    # macOS 启动入口
```

## 快速启动

准备 Node.js 22、npm、Python 3.11 或以上、uv 和 Redis。首次安装依赖需要联网。

```bash
git clone https://github.com/open-fin-sub/agentgate-web-nh.git
cd agentgate-web-nh
bash start-macos.command
```

也可双击 `start-macos.command`。该脚本安装项目依赖，不安装系统软件；未安装 Node.js、uv 或 Redis 时会提示退出。

启动后访问 [评测工作台](http://127.0.0.1:5196/)。前端端口 5196、API 8096、Redis 6396。端口占用时脚本拒绝启动，不停止已有服务。按 Ctrl+C 结束本次启动的进程。

日志和 SQLite 数据在首次启动后生成的 `runtime/`，该目录不会提交到 Git。新环境会初始化内置贷款 Demo；原电脑创建的评测集、历史报告及人工备注不在此代码仓库中。

### 模型配置（可选）

基础 Demo 和规则评测不需要模型密钥；Skill 静态分析和模型评估需要有效模型服务。

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，取消四个配置项的注释并填写供应商、兼容接口地址、模型名称和密钥，然后重启服务。也可通过 `AGENTGATE_MODEL_ENV_FILE` 指向其他私有配置文件。文件按 shell 环境配置读取，请只使用可信内容。不要将凭据写进前端或提交到仓库。

### 分别启动服务

在五个终端中依次运行：

```bash
bash scripts/run.sh redis
bash scripts/run.sh api
bash scripts/run.sh worker
bash scripts/run.sh scheduler
bash scripts/run.sh web
```

首次手动运行前先在 `backend/` 执行 `uv sync --extra test`，在 `frontend/` 执行 `npm ci`。

## 当前能力

- 评测集与发布版本管理、评估器管理、评测任务、报告及 Trace。
- A/B 实验创建与已有结果对比。
- 后端模型驱动的 Skill 静态分析及人工复核。
- 根据失败报告展示规则改进建议，人工备注可回写来源评测集草稿。

本项目是“真实评测后端 + 内置演示智能体 + 部分前端本地能力”，不是纯前端 Mock，也不代表已接入生产业务智能体。完整限制见 [当前能力与来源](docs/current-version.md)。

## 验证

```bash
cd frontend
npm ci
npm run build
cd ../backend
uv sync --extra test
uv run pytest -q
```

前端浏览器测试位于 `frontend/tests/`，需要运行中的服务和测试数据。部分历史用例引用原联调数据库中的固定报告 ID，不能将其作为全新数据库的开箱验收；浏览器测试也可能创建测试数据，不应直接针对重要数据运行。

## 上游与许可证

后端来源：[open-fin/agentgate，refactor-1](https://github.com/open-fin/agentgate/tree/refactor-1)，基础提交 `e3760d16602c9423b54be968ea97839a5144d691`。后端本地变更仅为两处模型提示词增加简体中文输出要求。完整后端源码纳入本仓库，不是 Git 子模块。

上游后端采用 Apache-2.0，保留在 [backend/LICENSE](backend/LICENSE)。新增前端的许可范围未另行声明，请勿将上游后端许可自动视为覆盖全部新增内容。后端内的 README 和设计文档为上游资料，本仓库默认启动方式以本文件为准。
