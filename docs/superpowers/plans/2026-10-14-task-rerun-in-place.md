# 单任务原配置重跑 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** 保持任务身份，以新运行完成原配置重跑，补测试并本地部署。

**Architecture:** 任务保留当前及历史运行 ID；专用 SQLite/MySQL 事务以 source_run_id 为前置条件切换执行。前端复用只读弹窗和现有任务页面，保持稳定任务路由。执行引擎不变。

**Tech Stack:** FastAPI/Pydantic/SQLite/SQLAlchemy；Vue/Pinia/Playwright。

**Spec:** docs/superpowers/specs/2026-10-14-task-rerun-in-place.md

## Global Constraints

- 单任务、原配置、终态重跑；运行 ID 必须新建，任务 ID 不变。
- 不改云虾/BJS/Pod/Trace 执行适配器；不改 SQL 表结构。
- 在独立功能分支实施；经用户授权提交、推送并创建 PR，不自动合并。

## Review Focus

- 重复/过期提交不能留下多余运行。
- 跨团队请求不能派发任务。
- 删除覆盖所有历史，不能影响其他任务。
- 刷新和详情导航不能显示旧运行或增加任务行。
- 原快照、凭证引用、静态分析关联保持一致。

### Task 1: 后端原子重跑

**Files:** domain/evaluation_task.py、storage/{repository,sqlite,mysql}.py、application/evaluation_task_management.py、server/routes/evaluation_tasks.py；tests/test_task_rerun.py、tests/storage/test_contract.py。

**Interfaces:** `previous_run_ids`；`save_task_rerun(task_id, source_run_id, rerun, *, user_team_id) -> EvaluationTask`；任务级 rerun POST。

- [x] 先补 ID/名称/时间、快照/证据保留、重启、重复重跑、状态边界、分组拒绝、团队隔离、并发、普通保存及删除的测试。
- [x] 运行 `.venv/Scripts/python.exe -m pytest -q tests/test_task_rerun.py`，新接口未实现时失败。
- [x] 实现领域字段、事务、应用服务和路由。
- [x] 运行后端全量测试和 SQLite/MySQL 同一套存储契约；真实 MySQL 未配置，相关契约跳过。

### Task 2: 列表和详情

**Files:** task-links.ts、evaluations.ts、TaskList.vue、RerunDialog.vue、TaskResults.vue、OverviewMetrics.vue、evaluation/index.vue；task-rerun.spec.ts、configuration-flow.spec.ts。

**Interfaces:** task link 的 previousRunIds/createdAt；弹窗 taskId + 原 run ID；created 通知切换最新详情。

- [x] 补真实组件测试，先确认入口缺失/原请求不符导致失败。
- [x] 实现终态单任务按钮、只读预览、source_run_id 提交、防双击、稳定任务导航、历史隐藏和任务 ID 删除。
- [x] 运行 lint、类型检查、单元测试、构建和 UI 验证；记录原基线失败。

### Task 3: 本地验收和审查

**Files:** runtime 内忽略的本地演示启动器；功能说明。

- [x] 启动 API/前端和独立演示数据库，使用真实 RunEngine 执行合成数据。
- [x] 连续两次重跑，验证单条任务、稳定 task_id、新 run_id、历史可读取；记录截图和控制台。
- [x] 最终独立代码审查，重要问题通过失败测试修复。
- [x] 提供 URL、测试证据、未联调环境；提交、推送及创建 PR 需用户授权，不自动合并。

## 验证记录

- 后端相关测试：58 passed / 18 skipped（未配置 MySQL）。
- 前端单元测试：89 passed；界面回归：15 passed；lint/typecheck/build 通过。
- 最新提交前后端全量复验（UTF-8）：1972 passed / 21 failed / 56 skipped。失败项此前均已在原始提交 `753bfa0` 复现，涉及 Windows 符号链接权限、POSIX 进程/文件模式、Bash 启动，以及会影响失败阶段判定的 Trace 同时间戳排序。后者存在不稳定性，因此不同轮次失败数量会变化；这不代表全量验收通过。用户了解该结果后明确授权提交 PR，本次不混入这些问题的修复，不自动合并。
- 本地页面：http://127.0.0.1:5198/，选择行外Login；独立演示数据库，不连接真实 MySQL、BJS 或行内平台。
- 界面测试命令：`npx playwright test -c playwright.config.ts task-rerun.spec.ts`；可通过 `PLAYWRIGHT_CHROME_PATH` 使用本机 Edge。
- 用户确认弹窗文案：将该任务按照原始配置重新运行一次，该任务原始运行结果保留。
- 用户确认弹窗标题：重新运行当前任务；底部按钮：开始测评。
