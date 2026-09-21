# 前端技术栈对齐记录

日期：2026-09-20。依据：《工程架构与编码规范（已脱敏）(2).md》的前端架构、目录规范、3.1 前端依赖清单。

## 范围和实际入口

本次工程为 `agentgate-ux-2026-09-18-v2/frontend`，对应 http://127.0.0.1:5198/ 。

运行入口：`index.html → src/main.ts → src/App.vue → Vue Router → src/views/evaluation/index.vue`。
评测集页面为 `src/views/datasets/index.vue`；公共框架为 `src/layout/EvaluationLayout.vue`。

未修改后端、数据库结构或三类智能体代码，也未实施已取消的看板改版。

## 依赖版本

文档中的 52 项运行时、35 项开发依赖，共 87 项声明均按原文保留；精确版本不自行升级，带 `^` / `~` 的声明保持原范围，由 package-lock.json 锁定实际安装版本。

| 技术 | 文档声明 / 当前声明 |
| --- | --- |
| Vue / SFC 编译器 | 3.4.31 |
| Element Plus / 图标 | 2.7.6 / 2.3.1 |
| Pinia / Vue Router | 2.1.7 / 4.4.0 |
| Axios | 0.28.1 |
| Vite / Vue 插件 | 4.5.13 / 4.6.2 |
| TypeScript / vue-tsc | 5.3.3 / 1.8.27 |
| ESLint / Vue ESLint | 8.57.1 / 9.20.1 |
| TypeScript ESLint | 8.7.0 |
| Sass | 1.77.6 |
| ECharts | ^5.4.3（锁定 5.6.0） |
| CodeMirror / Vue Flow / LogicFlow / Ace 等 | 按原文范围，完整清单见 config/frontend-stack.json |

补充依赖：fflate 0.8.3 用于已有 ZIP/Excel 导入解压限制；Prettier 3.3.3 对应架构规范中要求的格式化；@playwright/test 1.56.1 保留现有测试；@types/node 18.19.130 用于开发类型。保留 ExcelJS 的 uuid 11.1.1 传递依赖覆盖，不改文档的 ExcelJS 声明。

完整清单安装不意味着强制启用全部库：当前页面继续使用 Element Plus、Pinia 和 CodeMirror；Vuex、Naive UI、Vue Flow、LogicFlow、Ace、ECharts 等兼容或扩展依赖已按文档安装，未为了使用它们新增业务功能、重做看板或加载未使用的插件。

## 架构接入

- 视图：Vue 3 Composition API，现有页面样式和业务内容保持。
- 模块：活跃评测页面移至 views/evaluation，评测集移至 views/datasets；组件、类型、工具按模块分开；样式统一放在 styles。
- 全局状态：人工标注/评分资产、任务关联、模型预览使用 stores/modules 下的 Pinia；组件私有状态仍用 ref/reactive。
- 持久化：Pinia 持久化插件注册；已有标注存储键及容错写入逻辑保留，没有迁移、清空或冒充后端持久化。
- 路由：Vue Router 4 的 Hash 路由和 router/modules 配置实际接入主入口，保留旧链接与未保存修改提醒。未虚构后端尚未提供的权限服务。
- 请求：所有源码请求经 utils/request.ts 的统一 Axios 实例，提供 baseURL、超时和响应/错误拦截。兼容当前后端原始 JSON 与规范的 code/message/data 返回包；不自动重试写请求。
- 代理：现有 /api 继续连到 8098；同时支持规范的 /race-api → /api 代理。后端接口不变。
- 编辑器：结构化样本 JSON 使用 CodeMirror 6，显式 model-value / update:modelValue；非代码的普通文本字段保留文本输入。
- 工程校验：TypeScript strict、ESLint、Prettier 与可执行依赖一致性检查均接入 npm scripts。

src/upstream 中保留的历史壳页面及旧 EvaluationWorkspace.vue 不再是当前 HTML 入口，不另起页面或替换当前业务。规范中涉及单点登录、RBAC、服务端返回结构和智能体能力的部分，不能仅靠替换前端依赖实现，本轮未扩展这些后端功能。

## 使用与验证

在本 frontend 目录执行：

```sh
npm ci --ignore-scripts
npm run check:stack
npm run check
npm run format:check
npm run build
npm run dev
```

check:stack 同时检查文档依赖声明、锁文件、实际安装版本和 npm 依赖树，防止仅修改 package.json 而页面仍运行另一套依赖。基线在 config/frontend-stack.json，规范更新时需同步审核此文件。

已验证：依赖一致性、ESLint、TypeScript、34 项纯数据/契约测试；Node 18.20.3 + npm 10.7.0 下生产构建通过。构建仍有大于 500 kB 的分包提示（Element Plus、业务页面、按需 ExcelJS），不是构建失败。

本次页面检查不启动付费模型、不创建评测任务、不写入新的业务样本。页面读取现有后端数据；已有失败任务不会被改成成功。

浏览器检查通过：评测集列表与详情、顶部版本切换、新增样本弹窗及 CodeMirror JSON 编辑器、评估器列表、任务列表及已有任务报告、新建任务配置弹窗、人工标注模板和已完成任务会话。Pinia 迁移后原有 1 条示例标注仍显示为已标注。最终验证页无控制台 warning/error。手动样本验证未保存，关闭临时页后没有新增样本。

## 安全限制

2026-09-20 的 npm audit（包含生产、开发及传递依赖）报告 **36 项告警：2 低危、19 中危、13 高危、2 严重**。完整结果摘要见 dependency-audit-20260920.json。告警计数不等于 36 个可从当前页面直接利用的问题，是否进入运行包、是否触发相应 API，需要逐项评估。

主要涉及：

- LogicFlow engine 传递依赖 SandboxJS 的严重沙箱逃逸告警；当前页面没有导入或执行该引擎。
- Axios 0.28.1、Vite 4.5.13、xlsx 0.18.5，以及部分旧构建/Mock/Cookie 包的高危告警。
- 当前 Excel 导入仍使用 ExcelJS，并未切换到 xlsx。

为满足原文版本，本轮未执行 npm audit fix --force，也没有把对齐等同于安全验收通过。开发服务只监听 127.0.0.1，不应直接暴露为生产服务。正式发布前应先批准更新规范版本，再做依赖安全升级和回归。
