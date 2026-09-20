# Trace SDK 依赖来源

- 包名及版本：`trace-sdk==0.1.0`。
- 来源：项目所有者提供的 `tracev2-master/trace_sdk` 客户 SDK 源码。
- 纳入范围：原始 `pyproject.toml` 与 `src/`，共 22 个文件，逐文件 SHA256 见 `SHA256SUMS.json`。此次交付未修改这些源文件。
- 未纳入：客户 Trace Server、数据库、示例运行记录、构建产物、虚拟环境、客户接口原文及客户调用脚本。
- 安装：`tested-agents/pyproject.toml` 的 uv source 指向本目录；不要用 PyPI 同名包替代。
- 被测服务实际使用 SDK 的 file exporter。无需启动独立 Trace Server、Kafka 或 PostgreSQL；这些 exporter 的 Python 依赖仍按原包声明安装。
- 本次提供的 SDK 源码未附独立 LICENSE 文件。保留原有权利归属，不将 AgentGate 的 Apache-2.0 许可自动扩展到本目录，也不据此承诺第三方再分发权利。后续应由提供方补充正式许可声明。
- 手机号误伤 UUID 的处理使用被测服务 `telemetry.py` 中 SDK 公开的规则覆盖接口，未修改 vendor 源码。
