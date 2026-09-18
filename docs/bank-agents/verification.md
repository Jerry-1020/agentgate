# 交付验证记录 — 2026-09-17

## 交付方法

- 以远端 main 的 `141c60b7ad89a4a9d39dd8b523760eea0e23e41c` 为基线，在独立交付分支整合；未覆盖开发工作区的未提交改动。
- 前端源码直接取自当前已联调工作区，本次交付未重新设计布局。
- 保留 `delivery/2026-09-16/` 及已有历史；本次运行没有恢复旧数据库。
- SDK 原始 22 个文件与用户提供版本逐字一致；SHA256 随 vendor 目录交付。环境、密钥、客户原始资料和新运行日志不纳入提交。
- 对候选新增/修改文件进行了实际配置密钥匹配、常见凭据模式及运行目录检查，未发现真实凭据。测试中的合成私钥占位文本不是实际密钥，已人工区分。

## 独立安装及回归

在没有既有 .venv、node_modules、runtime 的独立交付目录执行安装脚本；随后从本次代码提交另行 clone，重新安装依赖，验证 SDK 不依赖仓库外的开发者路径。

| 检查 | 结果 |
|---|---|
| 根目录 uv sync --extra test | 成功 |
| tested-agents uv sync --locked --extra test | 成功，从 vendor/trace-sdk 安装 |
| frontend npm ci | 成功，npm audit 当次报告 0 漏洞 |
| 后端单元/接口回归 | 1023 通过，1 私有客户样本测试跳过 |
| 被测智能体单元回归 | 19 通过；注入模型，仅作为单元测试 |
| 前端生产构建 | 成功，保留大 bundle 警告 |
| 独立 clone 再安装 | 成功，未使用开发目录的虚拟环境或 node_modules |

有既有依赖弃用警告（Starlette、Kafka/importlib.resources）；不将其隐藏为“无警告”。只实测 macOS ARM64，不宣称跨平台全量验证。

## 新数据库真实浏览器验收

新运行未复用历史任务、未拦截 API、未回放旧 JSONL。初始化 24 条案例后，浏览器从页面创建三次任务；实际调用配置的 deepseek-v3.2，走 HTTP 被测服务和真实 SDK。

| 模式 | 本机验收 run_id | 案例 / 轮次 | 规则结果 |
|---|---|---:|---|
| base | 4f88ffff-4803-45c6-83a5-b7412f52d2b4 | 8 / 9 | 20 通过，4 不适用 |
| workflow | f2bee2f9-31a1-4008-b84b-f5e73c5fe264 | 8 / 9 | 20 通过，4 不适用 |
| cloudshrimp | 09c11d23-a13c-4ab1-9c6f-48f7bf13d693 | 8 / 9 | 20 通过，4 不适用 |

- 24 个样本页面：输入/输出/Trace 与 API 一致；页面错误 0。
- 27 轮请求：297 项 Trace/数据库/文件对照全部通过；关联 ID 未再被脱敏误改。
- 以上 ID 仅定位交付者本机验收记录，不是同事机器的预置数据。脚本每次产生新 ID。
- 12 项不适用来自对应工具期望未声明，不能当作通过，也不能据此推断业务全覆盖。
- 新生成的完整 browser.json、截图、trace-verification.json、数据库和模型附件保留在本机 runtime/，不公开上传。

## 版本与旧代码

- 更新前备份标签：`pre-bank-agents-20260917-141c60b`。
- 本次交付标签：`bank-agents-20260917`。
- 同事通常拉取 main；复现此交付可 checkout 上述交付标签。
- 旧代码在 Git 历史和备份标签；已有旧数据快照仍在原目录。

## 不在本次通过声明内

客户工厂/身份/文件生命周期、完整云虾协议、安全围栏真实语义、客户生产贷款规则及提示词等仍需正式接入和验收。新机器模型服务、网络和凭据必须有效；模型未来输出存在变化，测试应保留真实失败，而不是强行改成通过。

## 合并仓库回归与验收 — 2026-09-18

本记录对应把本仓库 main 按单后端方案合入 `open-fin-sub/agentgate` 的 `integration/baibo` 分支后的复验：原 `backend/` 增量已移植到仓库根 `src/`、`tests/`，`backend/` 目录删除，启动与验收脚本、文档路径改为指向根后端。

### 回归

| 检查 | 结果 |
|---|---|
| 根目录 uv sync --extra test | 成功 |
| 根目录后端 pytest | 1033 通过，1 跳过 |
| tested-agents uv sync --locked --extra test 后 pytest | 19 通过 |
| frontend npm ci、vue-tsc --noEmit、vite build | 成功，保留大 bundle 警告 |

### 真实浏览器验收

模型配置通过外部 `AGENTGATE_MODEL_ENV_FILE` 注入（未入库），真实调用模型并产生费用。为释放 5197/8097/6397/8107 端口，先停止了旧目录（915-NH-WEB）遗留的本机 stack；未复用历史任务、未回放旧 JSONL。

| 模式 | run_id | 案例 / 轮次 | 状态 |
|---|---|---:|---|
| base | 5ac7c22b-8d59-4667-a2c3-572cdd6566de | 8 / 9 | completed |
| workflow | a3754e46-830d-4ceb-bcc2-d79778d95a27 | 8 / 9 | completed |
| cloudshrimp | 2c4ea55d-5722-41d0-ac9b-13f766c7f47d | 8 / 9 | completed |

- 24 个样本页面查看，页面错误 0。
- 27 轮请求 × 11 项对照 = 297 项检查全部通过（trace-verification.json `passed: true`）。
- 以上 run_id 为本次新产生，脚本每次产生新 ID；完整 browser.json、截图与核对结果保留在本机 runtime/bank-acceptance/，不上传。
