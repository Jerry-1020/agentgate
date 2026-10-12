# 行内完整取证与真实调度验收

本次补齐行内 Trace 查询和 BJS 失败处理。Skill 静态分析按用户要求暂缓：真实行内版本定义接口尚未提供，不使用本地 `/web/agent/capabilities` 扩展冒充。

## 配置

已有行内网关、数据库、登录认证、执行器配置保持不变，另外设置：

```dotenv
AGENTGATE_AGENT_PLATFORM_MODE=inbank
AGENTGATE_TRACE_SERVER_URL=https://your-trace-host
AGENTGATE_INBANK_TRACE_PROJECT_ID=your-project-id
AGENTGATE_TRACE_SERVER_TOKEN=your-private-trace-query-token
```

将示例替换为真实配置。Trace URL 只允许 origin，不含路径、账号或查询参数；服务不要求认证时可不设查询 Token。该 Token 与行内登录令牌独立，不会把用户会话令牌发送给 Trace Server。必须显式提供项目 ID 和 URL；配置缺失会在创建 Pod 前失败。行外使用原有本地配置，不读取行内项目 ID。

## 被测平台需满足的协议

ChatABC 基础编排、工作流和云虾每轮正常响应都必须携带唯一的 SSE 引用：

```text
event: trace
data: {"project_id":"your-project-id","trace_id":"source-trace-id","session_id":"actual-session-id","request_id":"actual-request-id"}

```

该帧须在 `done` 前发送，且证据已经可查询。`project_id` 和 `trace_id` 必填；可选的 session_id/request_id 若出现必须匹配本次实际调用。项目/Trace 标识为最多128字符的字母数字、点、下划线和连字符，首字符为字母或数字。SSE 中的 URL 不参与请求寻址。

测评端读取以下既有 Trace Server 查询接口：

```text
GET /api/v1/projects/{project_id}/traces/{trace_id}
GET /api/v1/projects/{project_id}/traces/{trace_id}/llm_requests
```

详情响应沿用仓库 `TraceServerClient` 的 camelCase 契约：`trace`、`spans`、`observations`；模型附件响应为 `items`。根 Trace 要有匹配的项目、Trace、sessionId、agentName（本次创建的 Pod 名）、输入文本和最终回答；状态为 success，spanCount 为实际完整 Span 数量。每条 Span 具有有效时间、状态和父子关系。实际返回的 LLM 请求附件会保留。缺失、冲突或非法证据明确报错，不回退为 output_only。各轮使用不同源 Trace ID。

SDK 支持的 agent/chain/llm/tool/retriever 等原始步骤会保留，Skill/工作流的名称和层级以远端实际 Span 为准；不能由静态图谱猜测执行路径。只有服务实际提供的字段可以展示，不宣称恢复上游查询面未暴露的数据。云虾继续保留 SSE 返回的意图、槽位和 workflow_calls，不把它们伪造为内部执行 Span。

本次没有修改客户 Agent 的代码，也没有让未上报的 Agent 自动具备上报能力。如果真实网关未实现上述 Trace 引用或查询契约，需要平台方提供真实协议并接入。网络取证发生在每轮回答后，不是运行中的实时 Span 流。查询失败不重放对话，Pod 仍按既有生命周期清理。

## 可复现的本机契约验收

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_inbank_evidence.py tests/test_target_execution.py \
  tests/test_target_execution_factory.py tests/test_trace_server_client.py \
  tests/test_bjs_dispatcher.py tests/test_bjs_scheduling.py tests/test_bjs_execution.py
```

执行测试使用模拟行内网关及独立的本地 HTTP Trace 查询服务，覆盖基础编排、工作流、云虾、多样本多轮、LLM 附件、父子关系、错误会话/项目/输入/输出、不完整证据、服务不可用和 Pod 清理。这是接口契约验收，不代表真实行内平台通过。

## 真实行内验收

1. 配置自己的行内服务；用有效行内 Token 登录，选择真实智能体、版本和云虾分支。
2. 使用两轮且输入不同的样本，串行执行、重试0；先使用最终输出评估器验证连通性。
3. 在样本详情查看每轮下的模型和工具等内部环节及 JSON；应包含 `inbank.evidence_mode=trace_server`、实际源 `trace_sdk.trace_id`，`trace_sdk.replay=false`。点击节点应定位对应 JSON。
4. 根据真实返回的工具/路径证据配置过程规则；不能用本地贷款工具名称直接假设客户平台行为。
5. 测试环境中让一条 Trace 引用失效或让查询服务拒绝访问，确认任务失败且不会重复执行业务对话。只有回答、没有内部证据不算验收通过。

## BJS 失败验收

真实响应 `{code:"0",message:"success"}` 才确认受理；网络异常、超时、HTTP 错误、非法 JSON 和业务拒绝均报错。不再生成模拟成功响应，也不将响应中的敏感正文输出到错误信息。

传输层不重试；现有调度器使用同一 Run ID 有界重试：首次失败进入 WAITING，达到 `AGENTGATE_MAX_DISPATCH_ATTEMPTS` 后为 FAILED。超时只能表示受理未确认，无法证明远端没有执行；BJS 端应按 taskId 去重，不能声称跨系统 exactly-once。远端取消接口仍未定义，本次不宣称支持远程取消。

在测试 BJS 地址返回503、超时和业务拒绝，分别确认任务不会被误判受理；然后恢复服务，核对同一 taskId 的真实执行状态。不要在生产环境人为制造故障。
