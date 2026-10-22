# 任务

你是一个实现 agent，在 Windows 仓库 `D:\Workspace\MyOwn\ST-Manager` 中，把插件系统从 v2（`frontend.entries[]`）重塑为 v3（`contributions` 三原语 + 自绘模式）。设计已定稿，工作区已包含全部设计产物（未提交）。**不要重新设计、不要征求确认**；直接实现，并把它当作一个持续 goal：每阶段自测通过后继续下一阶段，直到设计文档第 11 节验收全部通过。

如果本会话支持创建 goal，请创建并持续执行；本任务预计跨多轮，不要因为某个阶段完成就停下。

## 必读（按顺序）

1. `docs/2026-10-21-plugin-contract-v3-design.md` —— 唯一事实源：manifest 形状、落点/插槽清单、运行时 API、共存契约、迁移映射、验收矩阵。
2. `docs/adr/0001`–`0016` —— 已定决策。与设计文档冲突时，以 ADR 的边界为准；两者都沉默时，选最小、最不意外的方案并写入实现日志。
3. `GLOSSARY.md` —— 术语（贡献通道 / 自绘模式 / 插件根节点 / 共存契约 / 能力位等）。
4. `AGENTS.md` —— 仓库规范；注意「Plugin Contract v3 (design finalized, implementation pending)」一节：当前代码仍是 v2，v2 的生成物规则暂时有效。
5. 现有 v2 实现：`core/plugins/manifest.py`、`core/plugins/entries.py`、`core/version.py`、`static/js/entryRegistry.js`、`static/js/pluginHost.js`、`static/js/pluginSurfaceHost.js`、`static/js/components/pluginManager.js`、`templates/components/*` 及相关 tests。

不要修改与插件契约无关的既有未跟踪文件（`debug.log`、`run5000.log`、`docs/2026-10-16-android-apk-feasibility.md`、`docs/agents/`、`scripts/`）。

## 目标（DoD）

设计文档 §11 的验收项全部通过：

- **契约层**：`api_version=3`、`manifest_version=3`，支持集合均为 `(3,)`；`permissions → capabilities`；`frontend.entries` 删除；未知顶层/`backend`/`frontend` 键拒绝加载，节点级非法项丢弃 + 警告，`x-` 键静默忽略。
- **三原语**：菜单树（7 个落点：`context.folder`、`context.card`、`context.footer`、`batch.actions`、`commandPalette`、`dock`、`settings.nav`）、插槽（`settings.section`、`header.actions`、`card.detail.tabs`、`page.cards.toolbar`、`page.worldinfo.toolbar`、`empty.<mode>`）、命令（静态声明 + 模块/导出绑定）；隐式 `group` 由显式 `submenu` 取代；`api.entries.*` 全部删除并由 `api.contributions.*` 取代。
- **自绘与共存**：`createRoot` 内容层/portal 层、`api.overlays` 可选登记、kill switch、崩溃隔离、`overlays:force-closed` 事件、核心事件防伪造（插件 emit 核心事件警告并忽略）。
- **CSS**：作用域扫描保留；只有 `frontend.global_styles` + `ui.global_styles` 能力位才允许全局注入，且注入带 `data-plugin-style`。
- **工具链**：契约以代码为源，生成 JSON Schema、`docs/plugin-api.d.ts`、扩展 `docs/plugin-api.md`；`stm-plugin-check` 可脱离宿主仓库运行且与宿主校验规则同源；官方插件 CI 接入。
- **迁移**：`samples/plugins/hello-world` 必须迁移并通过检查；`data/plugins/{stm-pet,hello-world,stm-ai-assistant}` 同步迁移用于端到端验证；外部官方插件仓库若可访问（如 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`）一并迁移，否则产出「第三方迁移指南」并把未覆盖项写入实现日志。
- **回归**：`pytest tests/` 全绿（v2 entries 相关测试按 v3 重写，不静默删除）；生成物 `--check` 全绿；应用可启动（至少 `python -c "from core import create_app; create_app()"` 或等价冒烟）。

## 执行方式

- 建 todo list，按设计文档 §10.3 五阶段推进：①契约层 ②前端注册表/渲染 ③自绘/共存 ④原语/工具链 ⑤迁移/收尾。
- 每个阶段先补/改测试，再实现；阶段退出前跑该阶段目标测试。
- 每阶段结束，在 `docs/2026-10-21-plugin-contract-v3-implementation-log.md` 追加：完成了什么、测试结果、与设计的偏差（必须零偏差，或写明原因与取舍）。
- **不要停下来问问题。** 遇到歧义：查设计文档 → 查 ADR → 查现有测试反映的约束 → 选最小方案并记录。只有真正阻塞（例如必需文件缺失且无法推断）才停。
- 不要扩大范围：不做插件间组合、不做沙箱/强制权限、不做宿主自身 UI 的 dogfooding、不动与插件契约无关的模块。
- 不要 git commit / push，除非用户明确要求。
- 环境：Windows + PowerShell；`bash` 工具不可用，统一用 `pwsh`；Python 用 `python`，测试用 `pytest`；生成器在 `tools/`。**不要手改生成物**（`docs/plugin-api.md`、`docs/plugin-manifest.schema.json`、`docs/plugin-api.d.ts`、`static/js/utils/iconMap.js`），改源头后重跑生成器。
- 先跑一遍基线测试并记录既有失败（避免把环境问题算成回归）；之后每个阶段只跑目标子集，收尾跑全量。

## 关键实现提示（减少走弯路）

- **后端**：新增 `core/plugins/contract.py`（常量/枚举/校验的单一来源，生成器与 CLI 共用）；把 `core/plugins/entries.py` 替换为 `contributions.py`；`PluginManifest.frontend_entries` → `frontend_contributions`，`to_dict()` 快照同步；`core/version.py` 升版本并删除旧兼容分支。
- **前端**：新增 `static/js/contributionRegistry.js`（静态 manifest → 运行时树、`update/remove`、`when` 求值、排序/容量）；`entryRegistry.js` 里可复用的排序/过滤工具保留；7 个落点优先复用现有 `contextMenu`/`header`/批量/命令面板/坞栏模板；新增 `static/js/pluginSlotHost.js`；`pluginHost.js` 的 `buildApi()` 顶层键改为 `contributions`/`createRoot`/`overlays`，删除 `entries`。
- **共存**：`static/js/pluginRootHost.js` 负责内容层/portal 层与清理；`static/js/pluginOverlayHost.js` 负责登记/ESC/焦点/`closeAll`/kill switch；新宿主事件 `overlays:force-closed` 加进 `tools/gen_plugin_api_docs.py` 的 `WINDOW_EVENTS_SECTION`。
- **生成器**：扩展 `tools/gen_plugin_api_docs.py`，从 `contract.py` + `PluginAPI` + `buildApi()` 生成 schema、d.ts、`plugin-api.md`；`stm-plugin-check` 做成独立单文件脚本（可复制到插件仓库），规则与 `contract.py` 同源；所有生成物都要能在 `--check` 模式下比对。
- **测试**：`tests/test_plugin_manifest*.py`、`test_plugin_entries_contracts.py`、`test_plugin_entry_*.py`、`test_plugin_contract_values.py`、`test_plugin_api_docs.py`、`test_plugin_host_contracts.py` 等会大面积变化，先改成 v3 断言再实现。仓库没有 JS 测试框架，前端可自动化部分（API 顶层键、注册表行为、模板锚点）用现有「源码扫描式契约测试」写法覆盖（参考 `test_plugin_*_frontend_contracts.py`）。新增脚本必须加入 `AGENTS.md` 的 Generated Artifacts 表。
- **迁移**：先从 `stm-pet`（2 条入口）开始，再到 `samples/plugins/hello-world`（夹具，删掉 `api.entries.register`），最后 `stm-ai-assistant`（12 条入口，按设计文档 §10.2 的映射表逐条改）。`data/plugins/*` 是运行期安装副本，改动前先确认是否被 git 跟踪。

## 完成判定（结束时的回报格式）

1. 改动摘要（按阶段，列主要文件）。
2. `pytest tests/` 结果。
3. 全部生成器 `--check` 结果。
4. `stm-plugin-check` 对 `samples/plugins/hello-world` 与 `data/plugins/*` 的输出。
5. 未覆盖/待决事项与理由。

全部通过才宣布完成；若有失败，继续修直到通过，或明确记录唯一阻塞点。
