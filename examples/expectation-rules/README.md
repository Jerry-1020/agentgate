# 期望结果：三类规则可复现示例

此示例保留一个两轮样本、两份固定合成 Trace，以及真实内置规则的执行结果。它验证已发布数据集中的 `state`、`tool_argument`、`output` 会被对应规则识别和计算；所有执行使用新建的临时 SQLite，不需要启动服务、Agent 或 LLM，也不读取现存数据库或环境凭据。

在工程根目录执行：

```sh
.venv/bin/python examples/expectation-rules/run.py
```

默认更新本目录的 `results.json`；也可以指定 `--output /tmp/expectation-rules-results.json`。成功输出 `offline_rules_verified=True`，退出码为 0。结果含 2 组 × 3 个评估器，每个评估器包含 2 轮检查：`pass` 组全部通过，`fail` 组全部失败。预设失败用于验证规则确实发现不符合期望的证据，因此仍属于示例验收成功。

## 文件和页面用法

- `dataset.json`：标准 `agentgate.dataset` 文件，可导入数据集页面。样本包含名称、输入、分类、难度、标签、初始状态、样本/轮次备注、扩展字段、已有工具调用和执行路径期望。
- `traces.json`：固定合成证据，包含每轮输出、状态，以及同一工具的多次调用。它不是外部智能体的实测记录。
- `results.json`：运行脚本生成的规则结果，保留数据集内容指纹、评估器版本、轮次 ID、期望 ID、实际值、期望值及失败原因。它是离线规则验收记录，不是在线测评任务记录。

导入后，在样本编辑器查看“期望结果”，或在“添加期望”中按下表填写。在线提交测评时，还需选择对应评估器；期望条目本身不会自动添加评估器。

| 期望 | 评估器 ID | 本例配置及通过证据 |
| --- | --- | --- |
| 最终状态 `state` | `final-state` | 第一轮 `decision` 属于给定对象集合；第二轮 `decision.details` 等于包含布尔、数字、数组、对象和 null 的 JSON 对象 |
| 工具参数 `tool_argument` | `tool-arguments` | 第一轮 `lookup_customer` 的最后一次调用中 `arguments.customer.id` 等于 `C-100`；第二轮每次 `approve_loan` 的 `arguments.request.limit` 都在 100000～150000 内 |
| 最终输出 `output` | `final-output` | 第一轮 `answer` 匹配 `^已提交复核$`；第二轮路径留空，用 JSON Schema 检查完整输出 |

`state.path` 从最终状态读取；`tool_argument.path` 从工具 span 的 `attributes` 读取，因此本例路径包含 `arguments.` 前缀；`output.path` 从最终输出读取，留空表示整个输出对象。路径使用点号分隔嵌套对象字段。

失败 Trace 保留同样的结构，分别改变状态、工具参数和输出。第二轮状态把布尔 `true` 改成字符串 `"true"`，用于验证 JSON 类型没有被当成普通文本丢失。

## 自动验证

```sh
.venv/bin/python -m pytest \
  tests/test_dataset_expectation_contract.py \
  tests/test_expectations.py \
  tests/test_rule_state.py tests/test_rule_tool_use.py tests/test_rule_output.py \
  tests/test_rule_observations.py tests/test_rule_operators.py \
  tests/test_rule_json_schema.py tests/test_evaluator_executor.py -q
```

契约测试通过进程内 HTTP 接口新增、修改、回读草稿、发布、回读发布版本，再调用三个真实内置规则。另有通过/失败两组任务回归，使用 `RunManagement` 创建并持久化任务快照，交给 `RunEngine` 经本地合成 Trace 适配器执行，最后从 `ResultReader` 读取持久化报告。创建任务后再发布 v2，原任务仍执行固定的 v1 样本。

测试断言所有样本和多轮字段完整保留、发布版本不被后续编辑改变、期望 ID 与每轮结果正确关联，并验证工具的 `first`、`last`、`any`、`all` 四种选择。

对象及包含对象的数组在领域对象中保持不可变；`equals.expected` 和 `one_of.allowed` 只在 JSON 序列化时恢复成标准对象/数组，覆盖 HTTP、持久化、内容指纹和导出所需的边界。

工具没有调用时，参数规则结果是“不适用”；需要强制调用时同时选择 `required-tool`。行内仅返回 `output_only` 证据时，依赖轨迹的状态和工具参数规则跳过，最终输出规则仍执行。线上被测智能体目录与 Token 仍按行内/行外模式选择；本示例仅回放合成证据，无目录查询或测评提交。
