# 行内取证与 BJS 失败处理

2026-10-08：用户授权自主 Goal；不提交、合并或推送。行内 Skill 静态分析因缺少真实版本定义接口，按用户要求暂缓，保留原有不可用提示。

## 边界与基线

- `goal/p1-demo`：复用 docs/trace/README.md 中统一 Trace/归一化后再评估的边界；该分支 trace/evidence.py 为空，不复用其实现。
- `integration/p1-new`：检查 TraceSdkFileReceiver 的文件增量接收与关联拒绝策略；其附件暂不消费，不适合本次远端完整取证，因此不复制旧接收器或替换当前 Run/Target 模型。
- 当前分支：复用 TraceServerClient、normalize_sdk_exports、行内 Pod 生命周期和现有调度失败状态机。
- 分支从更新后的 `refactor-1` 创建，再快进到已交付的 `integration/baibo`，名称 `feature/inbank-evidence-integrity`。

## 文件职责与实现顺序

1. `integrations/job_dispatchers/bjs_job_dispatcher.py`：只确认真实 BJS 成功响应；网络、HTTP、超时异常抛出脱敏错误。保留上层有界派发重试，不在传输层重试。
2. `integrations/targets/inbank/evidence.py`（新增）：校验行内 Trace 配置、逐轮 SSE 引用及远端证据关联；组装完整 Trace。必须使用配置的项目与查询地址，不用 SSE 任意 URL，不复用登录 Token 做 Trace 服务认证。
3. `integrations/targets/inbank/chatabc.py`、`yunxia.py`：保持原协议及清理逻辑，将每轮实际会话、请求、输入输出交给证据模块；删掉 output_only 轨迹生成。取证错误不重发对话。
4. `integrations/observability/trace_server.py`：保留既有查询协议，补充错误响应与安全地址校验，维持行外行为。
5. 对应测试及部署说明：覆盖两类协议、多轮隔离、缺证据、跨项目/会话、重复 Trace、失败调度、真实本地 HTTP 查询与行外回归。

## 契约与完成条件

每轮必须有唯一 SSE `trace` 引用，包含 `project_id`、`trace_id`；若携带 session_id/request_id，必须匹配本次调用。指定项目、源 Trace ID、会话、输入文本及输出必须与服务器返回的完整 SDK 证据一致。每轮源 Trace 不得复用。SDK 标准字段完成性和父子关系由现有归一化器校验。静态定义图谱不得补造成执行 Span。

显式配置 `AGENTGATE_TRACE_SERVER_URL` 和 `AGENTGATE_INBANK_TRACE_PROJECT_ID`。Trace 服务凭据使用 `AGENTGATE_TRACE_SERVER_TOKEN`；与用户会话凭据分开。完成每轮之后查询，不宣称实时流式 Span 展示。

完成条件：聚焦接口契约测试、后端全回归、贷款服务回归、前端既有回归及构建通过；提供配置和真实行内验收步骤。本机合同模拟不代表客户网关实测；若真实环境不返回此 Trace 引用或尚未上报证据，任务应明确失败。

## 完成记录

上述文件实现及配置/验收说明已完成。最终全后端1469通过、40跳过（含工具规则正反例、输入别名）；贷款服务32通过；前端82通过及lint/typecheck/build通过。新证据测试共28项，覆盖跨会话/项目/请求、缺失或重复引用、结构不完整和工具规则。真实行内网关与SDK部署尚未联调。

2026-10-08 后续交付：已将本次代码同步到本地完整验收环境，保留并备份已有数据库；三个贷款智能体的规则、LLM、混合评估共9项冒烟任务完成，各评估结果通过且有分数与远端Trace证据，LLM调用记录确认模型为deepseek-v4-pro。此为行外本地验收，不替代真实行内联调。用户随后明确授权提交并合并推送至 `origin/integration/baibo`。
