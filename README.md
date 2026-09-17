# AgentGate 工作台与三模式被测智能体

本仓库包含 Vue 工作台、AgentGate 评测后端，以及独立运行的基础编排、工作流、云虾三模式贷款测试智能体。保留已有前后端目录和历史交付文件，不使用日期文件夹复制整套工程。

**本次交付入口：[安装与端到端验收](docs/bank-agents/README.md)。**

## 快速开始

准备 Python 3.11、uv、Node.js 22/npm、Redis 和有效的支持工具调用的模型配置。

```bash
bash scripts/setup-bank-integration.sh
cp .env.example .env
chmod 600 .env
# 编辑 .env，填写模型配置；不要上传真实密钥
bash scripts/start-bank-integration.sh
```

打开 http://127.0.0.1:5197/#tasks 。启动后会创建本机数据库并初始化三个数据库评测集，共 24 条用例。前端、API、Worker、Scheduler、Redis、被测服务共同运行；Ctrl+C 关闭本次启动的服务，不删除数据。

## 目录

- `frontend/`：前端与当前真实接口接入。
- `backend/`：AgentGate API、执行调度、评估与存储。
- `tested-agents/`：独立贷款智能体、测试与依赖锁。
- `vendor/trace-sdk/`：必需 SDK 源码与来源摘要。
- `scripts/`：安装、启动、初始化、验收脚本。
- `docs/bank-agents/`：本次交付说明、架构和验证记录。
- `runtime/`：本机生成数据、日志及 Trace，不上传。
- `delivery/2026-09-16/`：保留的历史数据库及 Trace 快照，不自动恢复。

## 新机器验收

保持服务运行，在另一个终端中执行（会真实调用模型并产生费用）：

```bash
(cd frontend && npx playwright install chromium)
node scripts/accept-bank-browser.mjs
backend/.venv/bin/python scripts/verify-bank-traces.py
```

测试从前端发起新任务，不依赖开发者历史任务 ID。输入输出、页面 Trace、平台数据库、业务数据库与 SDK JSONL 互相核对。结果写入 runtime/bank-acceptance/，业务失败不会被伪装为通过。

## 重要边界

这是可执行的本地联调实现，不是客户行内完整源码或生产行为的等价复制。使用合成数据与 test-policy-v1，不连接真实银行征信或放款系统。客户工厂、文件、完整云虾协议和安全围栏仍存在待接入内容，详见交付文档。

三模式启动必须有有效模型配置，无 Mock fallback。旧 Demo 入口 start-macos.command 仍保留；旧日期能力记录是历史资料，不应覆盖本次交付说明。现有历史浏览器测试包含固定数据依赖，新机器请使用上述验收脚本。

后端来源：open-fin/agentgate 的 refactor-1，基线 e3760d16602c9423b54be968ea97839a5144d691，另有本地接入与修复。后端 Apache-2.0 许可保留在 backend/LICENSE；不要自动将其扩展至客户 SDK 和其他目录。SDK 来源声明见 vendor/trace-sdk/PROVENANCE.md。
