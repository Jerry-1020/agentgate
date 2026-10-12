# 六类智能体主动上报 Trace

## 已实现的链路

```text
三个贷款智能体 → 原始 Trace SDK → 本机备份 → HTTP POST /api/v1/ingest
三个协议模拟体 → 明确标记的模拟事件 → 本机备份 → 同一 HTTP 采集端
                                                  ↓
                                Trace Server 独立接收目录
                                                  ↓
                           测评端按返回的 Trace ID 查询 → 页面轨迹/JSON
```

这是项目新增的 `agentgate.trace-bundle.v1` HTTP 接口，未修改原始 vendor SDK 或查询服务，不宣称是客户原生 HTTP 上报协议。当前在每轮执行结束、SDK 完成 flush 后上报完整事件及 LLM 请求附件，并非运行中的实时 Span 流。

- 贷款基础编排、工作流、云虾上报实际执行证据；真实模型请求附件和工具调用一同保留。
- 三个“本地模拟”实例仅执行合成回显。其步骤使用 `mock.*` 名称、`simulated` 来源和 `platform.simulated=true` 属性；不伪造真实 LLM 或工具调用。页面显示“模拟轨迹”。模拟失败也上传 error Trace，不能标为成功。
- 上传成功后校验回执的 Trace ID、project ID、事件数和 SHA256，再返回完成事件。网络/5xx 最多尝试3次；只重试上传，不重新执行业务。失败时保留本机备份并明确报错。
- 同 ID 同内容重传为幂等成功；内容不同返回409。身份错配、循环/孤立Span、伪造模型证据、超限数据被拒绝。请求上限10 MiB、10000事件。

## 本机验收

```bash
bash scripts/setup-bank-integration.sh
# 按根 README 配置自己的模型
bash scripts/start-bank-integration.sh
# 另一个终端：会调用真实贷款模型，创建六项新任务
.venv/bin/python scripts/verify-trace-reporting.py
```

端口偏移1000时，验收命令附加 `--api http://127.0.0.1:9097`。在任务列表搜索“Trace 主动上报”。三个协议模拟任务各两轮，三个贷款任务各一轮；共六任务、九条源 Trace。每次验收使用新的任务ID，不覆盖旧结果。

默认发送端目录是 `runtime/bank-agents/traces/`、`runtime/platform-mock/traces/`；接收端目录是 `runtime/trace-server/received/`，二者不共享读取路径。模型请求附件存储在每条接收Trace的 `spn/` 子目录。备份运行目录时应连同 `trace-report.key` 安全保管，不提交Git。

## 分机部署

接收端需部署本工程的HTTP桥接入口，准备Python依赖并配置：

```bash
export STORAGE_BACKEND=file
export DATA_FILE=/absolute/path/to/trace-received
export TRACE_REPORT_TOKEN="${YOUR_PRIVATE_TRACE_TOKEN}"
PYTHONPATH=src:vendor/trace-server/backend \
  .venv/bin/python scripts/trace-server.py --host 127.0.0.1 --port 8210
```

通过自己的TLS反向代理将HTTPS转发至此端口，须透传 Authorization 请求头。发送端配置 `TRACE_REPORT_URL=https://your-trace-host`、相同的 `TRACE_REPORT_TOKEN`；测评端配置 `AGENTGATE_TRACE_SERVER_URL` 和 `AGENTGATE_TRACE_SERVER_TOKEN`。必须是至少32字符的随机私密令牌。远程HTTP明文地址会被发送端拒绝；本机loopback允许HTTP。认证同时覆盖采集和查询，只有 `/health` 无需认证。

行内部署沿用真实目录、会话令牌和已配置的Trace查询地址；本地启动器不会把行内查询地址改到本地模拟目录。这里的Trace服务令牌与行内会话令牌是不同用途，不能互相替代。现有其他客户Trace Server若没有这个新增采集接口，不能只改URL就直接接收该格式。

## 实测范围

2026-10-08已在同机独立进程、独立存储目录完成六类端到端验收；贷款模型为DeepSeek v4 Pro。未使用外部机器或真实行内网关做网络联调，因此不声称已验证某个生产环境的TLS、代理或网络策略。

验收记录位于 `runtime/trace-reporting-acceptance/20261008-141555/`。六个任务全部完成，规则检查通过；收到9条源Trace、9份真实LLM请求附件。临时移走三个贷款样本的发送端JSONL和附件后，接收端仍能查询全部9条Trace及附件；随后原文件已恢复。匿名查询被拒绝，跨项目查询和冲突重传由回归测试验证。

| 模式 | 任务ID | 轮数 | 页面环节数 |
|---|---|---:|---:|
| 本地模拟 · 基础编排 | 1bb9ab9c-9c85-4c9c-b9e9-85727c7afd33 | 2 | 6 |
| 本地模拟 · 工作流 | 7b779ec3-234b-4cb3-9125-45cd7f5a2dfd | 2 | 10 |
| 本地模拟 · 云虾 | 20a0fbc1-c443-4d8b-bb3f-4777d470d21a | 2 | 8 |
| 贷款 · 基础编排 | b1b71b74-bb89-432c-88ba-8bf2c6b44236 | 1 | 9 |
| 贷款 · 工作流 | bb8495df-7a39-4ad4-a8cd-d892676de443 | 1 | 13 |
| 贷款 · 云虾 | f4cd2888-8141-4143-8647-25a4b2641b07 | 1 | 16 |

页面补充验收：任务 `e42246f1-630e-4227-9ae3-0e84c93e1aae` 验证两轮工作流模拟步骤均为 start → echo → end，页面显示“模拟轨迹”，点击 echo 后右侧完整 JSON 定位并高亮对应 Span。记录保存在上述验收目录的 `workflow-order.json`。
