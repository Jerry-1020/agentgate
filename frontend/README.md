# AgentGate 最新前端测试交接

更新日期：2026-09-20。本目录即当前新版页面的前端源码；本次交付不更新仓库中的后端和三类智能体。

## 安装与启动

推荐 Node.js 18.20.3、npm 10.7.0（Node 18 已结束维护，此处用于复现工程规范基线，不作为生产运行环境建议）。依赖以 package-lock.json 为准，不要删除锁文件重新解析。

```bash
git pull --ff-only origin main
cd frontend
# 使用 nvm 时可执行 nvm use
npm ci --ignore-scripts
cp .env.example .env.local
npm run dev
```

打开 http://127.0.0.1:5198/#/overview 。默认代理到 http://127.0.0.1:8098；测试前请启动已有后端，或在 .env.local 中将 API_PROXY_TARGET 改为测试后端地址（不带 /api 后缀）。修改环境变量后重启前端。远程 API 通过开发代理访问，无需把模型密钥放入浏览器配置。

变量说明：FRONTEND_PORT 为前端端口，API_PROXY_TARGET 为开发代理目标，VITE_API_BASE_URL 为浏览器请求前缀（默认 /api）。所有 VITE_ 变量均可能进入浏览器，禁止写入真实密钥。生产静态部署需要由网关代理 /api，Vite 的开发代理不包含在 dist 中。

### 兼容仓库原有整套启动脚本

原有 scripts/start-bank-integration.sh 检查 5197/8097，且需要 Python、uv、Redis、模型配置及智能体环境。本次不修改这些服务和脚本。若使用原有整套启动方式，请先将 frontend/.env.local 配置为以下值，然后按仓库原有后端交接文档启动：

```dotenv
FRONTEND_PORT=5197
API_PROXY_TARGET=http://127.0.0.1:8097
VITE_API_BASE_URL=/api
```

也可在仓库根目录执行 `FRONTEND_PORT=5197 API_PROXY_TARGET=http://127.0.0.1:8097 bash scripts/start-bank-integration.sh`。此时访问 http://127.0.0.1:5197/#/overview 。请勿同时启动第二个前端占用相同端口。

## 数据边界

- 任务、评测集和执行结果来自所连接的后端数据库；Git 拉取源码不会复制开发者本机数据库、历史任务或 Trace。
- 人工标注模板/评分资产和部分前端偏好当前存储于浏览器本地，同事的新浏览器不会自动继承已有记录。这些不是后端同步能力。
- 本次不上传 .env、模型密钥、node_modules、dist、运行日志、数据库或浏览器存储。
- 历史浏览器测试含固定任务 ID/旧端口，不能视为新环境的一键验收套件。

## 验证

```bash
npm run check
npm run format:check
npm run build
# 单轮/多轮 UI 回归：先启动 5198 前端；使用测试夹具，不创建后端任务
npx playwright install chromium
npx playwright test -c playwright.conversation.config.ts
```

核心依赖匹配工程规范的 87 项声明。技术栈、入口结构和安全告警见 [对齐说明](docs/frontend-stack-alignment.md)。锁定的旧依赖存在 36 项审计告警（含 2 项严重），本交付用于测试，不等同于生产安全验收；不要用 npm audit fix --force 无审查替换规范版本。

本次 UI 包含评测集草稿/版本切换与详情导出、任务和样本详情、标注页面及评估器配置。样本详情根据真实轮次数显示单轮或多轮：单轮不显示无效的轮次切换，多轮支持单轮聚焦和连续对话。已取消的看板改版不在交付范围内。
