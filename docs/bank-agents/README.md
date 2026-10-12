# 三模式贷款智能体：安装与验收

当前操作入口见 [根目录 README](../../README.md#新机器快速开始)，使用 `open-fin-sub/agentgate` 仓库的 `integration/baibo` 分支、`frontend/` 目录及完整八进程启动器。旧日期记录仅代表当时版本。

## 新机器操作

1. 安装 Python 3.11、uv、Node.js 22.12+、npm、Redis。
2. 运行 `bash scripts/setup-bank-integration.sh`，按锁文件安装后端、贷款服务和前端依赖。
3. 将 `.env.example` 复制为 `.env` 并设置权限 600，填写自己的完整 Judge 模型连接四项；被测模型默认复用这套连接，也可以用独立 `BANK_MODEL_*` 配置。
4. 运行 `bash scripts/start-bank-integration.sh`，打开 `http://127.0.0.1:5197/`，使用行外 Login。
5. 在“测评集”搜索“核心专项”，应看到三集 v3，每集 12 样本、14 轮。评估器列表应有路径规则、三项 LLM、三项复合配置。
6. 新建任务，选择对应贷款智能体和测评集，分别用规则、LLM、规则＋LLM 检查。样本详情应可查看各轮、评估分数、路径图及完整 Trace JSON。

前端 5197、API 8097、Redis 6397、本地目录 8119、贷款服务 8107、Trace Server 8210。启动器同时管理 Worker 和 Scheduler，端口冲突时退出；可用 `--port-offset 1000` 整体偏移。脚本只关闭自己创建的进程，不删除运行数据。

## 自动真实模型验收

```bash
# 9 个任务，各运行一个低风险样本，验证三种模式和三种评估方式
.venv/bin/python scripts/run-loan-core-evaluations.py --smoke
# 全量：9 个任务，共108次样本执行、126轮交互
.venv/bin/python scripts/run-loan-core-evaluations.py
# 如果启动时使用端口偏移1000
.venv/bin/python scripts/run-loan-core-evaluations.py --api http://127.0.0.1:9097 --smoke
```

脚本仅面向行外本地地址，使用 local 令牌，不承担行内目录/令牌路由。任务使用当前数据库中的最新发布版本；已有数据库的种子内容不会被覆盖，因此升级后应先核对版本。脚本不复用固定历史任务 ID，不自动重复提交失败任务；完成后在页面或 `runtime/loan-core-acceptance/` 查看实际结果。任务状态 completed 仅代表执行结束，业务结论应查看样本通过/失败/待复核和分数。

## 历史与存储

[历史报告](../../examples/loan-core/history/index.html) 保留2026-10-07、v2、DeepSeek v4 Pro的9项专项任务：72次样本执行，67通过、5失败。历史 JSON 保留评分及失败证据，移除了 Judge 原始请求响应。它是只读参考，不自动导入本机任务列表，也不代表 v3 的测试结论。

`runtime/agentgate.db` 保存本机测评集、评估器、任务和结果；`runtime/bank-agents/` 保存合成贷款数据库及 SDK 轨迹。Trace Server 通过新增HTTP采集接口接收上报，在独立的 `runtime/trace-server/received/` 保存事件及附件，再复用上游file backend查询，不需要PostgreSQL或与发送端共享目录。`runtime/credential.key` 是本机密钥库主密钥，须与数据库一起安全备份；`.env` 和整个运行目录不随源码上传。

## 范围

贷款服务支持基础编排、LangGraph 工作流和 Skill 路由三类执行结构。工作流检查完整节点序列及分支；云虾检查 Skill 路由、实际执行及工具归属。基础/工作流没有 Skill 时应显示不适用，不能当作检查通过。

本地贷款服务执行合成数据和 `test-policy-v1`，不是客户生产工厂 Pod。行内数据库、真实网关及认证需按机构环境配置；本地启动器不替代行内部署。无真实模型配置会报错，不使用 Mock fallback。旧的浏览器验收脚本含早期数据与路径假设，本次新机验收以上述专项脚本和人工页面步骤为准。

历史说明：[2026-09-18 上游集成](upstream-sync-20260918.md)。SDK/Trace Server来源与许可边界见 `vendor/` 的 PROVENANCE.md。
