# 简洁性 LLM 评估器端到端示例

此示例使用本地模拟 Agent 的实际回答与 Trace，交给服务端配置的真实 LLM 评分。默认执行两条合成文本，也可只运行一条；每条样本正常情况下调用一次 Judge。脚本不会读取密钥，也不提供假的 Judge 回退。

## 前提

- 工程已按行外模式启动，`AGENTGATE_AGENT_PLATFORM_MODE=mock`，API、Worker、模拟 Agent 目录和 Trace 服务均可用。
- 服务端已接入你自己的 DeepSeek 官方接口和 `deepseek-v4-pro`。凭据仅存在本机配置，不能写入示例或命令行。
- 在“评估器 → 新建 LLM 评估器”选择“简洁性”模板，选择已接入模型，保存后“发布并启用”。记下评估器 ID。

## 执行

在工程根目录运行：

```sh
.venv/bin/python examples/llm-conciseness/run.py \
  --api http://127.0.0.1:15197 \
  --evaluator-id YOUR_PUBLISHED_EVALUATOR_ID
```

只执行第一条样本，减少模型请求：

```sh
.venv/bin/python examples/llm-conciseness/run.py \
  --api http://127.0.0.1:18097 \
  --evaluator-id YOUR_PUBLISHED_EVALUATOR_ID --smoke
```

`--api` 只允许本机 HTTP 地址，可以是前端代理地址或后端地址。脚本仅支持行外本地实例，固定使用合成 Token `local`；行内测评须从已登录的页面提交，页面使用行内目录和真实会话 Token。

也可通过 `--evaluator-file examples/llm-conciseness/evaluator.json` 创建、发布并启用评估器。该 JSON 是 `/api/evaluators` 的创建请求，包含 `name`、`description` 和 `draft`。`draft` 使用 `kind: "llm_judge"`、`implementation_id: "answer_quality"`、`implementation_version: "1"`；`config.instruction` 保存完整提示词，`config.render_template=true` 启用 `{{input}}` 和 `{{output}}` 替换，`config.rubric` 可设为 `{"overall":"按照提示词中的评分标准评估。"}`，`config.model` 只包含已接入的 `provider_id`、`model_id` 和可选凭据引用，不包含密钥。

每次不带 `--resume-run` 执行都会创建新任务，产生真实模型请求。示例任务给每条样本设置 900 秒预算，覆盖 Agent 执行及所保留配置的 660 秒评审预算；脚本默认最多等待 1800 秒，可用 `--wait-seconds` 调整。等待超时后任务继续保留，脚本输出非零退出码；使用打印出的运行 ID 查询原任务：

```sh
.venv/bin/python examples/llm-conciseness/run.py \
  --evaluator-id YOUR_PUBLISHED_EVALUATOR_ID \
  --resume-run YOUR_RUN_ID --smoke
```

恢复时保持原来的 `--api` 和评估器 ID。脚本只读取运行已固定的评估器版本和样本选择，不要求模型当前仍已接入或评估器仍启用，也不会创建数据集或评估器；恢复时 `--smoke` 不改变已有选择。

## 保留的实例与判断标准

- `dataset.json` 是可导入的标准 AgentGate 数据集，稳定 ID 为 `llm-conciseness-example`。首次执行导入 v1；后续执行复用并核对版本身份及完整内容指纹，不覆盖已有数据。
- 评估器、测评任务、固定的评估器版本、样本执行轨迹和完整 Judge 请求/响应保留在本地数据库。页面“测评任务”可查看“简洁性 · 真实 LLM 端到端示例”。
- `results.json` 在实际执行后生成，包含运行 ID、样本得分、原因、模型、请求 ID 和请求指纹。运行未完成、评分为空、模型报错或缺少真实请求证据时，`end_to_end_verified` 为 `false` 且脚本退出码为 1。成功时该值为 `true`，退出码为 0。
- `--output PATH` 可保留多次运行的独立摘要。默认摘要展示最近一次执行；历史任务继续保留在数据库。

模拟 Agent 会给回答附带“模拟回复”标识并回显输入，因此简洁性得分可能较低。样本 `outcome: "fail"` 表示真实模型认为回答未达标；这仍是正常评分结果。`outcome: "error"`、超时和缺失结果始终判定为验收失败，不会当作通过。

脚本提交 `POST /api/agent-platform/evaluations`，使用 `evaluator_refs` 固定已发布版本；通过 `/api/runs/{id}/status` 和 `/api/runs/{id}/samples` 读取实际持久化结果。

离线验证脚本的快照身份、恢复查询和失败判断，不连接任何服务或模型：

```sh
.venv/bin/python examples/llm-conciseness/test_run.py
```

## 本机实际验收记录（2026-10-15）

浏览器已实际完成新建页面、打开模板弹窗、应用“简洁性”、选择 `deepseek-v4-pro`、保存草稿、发布启用、重新打开详情，以及在测评任务表单中选中该版本。

- 已保存评估器：`cee497c8-acc0-4ecf-a670-1c175ab34c9c`，名称“简洁性”。`v1` 为页面直接创建的 180 秒评审配置；`v2` 仅将评审超时延长至 660 秒，当前启用，配置已导出为 `evaluator.json`。两版提示词、模型及评分标准相同。
- `14badec3-7dc3-49ce-a8c1-3d8ac7eccead`：使用 v1，Agent 输出与 Trace 已保存，真实评审在 180 秒后返回 `JudgeModelTimeout`，没有得分。摘要见 `results-pro-180s.json`，页面截图见 `result-timeout.jpg`。
- `26a30d39-6441-47de-a2c5-f448923b0222`：使用 v2，但原任务总预算仍为 300 秒，被运行回收检查判为失败（`Execution worker exceeded its recovery deadline`）。摘要见 `results-task-timeout.json`。示例脚本已修正样本预算为 900 秒。
- `571c08d9-6337-4efc-a0f0-e5c958ca2f0d`：使用 v2 与修正后的任务预算，确认官方故障后取消等待，状态保存在 `results.json`。
- [DeepSeek 官方故障记录](https://status.deepseek.com/incidents/7116348214287)显示 2026-10-15 的 API 中断影响 Pro 和 Flash；验收时仍在修复。所有报告的 `end_to_end_verified` 如实为 `false`，**真实评分端到端验收尚未完成**。
- 后端回归共 2434 项通过、56 项跳过（初次受沙箱禁止监听端口影响的 20 项，放行后单独重跑通过）；前端 96 项单元测试、类型检查、lint 和生产构建通过；示例离线测试 4 项通过。

界面截图：[新建入口](create-chooser.jpg)、[空白表单](create-form.jpg)、[选中模板名称](selected-template.jpg)、[表单内模板弹窗（自定义置灰）](templates.jpg)、[已发布评估器](evaluator.jpg)、[任务选择](task-selection.jpg)。服务端实例和所有运行保留在本机数据库中，可直接查看和复查；上述 JSON 与脚本支持重新部署后创建同样的实例。

官方服务恢复后，在当前本机实例运行以下命令重新验证一条样本，保留新任务和结果：

```sh
.venv/bin/python examples/llm-conciseness/run.py \
  --evaluator-id cee497c8-acc0-4ecf-a670-1c175ab34c9c --smoke
```
