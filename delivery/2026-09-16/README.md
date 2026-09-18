# 2026-09-16 数据交付

- `agentgate.db`：通过 SQLite backup API 生成的一致性快照，不是运行中的数据库文件直接复制。包含 53 次运行、117 条 Trace、606 条评估结果、18 个评测集、10 份 Skill 静态分析报告。
- `execution-traces.jsonl`：从同一快照导出的真实执行 Trace，便于逐行查看运行记录。它不是 API/worker 的终端 stdout 日志；本次服务未将 stdout 日志落盘。
- 快照已清空凭据表（此次原表为空），检查了常见密钥、手机号、身份证格式，并通过 SQLite integrity/foreign-key 检查。真实模型凭据需使用者自行配置。
- 不含 `.venv`、`node_modules`、系统 Redis、构建缓存和本机环境文件。依赖按仓库安装说明安装。
- 浏览器 localStorage 中的任务分组、Mock 配置、启停偏好不在数据库内，不随此快照迁移；数据库中的运行及评测结果已保留。

## 使用数据

先停止本仓库服务。若 `runtime/agentgate.db` 已存在，请先将其备份到其他路径；不要覆盖正在运行或有未备份数据的数据库。将本目录的 `agentgate.db` 复制到项目的 `runtime/agentgate.db`，再按根目录 README 启动。不要导入 scheduler 状态，避免重放旧调度。

## 代码版本

仓库根目录 main 为最新代码。`snapshot-2026-09-15` 保留更新前版本，`snapshot-2026-09-16` 标记本次交付；不在根目录创建两套日期源码副本。
