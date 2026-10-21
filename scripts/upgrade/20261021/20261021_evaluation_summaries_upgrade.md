# 测评摘要功能升级操作说明（2026-10-21）

## 适用范围与发布顺序

本文用于升级已有 AgentGate 数据库，使其支持测评总览和任务列表的摘要接口。后端、迁移与回填脚本、前端必须来自同一套已验证的发布版本。旧接口继续保留。升级和历史回填不需要执行 Agent、LLM 或 BJS 任务。

发布顺序：**进入维护状态并备份 → 增量升级数据库结构 → 启动新版后端及工作进程（仍禁止业务流量和任务写入）→ 历史数据回填 → 验证 → 发布新版前端并恢复业务流量。**

回填后不能再运行旧版写入程序，因为它们不会维护新增的摘要数据。本文是操作说明，不代表已经授权执行生产环境升级。

**不要对已有生产数据库执行 `../../sql/init.sql`。** 该文件用于全新数据库初始化，已经包含本次新增结构，不需要单独生成 `init20261021.sql`。此前提到该合并文件的旧注释已不再适用。

## 一、升级准备、暂停写入与备份

1. 确认发布版本、实际数据库主机/库名/类型、服务管理方式、API 基础地址，以及所有可能写入数据库的程序，包括 API 实例、工作进程、调度器和管理脚本。
2. 禁止创建任务及其他写入，等待正在执行的工作结束，再通过部署环境正常的服务管理工具停止写入程序。不要强杀正在执行的任务，也不要照搬开发环境的进程 PID。最终检查通过前保持维护状态。
3. 按 DBA 认可的方式完成 AgentGate 全量一致性备份，包含原始数据集、任务与运行记录、评测结果、Trace 和关联数据。记录行数及备份校验值，并在批准的环境验证恢复能力。同时保留旧版可部署程序和受保护的配置。只备份新增摘要表是不够的。
4. 对于 MySQL/InnoDB，常见导出参数为 `--single-transaction --skip-lock-tables --no-tablespaces --set-gtid-purged=OFF`。必须明确核对目标数据库和表清单，通过批准的凭据管理方式提供密码，并确认命令成功。不要在命令参数、日志或本文中暴露密码。TDSQL 应使用行内支持的备份方式，不要直接套用未经验证的本地命令。
5. 记录原始任务、运行、结果和 Trace 的数量与内容哈希，供回填后比较。回填只更新派生查询字段和摘要数据，不改动原始执行证据。

确认数据库后，执行以下 MySQL 只读预检查：

```sql
SELECT status, COUNT(*) FROM agentgate_runs GROUP BY status;

-- 继续升级前必须为零；非零时应先与数据负责人确认处理方式。
SELECT COUNT(*) AS dangling_links
FROM agentgate_evaluation_task_runs a
LEFT JOIN agentgate_evaluation_tasks t ON t.id_key = a.task_key
LEFT JOIN agentgate_runs r ON r.id_key = a.run_key
WHERE t.id_key IS NULL OR r.id_key IS NULL;

SELECT COUNT(*) AS tasks_without_links
FROM agentgate_evaluation_tasks t
WHERE NOT EXISTS (
  SELECT 1 FROM agentgate_evaluation_task_runs a WHERE a.task_key = t.id_key
);
```

检查缺失关联、无运行关联的任务，以及原始记录内容与关联关系的一致性。不同实体的总数不必相等：A/B 任务、历史运行和独立运行采用不同计数规则。

若存在 `pending`、`scheduled`、`running` 状态的工作，或无法解释的数据不一致，应暂停升级。不要复制开发环境清理过的 ID，也不要直接删除生产环境孤立记录。如需清理，应先导出准确的原始行，取得数据负责人的决定，再通过限定范围的事务处理。备份无法恢复在备份之前就已缺失的运行记录。

## 二、执行数据库结构迁移

在新版仓库根目录中，使用该版本已安装的 Python 环境执行。以下命令中的 `../../../.venv/bin/python` 和 `/secure/agentgate-production.env` 为示例，请将环境文件路径替换为实际受保护的部署配置路径。执行 `--apply` 前，先检查输出中的目标数据库。不要打印环境文件内容。

```bash
.venv/bin/python scripts/migrate_evaluation_summaries.py --check --env-file /secure/agentgate-production.env
.venv/bin/python scripts/migrate_evaluation_summaries.py --apply --env-file /secure/agentgate-production.env
.venv/bin/python scripts/migrate_evaluation_summaries.py --check --env-file /secure/agentgate-production.env
```

逐条执行，并分别保存标准输出、错误输出和退出码。出现非预期失败时立即停止。最终 JSON 中必须满足 `pending_before: []`；仅退出码为 0，并不表示没有待迁移项目。由一名维护人员统一执行，避免并发重复操作。

工具会检查现有数据库对象，并补充缺失且兼容的结构：

| 数据库对象 | 新增内容 |
| --- | --- |
| `agentgate_run_summaries` | 展示字段、来源哈希、允许为空的得分（`DOUBLE`）及完成摘要元数据 |
| `agentgate_run_case_progress` | 运行与用例的关联及用例完成状态 |
| `agentgate_run_expected_evaluators` | 运行与预期评估器的关联；运行状态仍保存在运行记录中 |
| `agentgate_evaluation_tasks` | `name`、`kind`、`first_run_key` |
| `agentgate_evaluation_task_runs` | `is_current`、`position` |
| `agentgate_dataset_versions` | `sample_count` |
| `ix_task_runs_current_position` | `(task_key, is_current, position)` 索引 |

`20261021_evaluation_summaries.sql` 用于审核 MySQL/TDSQL 的 SQL 变更。原始 `ALTER` 和 `CREATE INDEX` 语句在部分执行成功后不能盲目重复运行，优先使用带结构检查的 Python 迁移工具。

如果 DBA 要求仅执行 SQL，应先清点现有数据库对象，只执行尚未应用且兼容的语句，随后使用工具的 `--check` 确认。MySQL DDL 可能部分提交，并可能产生元数据锁；应安排维护窗口并监控阻塞。不能依靠一个事务回滚整个结构升级。

### SQLite 的处理方式

不要将 MySQL SQL 文件用于 SQLite。先暂停写入，通过 SQLite 备份 API 或部署环境认可的一致性备份方式完成备份，并考虑 WAL 文件的影响，然后执行：

```bash
.venv/bin/python scripts/migrate_evaluation_summaries.py --check --sqlite /absolute/path/agentgate.db
.venv/bin/python scripts/migrate_evaluation_summaries.py --apply --sqlite /absolute/path/agentgate.db
.venv/bin/python scripts/migrate_evaluation_summaries.py --check --sqlite /absolute/path/agentgate.db
```

必须使用实际存在的数据库路径；迁移工具会拒绝不存在的文件，避免误建数据库。

## 三、部署后端并回填历史数据

通过部署环境的服务管理工具，使用原生产配置启动新版后端和工作进程。此时仍应禁止业务流量和任务提交，保持调度写入暂停。检查健康状态，以及 OpenAPI 中是否存在以下新接口：

- `GET /api/evaluation-overview/summary`
- `GET /api/evaluation-task-summaries`

部分部署会将 OpenAPI 或健康检查响应包装在标准 `data` 字段内。应检查实际响应结构，不要因为最外层没有 `paths` 就认定启动失败。

预先创建受保护的报告目录，例如 `/secure/upgrade-20261021/`，然后依次执行：

```bash
.venv/bin/python scripts/backfill_evaluation_summaries.py --check --env-file /secure/agentgate-production.env --report /secure/upgrade-20261021/backfill-before.json
.venv/bin/python scripts/backfill_evaluation_summaries.py --apply --env-file /secure/agentgate-production.env --batch-size 50 --report /secure/upgrade-20261021/backfill-apply.json
.venv/bin/python scripts/backfill_evaluation_summaries.py --check --env-file /secure/agentgate-production.env --report /secure/upgrade-20261021/backfill-after.json
```

SQLite 环境将各命令的 `--env-file ...` 替换为 `--sqlite /absolute/path/agentgate.db`。

不要直接使用 shell 的 `&&` 串联这三个步骤：首次审计可能因为预期的摘要缺失而返回退出码 1，导致后续回填被跳过。应先阅读首次报告，区分正常的摘要缺失、连接错误和原始数据损坏。**回填执行和最终审计都必须退出码为 0，且报告中 `failures: []`。**

**仅执行结构迁移不会自动回填历史摘要。** 回填读取数据集版本、运行记录、任务关系和已有结果，使用现有评分算法重建查询字段、用例/评估器关联及已完成运行的得分。它不会执行 Agent 或 LLM，不改变运行状态，不生成虚假的成功结果，也不会给未完成运行伪造最终得分。原有结果和 Trace 内容保持不变。

回填按键游标分批处理，默认每批 50 个对象；来源数据冲突最多尝试三次。已经存在摘要的对象也会重新构建，因此重复执行可以得到一致结果，但不代表不会再次写入。

若执行中断，应保存报告和日志，排除原因后重新执行 `--apply`，再执行 `--check`。不要通过删除原始结果或摘要结构来掩盖失败。在相应团队范围的摘要尚未就绪时，请求可能返回 503 `evaluation_summary_not_ready`；审计完成前不要恢复用户访问。

## 四、验收与恢复业务

- 将原始数量和内容哈希与备份基线比较，仅扣除另行批准的数据清理。使用现有报告评分算法核对历史已完成运行的得分，包括缺失结果和评估异常场景。任何无法解释的差异都需要排查。
- 携带生产环境的认证信息和团队请求头验证新接口：团队 A 只能看到 A 的任务及总览，团队 B 只能看到 B 的任务及总览，无数据团队应返回零。同团队用户共享团队范围；空团队不是查询所有团队的通配符。本次优化不改变已有的可信身份请求头契约。
- 根据当前运行、历史运行和独立运行的规则核对总数，不要将任务数量直接等同于运行数量。检查分页、搜索、日期筛选、详情跳转和相关任务类型。创建、取消、重跑和删除测试只能使用经过授权的专用测试数据。
- 后端就绪后再部署配套前端。总览首次加载应请求两个摘要接口，分别获取统计和最近 6 条任务；任务列表应只请求一页摘要，默认每页 20 条，不再逐运行请求报告或状态。
- 每个页面先预热一次，再测量三次数据加载并渲染完成的耗时，记录响应字节数、请求数量和数据规模。区分接口响应耗时、浏览器数据就绪/渲染耗时，以及每五秒的正常轮询请求。本地测试结果不代表生产环境性能保证。
- 有控制地恢复新版调度器、工作进程和业务流量。如已获批准，执行一条专用冒烟测试任务，确认新完成的运行会同步更新摘要，并监控错误、503、查询延迟和数据库负载。保留备份、报告和发布版本标识。

## 五、失败处理与回退

迁移前，备份或预检查失败就应停止。DDL 部分完成后，应检查实际结构，仅继续缺失且兼容的变更，保留原始数据。

回填失败后保持维护状态，根据报告中的 ID 和错误类型排查；不能仅凭 HTTP 健康检查成功就宣布可以恢复业务。

前端回退时，可发布上一版兼容的前端产物，保留新增后端接口和数据库结构。后端回退前，必须验证旧版程序与增量结构的兼容性。旧版写入程序不会维护摘要，不能让新版前端继续使用可能已经过期的摘要数据。应恢复旧版前端并暂停摘要接口的使用；重新升级后，先重建并审计摘要，再恢复使用。

破坏性的数据库恢复需要数据负责人/DBA 单独批准，并核对备份之后的全部写入。不要自动删表、删列、执行初始化 SQL 或覆盖业务数据。应使用已验证的备份和部署环境的恢复方案。
