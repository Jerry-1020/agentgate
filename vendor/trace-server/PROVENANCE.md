# Trace Server 来源

来源为项目所有者提供的 tracev2-master 压缩包。只纳入 trace_server/backend 的原始 Python 源码，逐文件摘要见 SHA256SUMS.json；未复制数据库、示例轨迹、客户配置、测试清库脚本或前端。源文件未经修改。

本地启动器设置 STORAGE_BACKEND=file 与 DATA_FILE，使用独立进程监听 loopback；读取本次贷款服务产生的真实 SDK 文件，不生成替代证据。此服务仅用于本地联调，行内仍使用配置的远程 Trace Server。

保留原有权利归属。提供的源码未附独立 LICENSE，不将 AgentGate 的 Apache-2.0 许可自动扩展到这些文件。
