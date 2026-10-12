# 贷款核心专项交付数据

当前v3测评集位于src/agentgate/demo/loan-core-datasets.json，共3集、36样本、42轮。专项评估器定义位于同目录loan-core-evaluators.json；启动器使用接收方配置的模型初始化，不携带密钥。

## 历史验收记录（只读）

可直接打开 [历史报告](history/index.html)。history/2026-10-07-summary.json与9个results.json保存2026-10-07真实DeepSeek v4 Pro验收：使用旧v2，每集8样本，共72样本，67通过、5失败。失败依据保留；已移除Judge原始请求和响应。模型测试使用合成客户，不是生产审批。

这些记录不会自动写入接收方任务列表，也不代表v3或接收方模型的结果。需要新结果时运行scripts/run-loan-core-evaluations.py；新任务有独立ID，并使用本机最新发布的测评集版本。
