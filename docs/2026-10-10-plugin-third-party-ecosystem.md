# 第三方生态与官方插件（追加篇之二）

> 本文是 [2026-10-10-plugin-entry-unification-design.md](2026-10-10-plugin-entry-unification-design.md) 的追加篇之二。
> 触发条件：用户澄清（m00690，逐字）——「目前有的两个插件，一个是hello插件，用来测试插件系统功能的，一个是ai助手插件，是打算作为官方插件发布的，但是插件不一定都是我写的，未来是会开放给其他人的，ai助手插件目前设计上也不是内置，计划添加到官方列表中（暂且还没加），用户可以选择是否安装。你的设计应该不会破坏这一点把」。
> 状态：**设计草案，未实现**。
> 文档优先级：**本篇 > 追加篇一 > 主文档**（冲突时以优先级高者为准）。
>
> **修订记录（m00758）**：用户补充三条事实并据此修订本文——
> ① AI 助手源码在**独立仓库** `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`（remote `https://github.com/Dadihu123/ST-Manager-AI-Assistant.git`），`data/plugins/stm-ai-assistant/` 只是手动安装过来的副本 → 修订 §1 表；
> ② **允许第三方插件使用宿主图标名**（项目开源，第三方可直接读源码开发）→ **反转 §3.4**，并暴露出「授权已给但机制不存在」的新问题（§3.4 新增小节）；
> ③ 据此重排 §4 优先级、修正 §5 反目标、更新 §6 未决问题。

---

## 0. 直接回答

**不会破坏。而且这个前提本来就在设计里。**

主文档 §12 风险 4 的核心设计是：**坞只从 `/api/plugins/list` 的插件列表渲染**（`static/js/pluginHost.js:112-145` 已有 `entry.enabled === false` 过滤），入口声明来自 manifest（`frontend.entries`），与「插件从哪来」完全无关。装了就渲染，卸载就消失，未安装就不存在。

具体到三条：

| 你的要求 | 设计是否满足 | 机制 |
|---|---|---|
| AI 助手不是内置 | ✅ | 入口声明在 manifest 里，不在宿主模板/JS 里；宿主对 `stm-ai-assistant` 这个 id 零硬编码 |
| 加入官方列表，用户可选安装 | ✅ | catalog 机制不动（`core/plugins/catalog.py`、`installer.install_from_catalog`），入口契约是 manifest 层的，catalog 只管「从哪下载」 |
| 用户可不安装 | ✅ | 未安装 → `/api/plugins/list` 里没这条 → 坞里没槽位、命令面板搜不到、总览页不列 |

**反而强化**：追加篇一里那批「发布前必须做」的事（契约冻结、原语库、严格校验、命名统一），原本的理由是「省自己的返工」。有了第三方，理由升级为「**别人要靠这份契约写代码**」——不做的话代价从「自己返工」变成「生态起不来」。

### 0.1 m00758 三条补充带来的净变化

| 补充信息 | 原判断 | 修订后 | 影响面 |
|---|---|---|---|
| AI 助手源码在独立仓库 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`（remote `Dadihu123/ST-Manager-AI-Assistant`） | 「源码不在任何版本库，会阻塞加入官方列表」 | **判断错误，已撤销**。安装副本没有 `.git` 是 `installer.py:236-250 strip_forbidden_dirs` 的正常行为 | §1 表、§6 未决 4/9、附录 |
| 允许第三方使用宿主图标名 | 「禁止，插件必须自带图标资源」 | **反转**。开源项目里图标集是公开接口，授权成立 | §3.4 全节重写、§4 P0-D、§5 反目标 16、§6 未决 7/8、附录 |
| 项目开源，第三方可读源码开发 | 未考虑 | **改变多处论证前提**：图标集、`ui.svg` 名字、CSS 令牌、`icon.html` 路由规则都属可读公开接口，「内部细节」这个理由大面积失效 | §2 表、§3.4、§3.6 |

**最关键的连带发现**：图标这条一反转，暴露了**授权与机制脱节**——宿主允许第三方用图标名，但前端**根本没有图标 API**（`pluginHost.js` 的 `buildApi()` 无任何图标成员），**也没有名字清单**（`ui.svg` 里 141 个图标，前端唯一的白名单是 `state.js:79-95` 的 17 个 toast 专用名字）。第三方现在唯一能做的，是去读 `ui.svg` 源码、自己拼 `/static/icons/ui.svg#icon-xxx` ——**这正是「授权已给、机制缺失」时用户必然踩的坑**。所以 §3.4 的任务从「禁止」变成「交付」。

---

## 1. 但这条信息**改变了设计的目标函数**，追加篇一有三条要改

追加篇一我按「宿主与插件是同一批人写的」推出了三个结论。现在需要逐个修正：

| 追加篇一原结论 | 修正 | 理由 |
|---|---|---|
| 「首次发布即定 **Stable**，删除 Provisional」 | **改为「冻结」而非「全 Stable」**：字段名/语义/签名定下来不再随意改，但**稳定性分级必须保留并对外承诺** | 第三方需要知道哪些能依赖。Provisional 不是「以后再说」的垃圾桶（那条反目标成立），但它是给第三方的**风险标注**，删掉等于让第三方盲猜 |
| 「**强制迁移**，不保留别名」 | 对自研的两个插件成立；对第三方改为「**发布即冻结 + 版本化演进**」 | 冻结的是**发布那一刻**的契约；发布之后第三方写的代码就是兼容负担，必须走 deprecation 流程 |
| 「插件**测试进主套件**」（§4.9） | **反转**：官方插件的测试在**它自己的仓库**跑 CI；宿主主套件只保留**契约测试** | AI 助手要作为官方插件发布 → 它必须有独立公开仓库（D1 本来就是「插件外置」）。它的 15 个测试文件跟着走，不进宿主套件 |
| 「插件源码移到版本库内 `plugins/<id>/`」（§4.9） | **删除这条** | 与「官方插件独立发布」冲突。宿主仓库不该托管插件源码 |

**补充事实（m00758 澄清）**：AI 助手的源码确实已经在独立仓库里，位置 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`，remote 为 `https://github.com/Dadihu123/ST-Manager-AI-Assistant.git`（有 `.git`）。仓库顶层：`.pytest_cache/ .superdesign/ backend/ design/ docs/ frontend/ tests/ tools/ .gitignore CHANGELOG.md LICENSE manifest.json README.md`，另有若干未跟踪的临时诊断产物（`_all_rules.json`、`_bf_all.json`、`_fs_out.txt`、`_gaps_out.txt`、`_probe_fullscreen.py`、`_probe_gaps.py`、`recon_backdrop_filter_report.md`、`tools/`）。其 `frontend/` 为 `api.js`、`dom.js`、`panel.js`、`plugin.js`、`plugin.css`、`assets/icon.svg`、`views/{workbench,review,profiles,settings}.js`。

`data/plugins/stm-ai-assistant/` 是**手动安装过来的副本**，所以那里没有 `.git` 是正常的——不是「源码没有版本管理」，而是「安装副本本来就不该有 `.git`」。这与 `core/plugins/installer.py:236-250 strip_forbidden_dirs` 的设计一致：安装时剥离 `__pycache__` / `.git` / `node_modules` 等（`FORBIDDEN_DIR_NAMES`）。

**该仓库最近一次提交是 `c34b585 feat(frontend): 悬浮入口改图标可拖拽，档案页修复黑屏/切换/单档导出`** —— 「悬浮球」正是在这个独立仓库里迭代的。这印证了本设计的核心论点：**没有契约通道时，插件只能在自绘浮层这条路上越走越远。** 仓库里那 20+ 个 `tools/probe_*.py` / `repro_*.py` / `check_backdrop_render*.py` 诊断脚本，佐证的正是 `frontend/plugin.css:89-145` 记录的那段 Chromium backdrop-filter 排查史——**这些本该由宿主 surface 层解决的问题，现在由插件独自承担。**

**§4.9 的正确形态**（替代原方案）：

| 层 | 位置 | 内容 |
|---|---|---|
| 宿主契约测试 | `tests/test_plugin_*.py`（已有 28 个） | 测宿主的 manifest 解析、加载、隔离、API 契约 |
| **契约活体夹具** | `samples/plugins/hello-world/` | **升级**：填满全部 `kind`（dock/nav/settings/context/command），成为契约的活文档 + CI 夹具。宿主改契约 → CI 立刻发现破坏，而不是等第三方报错 |
| 官方插件测试 | AI 助手自己的仓库 CI | 它的 15 个测试文件（`conftest.py`、`fake_api.py`、`test_css_scope.py`、`test_hashing.py`、`test_jobs.py`、`test_llm.py`、`test_manifest_contract.py`、`test_module_layout.py`、`test_parsing.py`、`test_profiles.py`、`test_prompt.py`、`test_routes.py`、`test_store.py`、`test_tokens.py`、`test_trimming.py`）整体搬走 |
| 第三方插件测试 | 第三方自己的仓库 | 宿主不关心，但宿主应提供可复制的契约测试模板 |

**撤销一条错误判断**：本文初稿曾写「AI 助手源码不在任何版本库里，会阻塞加入官方列表」——**该判断已作废**（依据是 `data/plugins/stm-ai-assistant/` 无 `.git`，但那只说明它是安装副本）。真实情况见上方「补充事实」：源码在独立仓库 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`，remote 已配置。**加入官方列表的前置条件不是「建仓库」，而是「定发布策略」**（该仓库 `git tag` 为空，见 §6 未决 4）。

---

## 2. 新增：目标函数从「省自己的力」变成「降低第三方的接入与理解成本」

| 维度 | 自研插件视角（追加篇一） | 第三方视角（本篇） |
|---|---|---|
| 严格校验 | 省自己调试时间 | **降低你的支持成本**——第三方写错 `entrys`，你收到的是「装了但不显示入口」的 issue，日志里只有一条 warning |
| 原语库 | 少写 CSS | **防止出现第三、第四种外观**——第三方不会猜你的设计语言，只会画自己的 |
| 错误信息 | 自己看得懂就行 | **必须面向非作者**：用户装第三方插件失败时，看到 `id 不符合 ^[a-z][a-z0-9-]{1,63}$: 'My_Plugin'` 不知道该干什么 |
| 契约文档 | 自己查代码 | **唯一真相来源**，且必须写清演进承诺 |
| 静态检查 | 辅助自查 | **唯一能约束第三方的手段**——文档约束不了别人的代码 |
| **宿主资源**（图标、CSS 令牌、`icon.html` 路由规则） | 「内部实现细节」，不该成为公开契约 | **项目开源 → 源码即文档，这些是可读的公开接口**。约束手段从「禁止使用」改为「提供正式 API + 校验 + 不改名承诺」（见 §3.4） |

**推论：凡是「靠文档约束第三方」的设计都不成立，必须落到安装期自动检查或宿主运行时强制。**
**反面推论（m00758 补充）：凡是「靠隐藏来防止滥用」的设计也不成立——源码公开时，隐藏只会让第三方绕过正式 API 去硬编码内部路径。**

---

## 3. 面向第三方的具体新增/加强点

### 3.1 官方 vs 第三方：catalog 缺一个「分级」字段

`core/plugins/catalog.py:85-121 _normalize_entry` 目前只认这些字段：

`id` / `name` / `description` / `author` / `icon` / `tags` / `source{type,repo,ref,subdir,release_channel,sha256}` / `version` / `api_version` / `min_app_version` / `permissions` / `homepage`

**没有 `official` / `verified` / `tier` 之类的分级字段。** 而 `static/plugins/catalog.json` 现在就是空的：

```json
{"schema_version": 1, "updated_at": "2026-09-22T00:00:00Z", "plugins": []}
```

但「官方目录」这个概念在 UI 里已经成立（`templates/modals/plugin_manager.html:350` 提示「目录清单来自仓库内的 `static/plugins/catalog.json`」，`:353` 遍历 `catalog`，`:357` 用 `entry.installed ? '●' : '○'`）。

**需要补**（`CATALOG_SCHEMA_VERSION = 1` → `2`）：

```jsonc
{
  "id": "stm-ai-assistant",
  "tier": "official",          // official | verified | community
  "maintainer": "ST-Manager",  // 与 author 区分：author 是原作者，maintainer 是当前维护方
  "channel": "stable",         // stable | beta | experimental
  ...
}
```

用途：
- **UI 徽标**：官方 / 认证 / 社区 三档视觉区分（`plugin_manager.html:354-402` 的目录卡片目前只有 `●`/`○`）。
- **准入分级**：`tier` 决定该插件的入口能声明哪些 `kind`（见 §3.2）。
- **免责边界**：社区插件的权限清单需要更醒目的确认（S8 已有「安装前展示权限清单」，`docs/2026-09-22-plugin-system-design.md:1638`）。

**注意**：catalog 的 `tier` 是**宿主仓库里的清单说了算**（D11 方案 B：清单在本仓库），第三方无法自己声称 official。这是正确的信任模型。

### 3.2 入口 `kind` 的准入分级（主文档 §7.3 没写）

我在主文档里假设都是自研插件，所以没限制 `kind`。有了第三方必须分级：

| `kind` | 官方 | 认证 | 社区 | 理由 |
|---|---|---|---|---|
| `command` | ✅ | ✅ | ✅ | 只在命令面板，不占视觉空间，零干扰 |
| `context` | ✅ | ✅ | ✅ | 只在右键菜单，按需出现 |
| `dock` | ✅ | ✅ | ✅（**默认不固定**） | 坞槽位是稀缺资源，见 §3.3 |
| `settings` | ✅ | ✅ | ✅ | 在设置页内，不影响主界面 |
| `status` | ✅ | ✅ | ❌ | 纯展示不占点击语义，**极易被滥用成广告位** |
| `nav` | ✅ | ✅ | ❌ | 与宿主 8 个核心模块平级、占主内容区整页，这是**产品级承诺**，不该让任意第三方占据 |

`nav` 的门槛尤其要写清楚：`kind:'nav'` 意味着这个插件要在侧栏模块菜单里和「角色卡 / 世界书 / 聊天 / 预设 / 正则脚本 / ST 脚本 / 快速回复 / 美化」并列。这是宿主的产品决策，不是插件的权利。

### 3.3 坞的槽位是宿主分配的资源，不是插件索取的权利

主文档 §6.1 给了 `priority` 字段，但没说清所有权。第三方场景下必须明确：

- 插件声明 `priority`（**建议值**），宿主 + 用户决定谁进坞。
- **默认策略**：社区插件的 `dock` 入口**默认进溢出菜单，不进坞槽位**；用户显式拖入才固定。
- **配额**：坞可见槽位上限（建议 6–8 个，与 `⋯` 溢出入口合计不超一屏）；单插件在坞内最多占 1–2 个槽位。
- **依据**：10 个第三方插件各固定 6 个 → 坞爆掉。主文档 §6.1 的「单插件最多 16 项 entries」只防了单插件，没防总量。

### 3.4 第三方插件**可以**用宿主图标名 —— 但机制还不存在（本节已反转）

> **原设计（现已推翻）**：主张「插件必须自带图标资源，禁止使用宿主图标名」，理由是第三方不知道白名单、白名单是内部细节、宿主改图标集会破坏第三方。
> **用户裁定（m00758，逐字）**：「第三方插件允许使用宿主图标名，项目本身是开源的，第三方开发插件的时候也是可以直接结合源码来开发的，因此可以允许第三方插件使用宿主图标名。」

**采纳该裁定。** 理由成立：项目开源 + 契约文档公开 + `templates/components/icon.html` 就在仓库里可读，所以「图标集」是**公开接口**而非内部细节。第三方读源码开发，用宿主图标名是合理且更优的选择——**视觉一致性**（第三方插件用同一套图标语言，比各自画 SVG 好得多）。

**这个裁定还纠正了一个方法论错误**：我原来的理由是「白名单是内部实现细节，不该成为公开契约」——但在开源项目里，**没有「内部细节」这回事**。`ui.svg` 的 141 个 `id="icon-*"` 就在版本库里，任何人都能读到。**「禁止使用」只能禁止使用正式 API，禁止不了硬编码路径。** 与其让第三方各自去拼 `/static/icons/ui.svg#icon-xxx`（宿主改 sprite 文件名就静默失效），不如把图标名变成**有校验、有承诺**的正式契约。这与 §2 的推论一脉相承。

**但裁定立刻暴露一个新问题：授权已经给了，机制却不存在。** 现在的实际状况：

| 事实 | 证据 |
|---|---|
| 图标宏是 **Jinja 服务端宏**，只在模板里可用 | `templates/components/icon.html` 的 `icon`/`loading_icon`/`sidebar_icon`/`detail_icon`/`preset_icon`/`beautify_asset_icon` 全部渲染为 `<use href="{{ url_for('static', filename='icons/<sprite>') }}#icon-<name>">` |
| 插件是**纯前端 JS**，拿不到 Jinja 宏 | `static/js/pluginHost.js:147-178 loadPlugin` 只做 `injectStyle()` + `await import(entryUrl)`；`buildApi`（`:180-543`）**没有任何图标 API** |
| 前端唯一的图标名白名单是 **toast 专用**的，只有 17 个名字 | `static/js/state.js:79-95 TOAST_ICON_NAMES`：forbidden / card-send-to-st / sillytavern / tauritavern / folder / loading-animation / close / trash / check / settings-help-entry / settings-save / alert-triangle / clipboard / snapshot + `TOAST_ICON_SPRITES`(`:71-75`) 的 backup-rollback / tags / link-source |
| sprite 里实际有 **190 个图标**，其中 `ui.svg` 141 个 | 实测：`static/icons/ui.svg` 141 symbols / 289.3 KB、`detail.svg` 26 / 68.9 KB、`preset.svg` 13 / 26.6 KB、`sidebar.svg` 10 / 24.7 KB、`loading-animation.svg` 1.2 KB（无 `id="icon-*"`，是独立文件） |
| **`ui.svg` 的 141 个图标没有任何前端可读的名字清单** | 名字只存在于 sprite 的 `id="icon-*"` 属性里；`icon.html` 的两个 Jinja 白名单（`sidebar_icon` 的 `:24` 四名字、`detail_icon` 的 `:37` 24 个名字）是**路由到哪个 sprite** 的规则，不是名字全集 |
| 插件要自己用 `<use>` 引用宿主 sprite，**必须知道文件名 + 图标名 + `#icon-` 前缀约定** | 这三个都是事实契约，一处都没写进 `docs/plugin-api.md` |

**所以本节的任务从「禁止」变成「补全机制」。** 需要交付：

1. **`api.ui.icon(name, options)`** —— 返回一个 `<svg><use href="/static/icons/<sprite>.svg#icon-<name>"></use></svg>` 元素（或对应 HTML 字符串）。宿主内部持有「名字 → sprite」映射，与 `icon.html:24`/`:37` 的规则一致。
2. **图标名清单导出** —— `GET /api/plugins/ui-icons`（或静态 JSON）：`{name, sprite, category, keywords}` 列表。供：
   - 插件开发时查阅（比翻 sprite 源码友好）；
   - **安装期校验**：manifest 里 `entries[].icon` 写的是宿主图标名时，校验其存在性 → 拼错就报错，而不是渲染成空白；
   - **图标选择器 UI**（`api.ui.iconPicker()`），让第三方作者可视化挑图标。
3. **命名空间隔离** —— 宿主图标名与「插件自带资源路径」必须在语法上可区分（如宿主名不带 `/` 与 `.`，资源路径必含 `/`）。**这点已天然满足**（§6.1 的三级解析规则）。
4. **契约承诺** —— 既然允许第三方依赖图标名，就**必须承诺不随意改名/删除**。列入 `docs/plugin-api.md` 的稳定性分级：建议整表标 `Stable`，但允许「新增」（新增不影响既有插件），删除/改名需走 deprecation。

**这条反转带来的正面效果**：`docs/plugin-api.md` 从「143 行、只有 API 签名」升级为「包含可用图标目录」——这是第三方最需要的参考资料之一，且成本只是把已有的 sprite 解析一遍。

**仍保留的部分约束**：宿主图标名只保证在 `entries[].icon` 与 `api.ui.icon()` 两个位置可用；插件**不应**在自己 CSS 里硬编码 `url('/static/icons/ui.svg#...')`（那是绕过校验的路径，且 sprite 文件名可能变）。宿主 sprite 只给 `core:` 前缀内建入口直接引用的说法作废。

### 3.5 `when` 表达式是第三方插件的安全阀（重要度上调）

追加篇一 §4.2 提出 `when` 表达式时，论证角度是「用户体验」。第三方场景下理由更强：

**第三方插件无法保证配置正确。** 一个社区插件声明了 `config_schema.properties.api_key`（或 `secret_schema`），用户装了但没填——这时候：

| 无 `when` | 有 `when.config.requireKeys` |
|---|---|
| 点入口 → 插件自己抛错 → 用户看到 console 报错或静默无反应 → 用户去提 issue | 入口**可见但置灰** + `disabledHint: '请先在插件设置中填写 API Key'` + 可点进配置 |

**你无法 review 第三方的代码，所以必须在契约层给它一个「优雅降级」的标准姿势。** 否则每个第三方插件都会用自己（通常很糟）的方式处理未配置状态。

配套：`when.hostVersion` / `when.feature` 让第三方能声明「需要宿主 ≥ X」「需要宿主能力 Y」，避免在不满足时静默失效。

### 3.6 manifest 严格校验 + **面向非作者**的错误信息

`core/plugins/manifest.py` 现在的报错是给作者看的：

- `:356-357` `raise PluginManifestError(f'id 不符合 ^[a-z][a-z0-9-]{{1,63}}$: {raw_id!r}')`
- `:372-376` `raise PluginApiVersionError(f'插件需要 api_version {api_version}，当前主程序仅支持 {list(SUPPORTED_PLUGIN_API_VERSIONS)}（需更新主程序）')`

而未知项**只记 warning 不报错**：未知 hook `:426`、未知权限 `:453`、requires 非法项 `:461`/`:467`/`:473`、icon 不可用 `:483`。

第三方场景下需要**两层错误信息**：

```python
{
  'code': 'manifest_unknown_key',
  'field': 'frontend.entrys',            # 技术细节（给作者 / 日志）
  'msg': 'manifest 中存在未知字段 frontend.entrys',
  'hint': 'frontend 下支持的字段：entry, styles, entries, panels(已废弃)…',
  'user_msg': '插件「XXX」的清单格式不正确，请联系插件作者更新。',  # 给 UI
}
```

`user_msg` 是新增的：用户装第三方插件失败时，`plugin_manager.html` 应显示 `user_msg`，把技术细节折叠。现在只有 `load_error` 一个字符串（`core/plugins/registry.py:118-119`），没有分层。

### 3.7 `api_version` 的语义要重新定义 + 支持多版本并存

追加篇一说「升到 2」。有了第三方，还需要两件事：

1. **写清语义**：`api_version` 是**宿主契约版本**，插件声明它要求的版本；`min_app_version` 是**应用版本**。两者独立。
2. **支持多版本并存**。现在 `core/version.py:13` 是：

```python
SUPPORTED_PLUGIN_API_VERSIONS = (PLUGIN_API_VERSION,)
```

单元素元组。**发布后**任何破坏性变更都必须让旧版插件继续可用一段时间，那时需要 `(2, 1)` 这样的集合，并且宿主需要按插件声明的版本走兼容分支。

现在改结构 → 成本为零；发布后改 → 又是一次破坏性变更。**这是发布前最该做的一项。**

### 3.8 契约文档必须补「演进承诺」

`docs/plugin-api.md` 是自动生成物（`tools/gen_plugin_api_docs.py`，`tests/test_plugin_api_docs.py:35-42` 断言磁盘内容 == `render()`），稳定性分级在生成器的 `FRONTEND_MEMBERS`（`tools/gen_plugin_api_docs.py:68-94`，`registerModal`/`registerSettingsSection`/`utils`/`jobs` 标为 Provisional）。

但文档末尾只有「相关文档」三条链接（`docs/plugin-api.md:139-143`），**没有版本化策略**。第三方无法规划。

需要补一章：

| 分级 | 承诺 |
|---|---|
| `Stable` | 破坏性变更需 `api_version` +1，且旧版本继续支持至少 N 个宿主版本 |
| `Provisional` | 可能在 minor 版本变更，变更会在 CHANGELOG 说明 |
| `Experimental` | 随时可能变，不承诺 |

外加：deprecation 流程（先标记、保留至少一个 minor、再移除）、`api_version` 变更日志。

### 3.9 静态检查是约束第三方的**唯一**手段——必须加强

`core/plugins/installer.py:521-589 scan_css_scope` 现在**只查作用域**。第三方场景下至少还要查三项，且**必须自动化**：

| 检查 | 现状 | 为什么对第三方是必须的 |
|---|---|---|
| 顶层裸选择器（F11 作用域） | ✅ 已实现 | 已有 |
| **`position: fixed`** | ❌ 未查 | 第三方用 `position:fixed` 画浮层 → 又回到「球满天飞」，正是本设计要消灭的东西。应与反目标「不允许插件自绘浮层」配套，**在安装期拦截** |
| `var(--x)` 引用不存在的令牌且无回退值 | ❌ 未查 | 第三方不知道宿主有哪些令牌，会写出静默失效的样式 |
| 非作用域选择器上的 `!important` | ❌ 未查 | 第三方抢样式的典型手段 |

**实现陷阱（必须写明）**：`scan_css_scope` 用 `skip_blocks` 计数跳过 `@media`/`@supports`/`@layer`/`@container`/`@keyframes`/`@font-face` **内部的选择器检查**（`installer.py:563-566`），`tests/test_plugin_css_scope.py:48-54` 明确断言 `@media (max-width:600px){ .card{display:none} }` → `[]`。

所以**声明层**的新检查（`position:fixed`、令牌、`!important`）**必须进入** `@media` 块——否则第三方把浮层写进 media query 就绕过了。这是两套不同的遍历逻辑，不能复用现有 `skip_blocks` 分支。

`tests/test_plugin_css_scope.py:81-87` 的现有行为（`@media print { body{...} }` + 顶层 `.card{...}` → `['.card']`）应保持不变。

### 3.10 官方插件与第三方插件在同一列表里的信任呈现

`templates/modals/plugin_manager.html:353-402` 的目录卡片现在只有 `●`/`○` 和版本、作者、GitHub 链接、来源 repo。需要（配合 §3.1 的 `tier`）：

- 徽标：官方 / 认证 / 社区
- 社区插件的权限清单更醒目（S8 已有基础）
- 「此插件将添加 N 个入口」披露（追加篇一 §4.4 已提，对第三方更重要）

### 3.11 一个现存的小缺口：上传安装不绑定 id

- catalog 路径：`core/plugins/installer.py:377 expected_id = str(entry.get('id') or '').strip()` → `:397-399 install_plugin_dir(plugin_root, expected_id=expected_id, source_label=f'catalog:{repo}')` → **id 不匹配则拒绝**（防供应链投毒，设计文档 `:345`）。
- **上传路径**：`:428-429 install_from_upload` → `install_plugin_dir(plugin_root, source_label=source_label)` —— **没有传 `expected_id`**。

上传是「离线兜底」且用户显式操作，风险较低，但第三方生态下「从聊天群下载一个 zip 装进来」会是常见路径。建议上传 UI 允许（可选）填写期望 id 并在不匹配时警告。

### 3.12 第三方插件写坏界面时的兜底

第三方插件在 `activate()` 里抛错、或 `mount()` 挂载后卡死，宿主必须能**独立于插件代码**恢复：

- `PluginHost` 已有 `failed` Map（`pluginHost.js:92-110`）记录加载失败的插件；
- 但 `mount(container, ctx)` 的**运行时**失败目前没有处理路径。需要：mount 抛错 → 宿主销毁该 surface、坞槽位置为错误态（`api.entries.setStatus` 的宿主侧对应）、toast 提示、**不影响其他插件与宿主**。
- 这依赖 §6.2 的契约「宿主负责强制卸载 surface，不依赖插件的 `deactivate`」——第三方插件更可能写出不干净的 `deactivate`。

### 3.13 插件间通信对第三方是攻击面

`core/plugins/hooks.py:82-84` 强制插件自定义事件带 `<plugin_id>:` 前缀，`pluginHost.js:217-227 emit` 同样限制。**这一点已经是对的**，第三方无法冒用别人的事件名。

但 `docs/2026-09-22-plugin-system-design.md:1593`（N1）明确「**允许**跨插件订阅（`api.on("other-plugin:xxx")`），但不保证送达顺序，也不检测循环触发」。

第三方场景下需要重新评估：一个社区插件订阅 `stm-ai-assistant:something` 是否应该被允许？倾向：
- **允许订阅**（只读语义，不构成危害），
- 但在 `docs/plugin-api.md` 明确「跨插件事件不是契约，插件作者可随时改自己的事件名，订阅方自担风险」，
- 且**不提供**「插件间调用」这类能互相触发的 API。

---

## 4. 优先级修订

追加篇一给了 P0/P1/P2。本篇在第三方前提下追加/调整：

### 新增 P0

| # | 项 | 理由 |
|---|---|---|
| A | **`api_version` 支持多版本并存**（`core/version.py:13` 从单元素元组改为集合 + 兼容分支结构） | 发布后改就是破坏性变更；这是第三方生态能演进的前提 |
| B | **契约冻结 + 稳定性分级对外承诺**（`docs/plugin-api.md` 补「演进承诺」章节） | 第三方要靠它规划 |
| C | **入口 `kind` 准入分级**（§3.2） | 决定第三方能把界面弄成什么样，后补要收回已发布的权限 |
| D | **宿主图标名成为正式契约**（§3.4，**已按 m00758 反转**）：交付 `api.ui.icon(name)` + 图标名清单导出 + 安装期校验 + 不改名承诺 | 用户已授权第三方使用宿主图标名，但机制（前端图标 API、名字清单）**目前完全不存在**；授权与机制必须同时到位，否则第三方只能靠读 sprite 源码硬编码 |
| E | **catalog `tier` 字段**（§3.1，`CATALOG_SCHEMA_VERSION` 1→2） | 加入官方列表前必须有，否则官方与社区无法区分 |

### 从 P1 提升到 P0

| # | 项 | 原级别 | 新理由 |
|---|---|---|---|
| F | **静态检查加强**（`position:fixed` / 令牌 / `!important`，§3.9） | P1 | 这是约束第三方的**唯一**手段；文档约束不了别人的代码 |
| G | **manifest 严格校验 + 分层错误信息**（§3.6） | P0（原为「省调试时间」） | 升级为「降低支持成本」，且需要 `user_msg` 字段（新增设计） |

### 从 P1 降级 / 修正

| # | 项 | 调整 |
|---|---|---|
| H | 插件测试进主套件（追加篇一 §4.9） | **改为**：`samples/plugins/hello-world` 升级为契约活体夹具进主套件；AI 助手测试跟它自己的仓库走 |
| I | 插件源码移到宿主版本库内 | **删除**（与官方插件独立发布冲突） |

### 保留 P1/P2 不变

追加篇一的其余条目（坞的徽标/进度/状态语义、主题令牌契约导出、热重载、日志面板、`api.storage`、导航项配额、坞 vs 命令面板职责、死 CSS 清理）**不受影响**。

其中 **`api.storage`** 对第三方更重要（不能指望第三方正确使用 localStorage 并自己清理），建议从 P2 提到 P1。

---

## 5. 更新后的反目标

追加篇一的 14 条反目标中，**第 9 条要修正**：

> ~~不为兼容保留任何别名、deprecated 字段或过渡阶段。没有旧插件，过渡期是纯浪费。~~

**改为**：发布前不为兼容保留别名/过渡阶段（因为还没有第三方）；**发布后必须走 deprecation 流程**，不得直接删除已标 Stable 的契约。

**新增**：

15. **不允许社区插件声明 `kind:'nav'` 或 `kind:'status'`**（§3.2）。
16. ~~不允许插件（含官方）使用宿主图标名~~ → **作废（m00758）**。允许使用宿主图标名；改为新约束：**不允许插件在 CSS 里硬编码 sprite 路径**（如 `url('/static/icons/ui.svg#icon-x')`），必须走 `entries[].icon` 或 `api.ui.icon()`，否则绕过校验且 sprite 文件名变更会静默失效（§3.4）。
17. **不允许插件在 CSS 中使用 `position: fixed`**（安装期静态检查拦截，§3.9）。
18. **不把坞槽位当作插件可索取的权利**；宿主 + 用户分配，社区插件默认进溢出（§3.3）。
19. **不允许第三方插件声称 `tier`**；分级由宿主仓库的 catalog 决定（§3.1）。
20. **不提供插件间调用 API**；跨插件事件订阅允许但不构成契约（§3.13）。

---

## 6. 本篇新增的未决问题

| # | 问题 | 待定因素 |
|---|---|---|
| 1 | `tier` 三档（official/verified/community）是否够？「verified」的认证标准是什么？ | 需要先有第三方插件再定 |
| 2 | 社区插件的 `dock` 入口「默认进溢出」是否太严？会不会让第三方觉得被歧视？ | 可用「首次安装后 toast 提示可拖入坞」缓解 |
| 3 | 静态检查发现 `position: fixed` 时：拒绝加载整份样式（同 F11），还是仅警告？ | 倾向**仅警告 + UI 标记**，因为 `position:fixed` 在 `@media` 内可能有合法用途；F11 的拒绝策略更激进 |
| 4 | 宿主仓库是否保留一份「官方插件清单 + 版本」用于 `check_updates`？ | `catalog.py:345 check_updates` 已通过远端 manifest 比对版本，机制上不需要本地副本。但 **AI 助手仓库目前没有任何 tag**（`git tag` 为空），而 `source.ref` 默认 `main`、`release_channel` 默认 `stable` —— 加入官方列表前需要确定发布策略（打 tag / 用 Releases / 还是直接跟 `main`） |
| 5 | `docs/plugin-api.md` 的「演进承诺」是否要独立成 `docs/plugin-api-stability.md`？ | 生成物 vs 手写文档的边界 |
| 6 | 第三方插件的 `user_msg` 是否需要 i18n？（N3 记录了 manifest 只支持单语言，`docs/2026-09-22-plugin-system-design.md:1595`） | 与 N3 一起考虑 |
| 7 | **（新增，§3.4 反转引出）宿主图标名清单导出后，是否承诺永不删除？** | 190 个图标（`ui.svg` 141 / `detail.svg` 26 / `preset.svg` 13 / `sidebar.svg` 10）里必然有一部分是历史遗留或内部专用。建议：导出时按 `category` 分组，只把「公共图标」标为 Stable，其余标 Provisional |
| 8 | **（新增）`api.ui.icon()` 返回 DOM 元素还是 HTML 字符串？** | 与 `api.ui.*` 原语库（追加篇一 §4.1）风格保持一致即可，倾向返回元素 + `toHTML()` 辅助 |
| 9 | **（新增）AI 助手仓库里的临时诊断产物是否要清理？** | `git status` 显示未跟踪：`_all_rules.json`、`_bf_all.json`、`_fs_out.txt`、`_gaps_out.txt`、`_probe_fullscreen.py`、`_probe_gaps.py`、`recon_backdrop_filter_report.md`、`tools/`（20+ 个 probe/repro 脚本）；已修改未提交：`.gitignore`、`CHANGELOG.md`、`frontend/plugin.css`、`tests/test_css_scope.py` |
| 10 | **（新增）AI 助手仓库的 `.gitignore` 是否够用？** | 现有内容覆盖 `data/`、`__pycache__/`、`*.py[cod]`、`.pytest_cache/`、`.venv/`、`.superdesign/`、`design/`、`venv/`、`.idea/`、`.vscode/`、`.DS_Store`、`Thumbs.db`、`tools/out/`、`tmp_crops/`、`tmp_*.png` —— 但 `tools/` 本身未被忽略（20+ 个 probe 脚本处于未跟踪状态），顶层 `_*.json`/`_*.py`/`_*.txt` 也未忽略。作为要发布的官方插件仓库，应决定：这些诊断脚本是**删掉**、**收进 `tools/` 并提交**、还是**加进 `.gitignore`** |
| 11 | **（新增）AI 助手仓库是否要加 CI？** | 它已有 15 个测试文件但无 `.github/`。作为官方插件，至少要跑 `pytest` + manifest 校验 + CSS 作用域校验（后者依赖宿主仓库的 `scan_css_scope`，需要决定如何跨仓库复用：vendored 一份、还是从宿主 pip 安装、还是宿主提供 `stm-plugin-check` CLI） |

---

## 附录 · 本篇新增取证

| 事实 | 证据 |
|---|---|
| catalog 条目字段无分级：`_normalize_entry` 只认 id/name/description/author/icon/tags/source/version/api_version/min_app_version/permissions/homepage | `core/plugins/catalog.py:85-121`（返回 dict 在 `:100-121`） |
| `CATALOG_SCHEMA_VERSION = 1`；`REPO_PATTERN = ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`（强制 owner/repo，不接受任意 URL，防 SSRF） | `core/plugins/catalog.py:25`、`:36`、`:96-98` |
| 官方目录当前为空 | `static/plugins/catalog.json` = `{"schema_version": 1, "updated_at": "2026-09-22T00:00:00Z", "plugins": []}` |
| catalog 安装路径绑定 id（防投毒） | `core/plugins/installer.py:377` `expected_id = str(entry.get('id') or '').strip()` → `:397-399 install_plugin_dir(plugin_root, expected_id=expected_id, source_label=f'catalog:{repo}')` |
| **上传安装路径不绑定 id** | `core/plugins/installer.py:428-429 install_from_upload` → `install_plugin_dir(plugin_root, source_label=source_label)`（无 `expected_id`） |
| api_version 只支持单版本 | `core/version.py:13 SUPPORTED_PLUGIN_API_VERSIONS = (PLUGIN_API_VERSION,)`；`:11 PLUGIN_API_VERSION = 1`；`:8 APP_VERSION = '1.0.0'` |
| 契约文档是生成物，无演进承诺章节 | `docs/plugin-api.md:139-143` 只有三条「相关文档」链接；稳定性分级定义在 `tools/gen_plugin_api_docs.py:68-94 FRONTEND_MEMBERS`（`registerModal`/`registerSettingsSection`/`utils`/`jobs` 为 Provisional）；`tests/test_plugin_api_docs.py:35-42` 断言磁盘 == `render()` |
| 未知 manifest 项只记 warning | `core/plugins/manifest.py:426`（未知 hook）、`:453`（未知权限）、`:461`/`:467`/`:473`（requires 非法）、`:483`（icon 不可用） |
| 报错信息面向作者，未分层 | `core/plugins/manifest.py:356-357`（id 正则）、`:372-376`（api_version）；`core/plugins/registry.py:118-119` 只注入单个 `load_error` 字符串 |
| CSS 静态检查只查作用域 | `core/plugins/installer.py:521-589`；`skip_blocks` 逻辑在 `:563-566`（跳过 `@media`/`@supports`/`@layer`/`@container`/`@keyframes`/`@font-face` 内部的**选择器**检查） |
| 现有行为契约（不可破坏） | `tests/test_plugin_css_scope.py:48-54`（`@media (max-width:600px){ .card{display:none} }` → `[]`）、`:81-87`（`@media print { body{...} }` + 顶层 `.card{...}` → `['.card']`）、`:33-38`（裸选择器被报）、`:21-31`（作用域选择器通过） |
| AI 助手源码在**独立仓库**（m00758 澄清） | `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`，`Test-Path "$p\.git"` → `True`；`git remote -v` → `origin https://github.com/Dadihu123/ST-Manager-AI-Assistant.git`（fetch+push）；`git log --oneline -5` 最新为 `c34b585 feat(frontend): 悬浮入口改图标可拖拽，档案页修复黑屏/切换/单档导出`；`git tag` **为空**；`git status --short` 有 4 个已改未提交（`.gitignore`、`CHANGELOG.md`、`frontend/plugin.css`、`tests/test_css_scope.py`）与 8 项未跟踪（`_all_rules.json`、`_bf_all.json`、`_fs_out.txt`、`_gaps_out.txt`、`_probe_fullscreen.py`、`_probe_gaps.py`、`recon_backdrop_filter_report.md`、`tools/`） |
| 该仓库顶层与 `frontend/` 结构 | 顶层 `.pytest_cache/ .superdesign/ backend/ design/ docs/ frontend/ tests/ tools/ .gitignore CHANGELOG.md LICENSE manifest.json README.md`；`frontend/` = `api.js`、`dom.js`、`panel.js`、`plugin.js`、`plugin.css`、`assets/icon.svg`、`views/{workbench,review,profiles,settings}.js` |
| 该仓库 `manifest.json` 与安装副本一致 | `D:\Workspace\MyOwn\ST-Manager-AI-Assistant\manifest.json:1-23`：`id` `stm-ai-assistant`、`name` `AI 角色卡分析助手`、`version` `0.1.0`、`api_version` `1`、`author` `ST-Manager`、`license` `MIT`、`min_app_version` `1.0.0`、`backend.jobs=["ai.analyze"]`、`backend.hooks=[]`、`frontend` 段只有 `entry`+`styles` |
| 该仓库 20+ 个诊断脚本（佐证插件独自承担了宿主层的合成器问题） | `tools/`：`accept_fix.py`、`analyze_user_shots.py`、`bisect9.py`、`bisect_shadow.py`、`calib_accept_bands.py`、`check_backdrop_render3.py`、`check_backdrop_render4.py`、`probe_bg.py`、`probe_has_cost.py`、`probe_layers.py`、`probe_main_modal.py`、`probe_real_browser.py`、`probe_residual.py`、`probe_rootcause.py`、`probe_user_cfg.py`、`probe_wallpaper_parity.py`、`repro_black_shadow.py`、`repro_installer_scan_bug.py`、`sweep_viewports.py`、`verify_user_dpr.py`、`_probe_fields.py`、`_sync_css.ps1` |
| 安装副本没有 `.git` 是设计使然 | `core/plugins/installer.py:236-250 strip_forbidden_dirs`：「剥离 `__pycache__` / `.git` / `node_modules` 等目录（2.1）」，遍历 `os.walk(root, topdown=True)` 对 `FORBIDDEN_DIR_NAMES` 中的目录 `shutil.rmtree` |
| **宿主图标只能经 Jinja 宏使用，前端无图标 API** | `templates/components/icon.html` 六个宏全部渲染为 `<use href="{{ url_for('static', filename='icons/<sprite>') }}#icon-<name>">`；`static/js/pluginHost.js` 的 `buildApi()`（`:180-543`）无任何图标相关成员 |
| **前端唯一的图标名白名单是 toast 专用的 17 个名字** | `static/js/state.js:79-95 TOAST_ICON_NAMES`（forbidden / card-send-to-st / sillytavern / tauritavern / folder / loading-animation / close / trash / check / settings-help-entry / settings-save / alert-triangle / clipboard / snapshot + `TOAST_ICON_SPRITES` 的键）；`TOAST_ICON_SPRITES` 在 `:71-75` 映射 `backup-rollback`→`detail.svg#icon-backup-rollback`、`tags`→`detail.svg#icon-tags`、`link-source`→`detail.svg#icon-link-source`；`TOAST_ICON_IMAGES` 在 `:76-78` 映射 `loading-animation`→`loading-animation.svg` |
| **sprite 实际图标数（实测）** | `static/icons/ui.svg` **141** symbols / 289.3 KB；`detail.svg` **26** / 68.9 KB；`preset.svg` **13** / 26.6 KB；`sidebar.svg` **10** / 24.7 KB；`loading-animation.svg` 1.2 KB（无 `id="icon-*"`，独立文件而非 sprite）。**合计 190 个图标，其中 141 个在 `ui.svg` 且无任何前端可读的名字清单** |
| 图标宏的 sprite 路由规则（名字→文件的映射） | `templates/components/icon.html:24`（`sidebar_icon`：`ui.svg` if name in `['layers','menu-category','character-cards','paint-brush']` else `sidebar.svg`）、`:37`（`detail_icon`：`ui.svg` if name in 24 个名字 `['version','info','user','grid','note','tags','locate','overwrite','edit-mode','editor','quick-reply','link-source','chat-bubble','fullscreen','persona','clock','book-open','file-name','preset','book-read','expand','regex','script-file','chat-empty']` else `detail.svg`）、`:9`（`icon` 恒 `ui.svg`）、`:55`（`preset_icon` 恒 `preset.svg`）、`:66`（`beautify_asset_icon` 恒 `ui.svg#icon-beautify-<name>`） |
| AI 助手 15 个测试文件清单（在独立仓库 `tests/`） | `data/plugins/stm-ai-assistant/tests/`：`conftest.py`、`fake_api.py`、`test_css_scope.py`、`test_hashing.py`、`test_jobs.py`、`test_llm.py`、`test_manifest_contract.py`、`test_module_layout.py`、`test_parsing.py`、`test_profiles.py`、`test_prompt.py`、`test_routes.py`、`test_store.py`、`test_tokens.py`、`test_trimming.py` |
| 其 `conftest.py` 刻意模拟主程序加载方式 | `data/plugins/stm-ai-assistant/tests/conftest.py:1-6` 注释「加载方式**刻意模拟主程序**：用 `importlib.util.spec_from_file_location` + `submodule_search_locations` 构造包（见 `core/plugins/registry.py:262-286`），不注入 `sys.path`」；`:16 MAIN_APP_DIR = os.environ.get('STM_MAIN_APP_DIR', r'D:\Workspace\MyOwn\ST-Manager')` |
| 其 `fake_api.py` 是 PluginAPI 测试替身 | `data/plugins/stm-ai-assistant/tests/fake_api.py`（231 行）：`FakeApi`（`plugin_id='stm-ai-assistant'`、`manifest={'id':…, 'version':'0.1.0'}`、`app_version='1.0.0'`）、`FakeConnection`、`FakeCtx`（对应 `core/plugins/jobs.py:91-219` 的 `JobContext`） |
| 插件管理器目录卡片现状 | `templates/modals/plugin_manager.html:350`（提示来自 `static/plugins/catalog.json`）、`:353 x-for="entry in catalog"`、`:357 entry.installed ? '●' : '○'`、`:365-370` 目录版本、`:371-376` 作者、`:381-389` GitHub 链接、`:390-397` 安装按钮、`:401` `'来源: ' + entry.source.repo` |
| 跨插件事件：前缀强制已实现，跨插件订阅允许但非契约 | `core/plugins/hooks.py:82-84`（前缀不符抛 `ValueError`）、`pluginHost.js:217-227`（不符则 `console.warn` 并忽略）；`docs/2026-09-22-plugin-system-design.md:1593`（N1） |
| 插件 CSS 只能以 `.plugin-<id>` 或 `[data-plugin="<id>"]` 为根 | `core/plugins/installer.py:539-541 scope_tokens`；`docs/2026-09-22-plugin-system-design.md:1165`（F11） |
| 脚手架生成的 manifest 目前不含 `entries` | `tools/new_plugin.py:34-73 MANIFEST_TEMPLATE`（frontend 段只有 `entry`/`styles`）；`:31 PLUGIN_ID_PATTERN = ^[a-z][a-z0-9-]{1,63}$`；`:32 DEFAULT_OUT_DIR = os.path.join('data','plugins')` |
| `samples/plugins/hello-world` 现状（升级为契约夹具的起点） | `samples/plugins/hello-world/manifest.json`：`backend.jobs=["demo.count"]`、`backend.hooks=["card.updated"]`、`permissions=["cards.read","secrets.read"]`、`config_schema`（`greeting`/`show_timestamp`）、`secret_schema`（`api_key` secret:true / `base_url`）；`frontend` 段只有 `entry`+`styles` |
| 安装期披露权限已有设计基线 | `docs/2026-09-22-plugin-system-design.md:1638`（S8「安装前展示权限清单，用户显式确认；卸载进回收站」） |
| 插件 i18n 未实现，仅预留 | `docs/2026-09-22-plugin-system-design.md:1595`（N3） |
