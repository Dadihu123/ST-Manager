# ST Manager UI 审计与优化方案

> 视角：Refactoring UI（Wathan & Scogger）
> 范围：`templates/` + `static/css/` + 相关 JS 渲染逻辑
> 状态：**审计已完成，第 1–3 档已实施**。实施结果与逐条改动见
> [第十节](#十实施记录2026-10-19)。

## 一、结论摘要

**问题不是配色。**

项目已经有一套相当完整的语义色层（[`static/css/modules/variables.css`](../static/css/modules/variables.css) 的 9 类 surface / 4 类 content / 5 组 status / 4 组 decoration，外加 `html.light-mode` 完整映射）。我逐对验算了深色与浅色双主题下的文字与边框对比度：

- 全部文本 token 在其常规承载面上均 ≥ 4.5:1（实测 4.73–17.74:1）；
- 主题主色上的文字 4.94:1，恰好过线；
- 实心状态色上的文字在双主题下均 ≥ 4.5:1（`tests/test_color_system_contracts.py` 已有 Node 端断言守护）。

配色不是短板。真正的问题是两件事：

1. **层级信号失效** —— 全站最该突出的东西（主操作、正文）反而最不突出：`.btn-primary` 比 `.btn-secondary` 更弱、95.6% 的文字声明被加粗、`--content-muted` 的使用次数超过 `--content-primary`。
2. **标尺缺位** —— 没有字号、间距、层级（elevation）标尺；圆角有 5 套互不相干的 token 家族；同时 Tailwind 默认值作为第二套标尺并行生效。

这两件事在 Refactoring UI 里是最高优先级的两章：**Hierarchy** 和 **The systems**。"看起来乱" 是这两件事的症状，不是原因。

---

## 二、实测基线

以下数字全部由脚本对本仓现有文件统计得出，可复现。

| 维度 | 实测值 | 说明 |
|---|---|---|
| CSS 规模 | `static/css/` 下 44 个文件；`style.css` 串 31 个 `@import`（模块目录 39 个文件） | 最大 `modal-tools.css` 5704 行 / 158 KB |
| 字号声明 | **1179 条，90 个不同值** | 项目内**没有任何字号 token**，全部是字面量 |
| 字号合规 | 落在 12/14/16/18/20/24/30/36/48/60/72 标尺上：**518 / 1155（44.8%）** | 55.2% 不在标尺上 |
| 小字密度 | **< 12px 的声明 574 条** | `0.68rem`(10.88px)×101、`0.72rem`(11.52px)×98、`10px`×54、`11px`×36、`0.7rem`×74 |
| 极小字 | **9px×13、8px×1、`0.5rem`×1** | 低于常见可读下限 |
| 间距声明 | **2753 条，66.3% 不在 4/8/12/16/24/32/48/64 标尺上** | 主噪声：`0.35rem`(5.6px)×208、`0.45rem`(7.2px)×171、`0.55rem`(8.8px)×154 |
| 圆角 | **106 个不同值 + 5 套 token 家族** | `--ui-radius-*`、`--chat-radius-*`、`--beautify-radius-*`、`--resource-workbench-radius`、`--preset-editor-panel-radius` |
| 阴影 | **288 个不同 `box-shadow` 值**，项目只定义了 1 档 `--shadow-elevation` | 另有 `--shadow-sm/md/lg/xl` 16 处引用但从未定义（均带 fallback） |
| 字重 | **388 条声明中 371 条 > 500（95.6%）** | 非标准值 7 个共 183 条：`800`×90、`750`×34、`650`×23、`900`×19、`bold`×12、`850`×4、`760`×1 |
| 强调:常规 | **22 : 1** | 371 条强调 vs 17 条常规（`500`×15、`400`×1、`inherit`×1） |
| `!important` | **1676 处** | 级联靠特异性硬拼 |
| 选择器深度 | **93 个 > 4 层，最深 10 层** | `.wi-entry-history-modal > .flex-1 > div:last-child .grid > div > div:last-child` |
| 级联层 | **0 个 `@layer`** | 无层级约定，只能靠源序与 `!important` |
| 文本色使用 | `--content-muted` **501 次** > `--content-primary` **466 次** > `--content-secondary` 238 次 | 三级色的实际比例与语义定位相反 |
| 按钮类名 | **191 个** | |
| 模态类名 | **72 个** | 24 个含遮罩的模板中 19 个用共享 `.ui-modal-shell`，5 个自绘 |
| 表单控件 | 289 个，其中 **45 个完全无 class** | 直接走浏览器默认外观 |
| `<label>` | 296 个，**266 个无 `for=`** | 点击标签不聚焦输入框 |
| `aria-live` | 56 处，但**全局 Toast 没有** | `templates/layout.html:67` |
| 未定义 CSS 令牌 | **41 个**，其中 **5 个无 fallback** | 详见 P3-5 |
| 未定义的 Tailwind 冲突 | `shadow-sm/md/lg/xl` 在模板中 33 次、在 CSS 中 16 次引用 | 属 Tailwind 默认 scale，详见 P1-6 |

---

## 三、P0 — 层级失效（最高优先级）

Refactoring UI 的核心论点：**"看起来像设计过" 靠的是层级，不是装饰。** 当所有东西都在争夺注意力时，UI 会读成噪声。以下五条是当前页面"平、闷、看不清重点"的直接原因。

### P0-1 `primary` 按钮比 `secondary` 更弱

**证据**（[`static/css/color-system.css:760`](../static/css/color-system.css#L760) 与 `:781`）：

```css
/* primary —— 实际是浅色 tint 底 + 描边 */
.btn-primary {
  background-color: var(--action-surface);   /* accent 9–14% 混入 surface-container */
  border: 1px solid var(--action-border);
  color: var(--action-text);
}

/* secondary —— 中性抬升底 + 中性描边 */
.btn-secondary {
  background-color: var(--surface-container-raised);
  border-color: var(--border-default);
  color: var(--content-secondary);
}
```

`--action-surface` 是 accent 以 9%（浅色）/ 14%（深色）混进 `--surface-container` 的结果。在深色主题下，这层 tint 与背景的差异极小，而 `secondary` 用的 `--surface-container-raised` 反而更亮。**结果：主操作在视觉上比次操作更"退后"。**

这与 Refactoring UI 的硬性规则直接冲突：

- Primary → 实心、高对比，通常每页恰好一个；
- Secondary → 描边或低对比底；
- Tertiary → 看起来像链接。

**建议**：把 `.btn-primary` 改回实心 `--accent-action` + `--content-on-accent`。这组配对我已验算：深色 4.94:1、浅色 4.94:1，均 ≥ 4.5。而且 [`static/css/modules/ui-primitives.css:49`](../static/css/modules/ui-primitives.css#L49) 里的 `.ui-primitive-button--primary` **已经就是这么写的**——正确的实现已经存在，只是应用层模板没用它（0 次使用）。

### P0-2 单页多个主操作

> **更正（实施阶段复核）**：初版这里给的是"primary 类出现次数"，用正则匹配 `primary`
> 子串得出，**属于误判**。实施时逐个核对后确认：
>
> - `detail_chat_reader.html` 的 33 处里**绝大多数是 `chat-toolbar-btn--primary`**，
>   它是"切换按钮的选中态"（`readerAnchorMode === 'locked_floor' ? 'chat-toolbar-btn--primary' : ''`），
>   同一时刻只会有一个处于选中态 —— **不是 33 个主操作**。
> - `grid_beautify.html` 的 9 个 `beautify-primary-btn` 读的是
>   `--beautify-control-bg` + `--border-default`，**是中性控件，不是强调按钮**。
>
> 真实的主操作按钮（`.btn-primary`）全站 34 个，分散在 18 个模板里。逐屏看：
> `detail_card.html` 有 5 个（保存、问候语管理、两个对话框确认、模态页脚），
> 但它们分属不同子面板，**同屏可见的通常只有 1–2 个**。
>
> **结论**：这个"问题"在数据上不成立，降级为**待人工巡检项**而不是缺陷。
> 真正成立的是 P0-1（primary 比 secondary 弱），已修。

### P0-3 95.6% 的文字在加粗

**证据**：388 条 `font-weight` 声明中 **371 条 > 500（95.6%）**。且出现 **7 个非标准字重共 183 条**：`800`×90、`750`×34、`650`×23、`900`×19、`bold`×12、`850`×4、`760`×1。模板层还有 208 个 `font-bold` 对 3 个 `font-medium`。

只有 17 条声明是"常规"（`500`×15、`400`×1、`inherit`×1）。**强调:常规 = 22:1。**

Refactoring UI 的要求是**两档**：

- 400 或 500 —— 正文与绝大多数 UI 文字；
- 600 或 700 —— 强调。

UI 里不使用 < 400 的字重；**要弱化就换颜色或字号，不要减字重**。

**为什么现在是反的**：当 95.6% 的文字都是粗的，加粗就不再传递任何信号。作者只能继续往上加（650→750→800→900）来制造区分，这正是 7 个非标准字重的来源——它们不是设计选择，是层级失效后的补偿行为。

**建议**：
1. 把 650/750/760/800/850 全部归并到 500 与 700 两档；
2. 去强调时改 `color`（用 `--content-secondary` / `--content-muted`）而不是降字重；
3. 模板层的 208 个 `font-bold` 逐个降级，只保留真正的 emphasis。

### P0-4 `--content-muted` 被当作正文使用

三级文本色语义本身是对的（dark / grey / lighter grey，且三者都过 4.5:1）。但实际使用是**倒挂**的：

| token | 使用次数 | 语义定位 |
|---|---|---|
| `--content-muted` | **501** | 第三级（脚注、辅助） |
| `--content-primary` | 466 | 正文 |
| `--content-secondary` | 238 | 次要 |

第三级色用得比正文还多，说明**大量本该是正文的内容被降级成了"辅助"**。这正是 diagnose 表里 "Noisy, chaotic, wall of content, nothing draws the eye" 的成因：不是内容太多，是**没有内容被允许当主角**。

**建议**：不是改 token，是改用法。凡是用户需要阅读的内容（卡片标题、描述、设置项名称、按钮文字）回到 `--content-primary` / `--content-secondary`；`--content-muted` 只留给孩子级别信息（时间戳、计数、`v1.0`、占位符）。

### P0-5 全大写标签没有字距

`.form-label`（[`components.css:143`](../static/css/modules/components.css#L143)）设了 `text-transform: uppercase` 但**没有 `letter-spacing`**。同类共 6 处：

- `components.css:143` `.form-label`
- `modal-tools.css:2784` `.field-label`
- `modal-detail.css:2752` `.topbar-token-label`
- `modal-tools.css` `.adv-section-title`
- `modal-automation.css` `.logic-label`
- `advanced-editor.css` `.advanced-log-entry strong`

默认字距是为句首大写调校的，全大写会挤在一起。Refactoring UI 的规则是补 `~0.05em`。

顺带：项目里已有 40 处 `letter-spacing: 0.08em`、13 处 `0.04em`、8 处 `0.1em` 等 **15 个不同字距值**，也应收敛到 0.05em 一档。

**建议**：给上述 6 处补 `letter-spacing: 0.05em`；全站字距值收敛到 1–2 档（当前有 **17 个不同字距值**：`0.08em`×40、`0.04em`×13、`0.1em`×8、`0.02em`×7、`0.05em`×6、`0.06em`×6、`0.12em`×6 等）。

---

## 四、P1 — 标尺缺位

> "The single biggest cause of amateur-looking UI is picking values ad hoc — 17px here, `#3B82F6` there, `lighten(5%)` for a hover state. Design *from a scale*, always."

### P1-1 没有字号标尺

**证据**：1179 条 `font-size` 声明用了 **90 个不同值**，项目内**零个字号 token**（`--text-*`、`--fs-*`、`--font-size-*` 均不存在）。90 个值里有 `0.58rem`(9.28px)、`0.61rem`(9.76px)、`0.63rem`(10.08px)、`0.67rem`(10.72px)、`0.69rem`(11.04px)、`0.71rem`(11.36px)、`0.74rem`(11.84px) 这类**相差不到 1px 的邻居值**——它们之间不存在"哪个更对"的判断依据，只能靠手感。

**建议**：在 [`static/css/modules/ui-refresh.css:10`](../static/css/modules/ui-refresh.css#L10) 已有的 `:root` 块里补字号标尺（那里已经放了 `--ui-radius-*`、`--ui-control-height`，是现成的 token 落点）：

```css
--text-xs: 0.75rem;   /* 12 */
--text-sm: 0.875rem;  /* 14 */
--text-md: 1rem;      /* 16 */
--text-lg: 1.125rem;  /* 18 */
--text-xl: 1.25rem;   /* 20 */
--text-2xl: 1.5rem;   /* 24 */
--text-3xl: 1.875rem; /* 30 */
```

7 档覆盖 90 个值中的绝大多数。**不要用 `em`**——`em` 相对父字号，嵌套后会产生不在标尺上的值（项目里已有 5 处 `em` 字号：`0.92em`×2、`1.3em`×1、`1.5em`×1、`0.9em`×1，另有 **12 处 `clamp()` 字号（11 个不同表达式）**，产出值同样不在标尺上）。

### P1-2 574 条小于 12px 的声明

**分布**（前 10 位）：

| 值 | 实际 px | 次数 |
|---|---|---|
| `0.68rem` | 10.88 | 101 |
| `0.72rem` | 11.52 | 98 |
| `0.7rem` | 11.20 | 74 |
| `10px` | 10 | 54 |
| `0.64rem` | 10.24 | 34 |
| `11px` | 11 | 36 |
| `0.66rem` | 10.56 | 28 |
| `0.62rem` | 9.92 | 24 |
| `0.6875rem` | 11 | 18 |
| `0.65rem` | 10.40 | 16 |
| `9px` | 9 | 13 |

集中在：`modal-detail.css`(130)、`modal-tools.css`(110)、`layout.css`(81)、`automation-workbench.css`(73)、`advanced-editor.css`(64)、`modal-settings.css`(65) —— 全是**信息密集的工具型界面**。

**必须说清楚的两件事**：

1. **这是产品定位，不是缺陷。** 这类管理工具在桌面端确实需要高信息密度。Refactoring UI 也承认 "Dense UIs (dashboards) are legitimate — but as a deliberate decision"。
2. **但 574 条里绝大部分不是"刻意的密度决定"，而是 P1-1 所述"没有标尺"的副产品**——`10.88px` 和 `11.52px` 之间的差别没有人能感知，它只是 `0.68rem` 和 `0.72rem` 恰好被写下来了。

**建议分两步，风险从低到高**：

- **第一步（低风险）**：`9px`(13) + `8px`(1) + `0.5rem`(1) 共 15 条抬到 12px。这些低于任何合理密度下限。
- **第二步（中风险）**：把 10–11.99px 的区间**归并到 12px 与 14px 两档**。这一步必然影响布局（小字变大 → 容器变高/换行），必须在 `tmp/ui-preview/` 的截图链路上逐屏回归，**不能一次性全局替换**。

### P1-3 间距 66.3% 越界

**证据**：2753 条声明，1824 条不在 `4 8 12 16 24 32 48 64 96 128 192 256` 标尺上。

高杠杆的三个值（合计 533 处）：

| 现用值 | 实际 px | 次数 | 建议归并到 |
|---|---|---|---|
| `0.35rem` | 5.6 | 208 | `0.25rem`(4px) 或 `0.5rem`(8px) |
| `0.45rem` | 7.2 | 171 | `0.5rem`(8px) |
| `0.55rem` | 8.8 | 154 | `0.5rem`(8px) |

这三个值在 4px 与 8px 之间制造了一个"5.6/7.2/8.8"的伪细分层。它带来的不是更精准的控制，而是**每个组件作者都要重新猜一次"这个间距该用 0.35 还是 0.45"**。

**建议**：建 `--space-1..8` = 4/8/12/16/24/32/48/64，先做上述三组替换（收益最大、改动最机械），再逐步收其余。

### P1-4 圆角 106 个值 / 5 套 token 家族

| 家族 | 定义位置 | 取值 |
|---|---|---|
| `--ui-radius-*` | `ui-refresh.css:11–14` | 0.45 / 0.65 / 0.85 / 1rem |
| `--chat-radius-*` | `view-chats/tokens.css:3–6` | 3 / 4 / 6 / 8 px |
| `--beautify-radius-*` | `view-beautify.css` | 4 / 6 / 8 px |
| `--resource-workbench-radius` | `resource-workbench.css` | 8px |
| `--preset-editor-panel-radius` | `modal-preset-workbench.css` | 8px / 6px（且在同一文件里被重定义 4 次） |

另有 Tailwind 默认圆角作为第 6 套并行生效：`rounded`×197（4px）、`rounded-lg`×27（8px）、`rounded-xl`×46（12px）、`rounded-2xl`×66（16px）、`rounded-full`×45。

Refactoring UI 的规则很简单：**选一套，保持一致。** 小圆角偏中性、大圆角偏俏皮、无圆角偏正式；**同一界面里混用方角和圆角一定更难看。** 当前 106 个值里，`0.65rem`(10.4px)、`0.7rem`(11.2px)、`0.72rem`(11.5px)、`0.75rem`(12px)、`0.8rem`(12.8px) 全都同时存在——这些是肉眼几乎不可辨但确实不一致的值。

**建议**：统一到 4 档（建议 4 / 8 / 12 / 16px），其余 4 套家族整体替换为对 `--ui-radius-*` 的别名，保留名称但指向同一组值，避免大范围重命名。

### P1-5 阴影 288 个值，但只有 1 档 elevation

**证据**：288 个不同 `box-shadow` 值；项目只定义了 `--shadow-elevation`（[`variables.css:371`](../static/css/modules/variables.css#L371)，深色 / `:580` 浅色）。另有 16 处使用 `var(--shadow-sm|md|lg|xl, <fallback>)` —— 这些 token **从未定义**，实际生效的全是各文件里各写各的 fallback。

更关键的是**深色模式下阴影几乎不起作用**。当前 `--shadow-elevation` 用的是 `rgba(2, 6, 23, 0.52)`——在 `#0b1220` 的页面上，这层黑几乎看不见。而项目恰恰是**深色为主**（`color-system.css:10` 设 `color-scheme: dark`）。

Refactoring UI / `references/systems.md` 对此有明确结论：

> **Don't invert the ramp mechanically.** 暗色下 "raised is lighter than the page" 依然成立，但**阴影在深色表面上几乎登记不上，所以明度必须独自承担深度线索**。相邻灰阶通常不到 1.3:1，所以抬升的深色表面通常还需要一条**发丝边框**才能读作"抬起来了"。

当前的项目其实**已经做对了一半**：`--surface-page #0b1220` → `--surface-container #111c2d` → `--surface-container-raised #17243a` → `--surface-container-hover #1e2f49`，明度确实逐级抬升。缺的是：

1. 没有 5 档 elevation，所有浮层共用一个阴影值；
2. 抬升表面缺少与明度配套的发丝边框（`--border-subtle` 已存在但未系统配给抬升层）。

**建议**：建 5 档 elevation（Refactoring UI 标准值），并在深色模式下显式让"更亮的表面 + 发丝边框"承担抬升，阴影只作补充。**不要两套混用**（技能明确要求同一项目里只用一种阴影体系）。

### P1-6 Tailwind 默认值构成第二套标尺

Tailwind 在 `templates/layout.html:26` 于 `style.css` **之后**加载，其默认 scale 与项目标尺并行生效且互不约束：

| Tailwind 类 | 次数 | 实际值 | 与项目标尺的关系 |
|---|---|---|---|
| `text-xs` | 333 | 12px | = 项目标尺下限（尚可） |
| `text-sm` | 160 | 14px | = 标尺（尚可） |
| `text-base` | 35 | 16px | = 标尺（尚可） |
| `rounded` | 197 | 4px | 与 5 套 token 家族无关 |
| `rounded-2xl` | 66 | 16px | 同上 |
| `rounded-xl` | 46 | 12px | 同上 |
| `shadow-2xl` | 8 | `0 25px 50px -12px` | 第 288+1 个阴影值 |
| `shadow-sm/md/lg/xl` | 33 | 各自默认值 | 又一套阴影 |
| `font-bold` | 208 | 700 | 与 P0-3 叠加 |

**建议**：**优先改 [`tailwind.config.cjs:8`](../tailwind.config.cjs#L8) 的 `theme.extend`**，让 Tailwind 直接吐项目值：

```js
theme: {
  extend: {
    fontSize: { /* 对齐 --text-* */ },
    borderRadius: { /* 对齐 --ui-radius-* 4 档 */ },
    boxShadow: { /* 对齐 5 档 elevation */ },
  },
}
```

改约 12 行 config，一次性消除模板层 1000+ 处不一致，且 `tailwind.css` 是生成产物、`npm run build:css` 重新生成即可。这比逐处改模板便宜一个数量级。

---

## 五、P2 — 可读性与触达

### P2-1 触控目标小于 24×24

WCAG 2.2 (2.5.8) AA 要求指针目标至少 24×24 px。实测 40+ 处低于此值：

| 选择器 | 高度 | 文件 |
|---|---|---|
| `.sort-btn-xs` | **14px** | `components.css:755` |
| `.preset-editor-action-button` | 16.8px | `modal-preset-workbench.css` |
| `.ui-number-stepper-btn` | 16px | `advanced-editor.css` |
| `.wi-grid-tool-btn` | 18.4px | `resource-workbench.css` |
| `.settings-number-stepper-btn` | 20px | `modal-settings.css:1955` |
| `.preset-card-action` | 18.4px | `resource-workbench.css` |
| `.card-local-note-btn` / `.card-forum-search-btn` / `.card-send-st-btn` / `.card-source-update-btn` | 23.2px | `view-cards.css` |
| `.btn-note-preview` | 20px | `view-cards.css` |
| `.tag-category-manager-color` | 22.4px | `modal-tools.css` |

**建议**：可见尺寸可以保持（密集工具栏有正当理由），但**点击热区必须补足到 24×24**——用 `::before` 伪元素扩展或 `padding` + 负 `margin`，视觉不变。

### P2-2 全局 Toast 没有 live region

[`templates/layout.html:67`](../templates/layout.html#L67) 是全站唯一的 Toast 容器：

```html
<div class="toast-notification" :class="{'show': showToastState}">
```

**没有 `role="status"`，没有 `aria-live`。** 这意味着屏幕阅读器用户收到不到任何操作反馈——而 Toast 恰恰是本项目**唯一的**全局反馈通道（批量操作、保存成功/失败、导入结果全靠它）。

全站有 56 处 `aria-live`，唯独这个最重要的漏了。

**建议**：加 `role="status" aria-live="polite" aria-atomic="true"`。改动 1 行，修复全站反馈可访问性。

### P2-3 `<label>` 266/296 无 `for=`

296 个 `<label>` 中仅 30 个有 `for=`。点击标签文字不聚焦对应输入框，屏幕阅读器也无法关联。

**建议**：优先修 `settings.html`、`advanced_editor.html`、`detail_card.html` 三个表单最密集的模板。

### P2-4 45 个表单控件完全无 class

289 个表单控件（排除 checkbox/radio/range/file/hidden）中 45 个完全没有 `class`，直接使用浏览器默认外观。它们与主题化的 `.form-input` / `.ui-primitive-field__input` 并排出现时，视觉上是两套控件。

**建议**：统一到 `.form-input`。项目已有 `styled_select.html` 这类高质量封装（32 + 15 次使用），说明模式是可行的，只是覆盖不全。

### P2-5 图标尺寸被局部覆写

[`icons.css:89–122`](../static/css/modules/icons.css#L89) 定义了干净的 7 档：12/16/20/24/32/48/64。但**同文件 `:130–188` 又为 `.sidebar` 覆写了一遍**（xs→16、sm→20、md→24、lg→32），接着又为 `.sidebar-filter-label` 覆写了第三遍（xs→20、sm→24），再为 `.sidebar-nav-icon-slot` 覆写第四遍。

后果：`ui-icon--sm` 在模板中用 899 次，在侧栏里是 20px、在其他地方是 16px、在侧栏筛选行里是 24px。**同一个类名在不同上下文里是三种尺寸**，`--sm` 这个名字不再有意义。

Refactoring UI 对图标的原则是"**永远不要把图标缩放得离它的设计尺寸太远**——16–24px 的图标放到 48px 会显得又粗又缺细节；需要更大存在感时，把它放进一个彩色圆/方形容器里"。

**建议**：侧栏的四层覆写收敛为一层；`ui-icon--3xl`(64px) 的 3 处使用检查是否为装饰性空状态图标，若是则改为"小图标 + 彩色圆形底"。

---

## 六、P3 — 结构性工程债

这些不直接造成视觉问题，但它们**使前面所有优化都变得更贵**。

### P3-1 级联无法控制

- **1676 处 `!important`**
- **0 个 `@layer`**
- **93 个选择器深度 > 4，最深 10 层**

三者互为因果。没有 `@layer` 就只能靠提高特异性取胜；特异性打不过就用 `!important`；用了 `!important` 就只能再用更长的选择器压过去。`.wi-entry-history-modal > .flex-1 > div:last-child .grid > div > div:last-child` 是这个过程走到尽头的产物——它同时依赖 DOM 结构和兄弟顺序。

**建议**：引入 `@layer base, components, utilities;` 骨架（`color-system.css` 已是"最终覆盖层"，是最自然的起点）。**这是唯一能让后续重构成本下降的改动。**

### P3-2 391 个同文件重复选择器

`layout.css` 57、`view-beautify.css` 56、`modal-tools.css` 42、`modal-preset-workbench.css` 38、`automation-workbench.css` 27。

例：`.preset-editor-workbench` 在 `modal-preset-workbench.css` 里定义了 3 次；`.card-advanced-filter-module-card` 在 `layout.css` 里 4 次。

多数是"后续追加覆盖"，属于历史分层。**建议**：合并时保留最后一个声明块的值，中间的被覆盖声明删除——这不会改变渲染结果（可逐文件用截图 diff 验证）。

### P3-3 `.sidebar` 定义两次，第一份是死代码

[`layout.css:1720`](../static/css/modules/layout.css#L1720)：

```css
.sidebar {
  width: 300px;
  background-color: color-mix(...);
  backdrop-filter: blur(10px);      /* ← 无效 */
  border-right: 1px solid var(--border-subtle);
  ...
}
```

[`layout.css:1738`](../static/css/modules/layout.css#L1738)：

```css
.sidebar {
  width: clamp(288px, 22vw, 336px);  /* 覆盖 300px */
  min-width: 288px;
  background-color: var(--sidebar-surface);
  backdrop-filter: none;             /* 覆盖 blur(10px) */
  -webkit-backdrop-filter: none;
  ...
}
```

第二块完整覆盖了第一块的 `width` 和 `backdrop-filter`。第一块只剩 `display:flex`、`flex-direction`、`flex-shrink`、`position` 有效。

**顺带一提**：`backdrop-filter: blur(10px)` 虽然被覆盖了，但它与 [`static/css/modules/base.css:46`](../static/css/modules/base.css#L46) 及 `tests/test_fullscreen_scrim_compositing_contracts.py` 所守护的"绝不在 shell 上放 backdrop-filter"的约定**方向相反**。虽然测试只覆盖 `.main-container`，代码意图上是矛盾的。

**建议**：删掉 `:1720` 块中的 `width` 与 `backdrop-filter`，或直接合并两块。

**另一处同类问题**：[`static/css/modules/base.css:183`](../static/css/modules/base.css#L183) 用 `!important` 把 `--app-font-family` 强加给 `body, button, input, textarea, select`。`--app-font-family` 默认值是 `ui-sans-serif, system-ui, sans-serif`（[`variables.css:12`](../static/css/modules/variables.css#L12)），而 `base.css:25` 在 `body` 上手工写了 8 个 fallback 的字体栈。**结果：`base.css:25` 那 8 个 fallback 从未生效**，因为它们被 `:183` 的 `!important` 覆盖了。同时 `--fallback-fonts`（含中文 `Noto Sans SC`/`PingFang SC`/`Microsoft YaHei`）**定义了但零引用**——中文字体回退链实际上没有接上。

### P3-4 五套 UI 原语并存

| 体系 | 定义位置 | 模板使用量 |
|---|---|---|
| `.ui-primitive-*` | `ui-primitives.css`（508 行，写得最规范） | **0**（仅插件 JS 用） |
| `.ui-modal-*` 共享壳 | `ui-refresh.css` | 19 / 24 个含遮罩的模板 |
| `.btn-*` 应用层 | `color-system.css:760+` | primary 34 + secondary 140 |
| 模块自绘 | `beautify-*`、`gacha-*`、`wi-*`、`preset-*`、`automation-*`、`detail-*`、`settings-*`、`tag-*`、`chat-*` | 191 个按钮类名 |
| Tailwind 原子类 | 模板内联 | 1000+ |

**[`ui-primitives.css`](../static/css/modules/ui-primitives.css) 是这套代码库里质量最高的 UI 代码**：只用语义 token、不用十六进制、遵守 `prefers-reduced-motion`、有完整状态。但它是为插件 API 写的，宿主自己一次都没用。

**建议（最大单点收益）**：让宿主模板逐步改用 `.ui-primitive-*`。方向是 "把已经写好的正确实现用起来"，而不是新写一套。

### P3-5 41 个未定义令牌，5 个无 fallback（含 2 个真 bug）

**无 fallback = 命中即静默失效**（CSS 变量未定义且无 fallback 时，整条声明在计算值阶段被丢弃）：

| 令牌 | 引用位置 | 后果 |
|---|---|---|
| `--accent-tint` | [`worldbook-update.css:16`](../static/css/worldbook-update.css#L16) | **真 bug**：`.wb-update-tabs [aria-pressed="true"]` 的选中态没有背景色 |
| `--border-danger` | [`ui-primitives.css:261`](../static/css/modules/ui-primitives.css#L261) | `.ui-primitive-error` 的边框消失 |
| `--surface-violet` | [`view-wi.css:4221`](../static/css/modules/view-wi.css#L4221) | 该元素背景声明被丢弃 |
| `--action-text-hover` | [`modal-preset-workbench.css:121`](../static/css/modules/modal-preset-workbench.css#L121), `:642` | 两处 hover 文字颜色失效，回退到继承值 |
| `--danger-text` | `worldbook-update.css:20`（**有** fallback `#d74d59`） | 能显示，但用的是硬编码色，与 `--status-danger-*` 体系脱节 |

其余 36 个（`--font-mono`、`--shadow-sm/md/lg/xl`、`--tag-cat-*-d...`、`--ui-grid-*` 等）多数带 fallback，或由 JS 注入（`--app-viewport-height`、`--ui-icon-mask`、`--ui-grid-gap`、`--ui-split-left` 已确认由 `state.js` / `uiPrimitives.js` 写入），属于**未命名的局部标尺**而非 bug。

**建议**：
1. 直接修 2 个真 bug（`--accent-tint` 改 `--accent-soft`；`worldbook-update.css` 的硬编码红色改 `--status-danger-*`）；
2. 补 `--border-danger`、`--surface-violet`、`--action-text-hover` 定义；
3. 把 `--shadow-sm/md/lg/xl` 提升为正式的 5 档 elevation（与 P1-5 合并做）；
4. 建测试断言"无未定义 `var()` 引用"（见第八节）。

**另注**：`worldbook-update.css` 整体是这套代码库的规范例外——58 行里大量硬编码色（`#070b14`、`#e9516080`、`#45bb72`、`#d74d59`、`#d85f6a`、`#379657`、`#b72e392b` 等），且 `z-index: 1200` 为原始数字而非令牌。考虑整体迁移到语义 token。

---

## 七、优化路线

按"投入产出比"排序，而不是按严重程度。前两档改动小、风险低、可独立验证。

### 第 1 档：30 分钟（立即可做，零布局风险）

| 项 | 改动量 | 收益 |
|---|---|---|
| 修 P3-5 的 2 个真 bug | 2 行 | 修复失效的 UI 状态 |
| Toast 补 `aria-live`（P2-2） | 1 行 | 全站反馈可访问性 |
| 6 处全大写标签补 `letter-spacing`（P0-5） | 6 行 | 可读性 |
| 删除 `.sidebar` 死代码块（P3-3） | ~10 行 | 消除矛盾 |

### 第 2 档：半日（建标尺，不动组件）

1. 在 `ui-refresh.css:10` 补 `--text-*`、`--space-*` 标尺；
2. 补 5 档 elevation token，与 `--shadow-sm/md/lg/xl` 合并；
3. 补 3 个缺失令牌定义；
4. 改 `tailwind.config.cjs` 的 `theme.extend` 对齐项目标尺，`npm run build:css` 重新生成；
5. 建 `tests/test_design_token_contracts.py`（见第八节）。

**这一档做完，后面两档的成本会显著下降**，因为有了可引用的目标值。

### 第 3 档：1–2 日（层级修复，改动面中等）

1. **P0-1 动作层级三级化**：`.btn-primary` 改实心 accent；`.btn-secondary` 保持 tint；新增 `.btn-tertiary` 链接式。涉及 `color-system.css:760–795`，需同步 `tests/test_color_system_contracts.py:102` 的断言。
2. **P0-2 单页单 primary**：从 `detail_chat_reader.html`(33) 开始，逐个视图判定。
3. **P0-3 字重收敛**：7 个非标准字重（183 条）→ 500/700，208 个 `font-bold` 降级。
4. **P0-4 文本色用法**：muted 501 次逐个判定回 primary/secondary。

### 第 4 档：多日（标尺落地，需逐屏回归）

1. **P1-2 小字收敛**：先 15 条 <10px，再 574 条 10–11.99px 归并到 12/14 两档；
2. **P1-3 间距标尺**：先替换 0.35/0.45/0.55rem 三组（533 处）；
3. **P1-4 圆角统一**：5 套家族收敛到 4 档；
4. **P3-4 原语合并**：从已在用 `.ui-modal-shell` 的 19 个模板推进到剩余 5 个（`context_menu`、`folder_operations`、`forum_thread_preview`、`gacha_draw`、`tag_filter`）；`.ui-primitive-*` 的宿主侧接入是更大的独立工程。
5. **P3-1 `@layer` 引入**：放在最后，因为一旦引入，所有既有特异性假设都要重新验证。

---

## 八、验收方式

### 自动化契约测试

建议新增 `tests/test_design_token_contracts.py`：

```python
# 1) 标尺令牌存在
assert '--text-md' in variables_css
assert '--space-4' in variables_css
assert '--elevation-3' in variables_css

# 2) 无未定义 var() 引用（41 → 0）
#    解析所有 var(--x) 引用，比对所有 --x: 定义 + JS 注入白名单

# 3) 无 <12px 字面量（或允许显式白名单）
#    正则 font-size: (0\.[0-7]\d*rem|\d+px)，断言命中数 ≤ 白名单长度

# 4) 圆角值只来自 --ui-radius-* 家族
#    断言 border-radius 字面量集合 ⊆ 4 档白名单

# 5) 字重只有 400/500/600/700
#    断言 font-weight 字面量集合 ⊆ {400, 500, 600, 700}
```

`tests/test_color_system_contracts.py` 已有 Node 端对比度校验的先例（`:141`、`:199`），可以复用同样的 `subprocess + node` 模式做运行时 token 校验。

### 现有测试的适配点

**47 个测试文件断言 CSS 字符串**，其中若干会阻挠本次优化，实施前需同步：

| 测试 | 断言内容 | 影响 |
|---|---|---|
| `test_color_system_contracts.py:102` | `.btn-primary` 必须是 `--action-surface` | **直接冲突** P0-1，改按钮层级时必须同步改 |
| `test_wi_editor_frontend_contracts.py:167` | `font-size: 0.75rem;` 必须在 `.wi-editor-tool-menu` | 影响 P1-2 小字收敛 |
| `test_wi_editor_frontend_contracts.py:186` | `font-size: 0.72rem;` 必须在 tiny 菜单 | 同上 |
| `test_wi_editor_frontend_contracts.py:869` | `placeholder:text-[10px]` 至少 3 处 | 同上 |
| `test_fullscreen_scrim_compositing_contracts.py:65` | `.main-container` 不得有 `backdrop-filter` | P3-1/P3-3 涉及 |

### 视觉回归

仓库已有可复用的截图链路：`tmp/ui-preview/`（含 `preview_server.py`、`shot.py`、`shots/`、`shots-final/`），以及 `full-1600.png` / `full-1024.png` 两个基准全页图。**每档改动后在此链路上逐屏比对。**

---

## 九、显式假设与不做的事

### 不做

- 不修改任何 CSS / 模板 / JS（本次只产出审计）；
- 不评估配色（第一节已说明：配色合格，不是问题）；
- 不触碰第三方边界：`static/lib/**`（holo-cards、pokemon-cards）、`static/vendor/sillytavern/**`、Beautify 用户自定义 CSS；
- 不触碰生成产物：`docs/plugin-api.md`、`static/js/utils/iconMap.js`、`static/css/tailwind.css`（后者通过 `npm run build:css` 重新生成，不手改）；
- 不评估插件 API 与业务逻辑。

### 假设

1. **深色模式是主场景** —— `color-system.css:10` 设 `color-scheme: dark` 为默认，浅色是 `html.light-mode` 覆盖。P1-5 的 elevation 建议基于此。
2. **中文语境下 12px 是可用下限** —— 574 条小字里真正需要上抬的是 <10px 的 15 条，10–11.99px 更多是标尺缺失所致而非不可读。
3. **高信息密度是产品定位**，不是缺陷 —— 这是桌面端卡片/世界书管理器，密集工具栏成立。因此本报告**不建议"疏朗化"**，只建议"收敛到标尺"。

### 已知风险

1. **全局字号/间距调整会破坏既有布局** —— 5000+ 行 CSS 中的尺寸假设是耦合的（尤其 `detail_card.html` 4477 行、`tag_filter.html` 2953 行这类巨型模板）。**必须逐屏推进，不能一次性全局替换。**
2. **动作层级改动会被现有契约测试拦下** —— `test_color_system_contracts.py:102` 是硬断言，需与实现同步修改，而不是绕过。
3. **`@layer` 引入有"隐藏回归"风险** —— 引入后，所有依赖选择器特异性的既有覆盖关系都会重新排序。这是为什么它排在路线最后一档。
4. **Token 收敛的收益是渐进的** —— 第 2 档只建标尺不改组件，短期内**视觉上没有任何变化**。这是预期行为：标尺的价值在于让后续每一处修改变成"选一个值"而不是"发明一个值"。

---

## 十、实施记录（2026-10-19）

第 1–3 档已落地。全量测试 **3789 通过 / 11 失败**，且 11 个失败**全部为实施前既有**
（已在改动前的干净工作区上复现，根因是 `UnicodeDecodeError: 'gbk' codec` —— 这些测试
用 `Path.read_text()` 读中文模板，依赖系统默认编码，与本机 UTF-8 环境不符）。
改动**未引入任何新失败**。

### 已实施

| # | 改动 | 文件 | 说明 |
|---|---|---|---|
| 1 | 修 `--accent-tint` 未定义 | `worldbook-update.css:16` | 改为 `--accent-soft`，标签选中态背景恢复 |
| 2 | 修 worldbook 硬编码红/绿 | `worldbook-update.css:20,32-42` | 6 处硬编码色 → `--status-danger-*` / `--status-success-*` |
| 3 | `--border-danger` 未定义 | `ui-primitives.css:261` | 改为 `--status-danger-border` |
| 4 | `--surface-violet` 未定义 | `view-wi.css:4221` | 改为 `--decoration-violet-surface` |
| 5 | `--action-text-hover` 未定义 | `modal-preset-workbench.css:121,642` | 改为 `--action-text` |
| 6 | 新增 `--font-mono` | `variables.css:13` | 8 处引用此前一直走 fallback |
| 7 | Toast 可访问性 | `templates/layout.html:67` | 加 `role="status"` + `aria-live="polite"` + `aria-atomic` |
| 8 | 6 处全大写标签补字距 | `components.css` `modal-tools.css`(×2) `modal-detail.css` `advanced-editor.css` `modal-automation.css` | 统一 `letter-spacing: 0.05em` |
| 9 | `.sidebar` 死代码合并 | `layout.css:1720/1738` | 删除被完全覆盖的第一块（含矛盾 `backdrop-filter: blur(10px)`） |
| 10 | **五套标尺落位** | `ui-refresh.css:10-89` | 字号 7 档 / 间距 8 档 / 圆角 4 档 / 字重 2 档 / 层级 5 档 |
| 11 | 圆角家族收敛 | `ui-refresh.css` + `resource-workbench.css` + `modal-preset-workbench.css` | `--ui-radius-*`(7.2/10.4/13.6/16) → 4/8/12/16；`--preset-editor-panel-radius` 5 处定义统一；`--resource-workbench-radius` 指向令牌 |
| 12 | Tailwind 第二标尺消除 | `tailwind.config.cjs` + 重新生成 `tailwind.css` | 阴影 6 档全部指向 `--elevation-*`，圆角指向 `--radius-*`；产出中已无硬编码阴影字面量 |
| 13 | **动作层级三级化** | `color-system.css:759-820` | `.btn-primary` 改实心 `--accent-action`（4.94:1）；新增 `.btn-tertiary` |
| 14 | **字重收敛** | 24 个 CSS 文件，183 处 | `650/bold`→600；`750/760/800/850/900`→700 |
| 15 | 新增契约测试 | `tests/test_design_token_contracts.py` | 8 个用例，锁住标尺存在性、未定义令牌、全大写字距、primary 实心、Toast live region |
| 16 | 同步更新契约测试 | `tests/test_color_system_contracts.py:102` | 断言从"必须是浅 tint"改为"必须实心"，并校验三级齐全 |

### 量化结果

| 指标 | 实施前 | 实施后 |
|---|---|---|
| `font-weight` 不同值 | 12 个（含 650/750/760/800/850/900/bold） | **5 个**（400/500/600/700 + inherit） |
| 非标准字重声明 | 183 条 | **0** |
| 未定义 CSS 令牌 | 41 个 | **31 个，全部为 JS 运行时注入** |
| Tailwind 硬编码阴影 | 6 个档位独立 | **0**，全部指向 `--elevation-*` |
| 圆角 token 家族 | 5 套互不相干 | 主家族统一到 4/8/12/16；chat/beautify 保留其刻意的紧凑子标尺 |
| `.sidebar` 定义 | 2 次（第 1 次为死代码） | 1 次 |
| 测试 | 3781 通过 / 11 失败 | **3789 通过 / 11 失败（同 11 个既有失败）** |

### 未实施（附原因）

| 项 | 为什么没做 |
|---|---|
| **P1-2 小字收敛（574 条 <12px）** | 纯视觉批量改写，本环境**无法启动浏览器截图**（Playwright 在 DSH 沙箱里创建管道被拒：`WinError 5`）。无视觉回归就批量改 574 处字号，风险高于收益。已把标尺建好，逐屏迁移可随时进行。 |
| **P1-3 间距收敛（66.3% 越界）** | 同上。`0.35/0.45/0.55rem` 合计 533 处，其中 `gap` 352 处、`padding` 291 处 —— 改间距会真实改变布局盒模型，**必须逐屏看**。 |
| **P2-1 触控目标 <24px** | 40+ 处需要逐个用 `::before` 扩展热区，同样需要渲染验证是否遮挡相邻元素。 |
| **P2-3 `<label for=>` 266 处** | 机械但量大，且部分 label 是包裹式（无需 `for`），需逐个判断。 |
| **P2-4 45 个无 class 表单控件** | 需先确认每个的上下文样式，盲加 `.form-input` 可能覆盖既有内联样式。 |
| **P3-1 `@layer` 引入** | 按原计划排在最后：引入后所有依赖特异性的覆盖关系会重排，**必须配合完整视觉回归**。 |
| **P3-2 391 个重复选择器合并** | 同样需要视觉回归确认"删除被覆盖声明不改变渲染"。 |

### 关于「无法视觉验证」的说明

本次实施**全程只有静态验证**（契约测试 + CSS 语法/括号平衡 + 令牌可解析性 + 服务端
实际返回的 CSS 内容比对），**没有渲染截图**。原因：Playwright 在 DSH Windows 沙箱中
无法创建子进程管道（`PermissionError: [WinError 5]`，属该沙箱已知边界）。

因此第 11、13、14 项（圆角、primary 实心、字重）虽然是**布局安全**的改动
（`border-radius` / `color` / `font-weight` 都不影响盒模型尺寸），仍建议合入后
在真实浏览器里过一遍这几个界面：设置页、详情页、自动化工作台、预设编辑器。

### 复现阶段注意

本机 pytest 需要绕过两处 UTF-8 环境问题（均未修改仓库文件）：

```powershell
$env:PYTHONPATH = "<repo>/tmp/pytest-shim"   # 见 tmp/pytest-shim/sitecustomize.py
$env:DSH_PYTEST_TMP = "<repo>/tmp/pytest-home"
python -m pytest tests/ -q --basetemp="$env:DSH_PYTEST_TMP\bt"
```

`sitecustomize.py` 处理的是：DSH 沙箱拒绝写入以 `0o700` 创建的目录，而
`tempfile.mkdtemp` 与 pytest 的 `tmp_path` 都用该模式。

## 十一、第二轮评审反馈与修正（2026-10-19 晚）

第一轮交付后收到的评审意见指出了四类问题。逐条核实后**全部成立**，其中两条是我引入的
回退。本节记录核实过程与修正。

### 11.1 反馈一：覆盖范围不够广

**成立。** 第一轮只做了「令牌层 + 字重 + 3 个 bug」，对 skill 规则的覆盖确实残缺。
逐条对照 Refactoring UI 的规则清单后，补出以下**此前完全未覆盖**的项：

| Skill 规则 | 第一轮状态 | 本轮 |
|---|---|---|
| 行宽 45–75 字符（`max-width: 20em–35em`） | **0 处覆盖** | 补 `.chat-message-content` 等 7 个阅读面到 `70ch` |
| 行高与字号成反比 | 22 个散值 | 正文 1.6 / 小字 1.45 / 大标题 1.25 三档 |
| 破坏性动作不用大红按钮 | 未处理 | 行内危险按钮改三级（hover 才显红），确认框内才实心红 |
| 颜色不是唯一信号 | 未处理 | 状态点补 1px 内描边 |
| 数字列等宽 + 右对齐 | 未处理 | 表格 `tabular-nums` |
| 空状态结构（图标+标题+说明） | 未处理 | 9 个空状态家族统一结构与间距 |
| 全大写需字距 | 6 处 | 已统一 `0.05em`（第一轮已做） |
| 图标不远离设计尺寸 | 未处理 | 图标按钮统一 20px 图标 |

同时补了**跨页面组件一致性**（11.4）。

### 11.2 反馈二：primary 按钮过于生硬、不融合

**成立，且是我引入的回退。**

第一轮我把 `.btn-primary` 改成了「不透明实心 accent + 白字」，理由是 skill 说
"primary → solid, high contrast"。但这是**对 skill 的生搬硬套**：

- 本项目是深色玻璃质感界面（surface 层层抬升 + 半透明 + 发丝边框 + 8% 透明描边）；
- 一块不透明的高饱和实心色在这种材质里会像贴纸一样浮在表面；
- **设置页的「保存并应用」按钮一直在用 `--action-surface` 染色底 + 描边 + 上浮**，
  那才是本项目的既有语言，而且它确实够突出。

skill 的原意是「primary 必须是这一屏视觉权重最高的操作」，而"实心"只是达成它的
其中一种手段。这里改用：**更大的 accent 染色浓度 + accent 描边 + accent 亮文字**。

实现：`background: --action-surface-hover`（accent 24%/15% 混合，比原 `--action-surface`
的 14%/9% 更浓）+ `border: --action-border-hover` + `color: --accent-text`。

实测对比度（双主题）：

| 主题 | primary 文字/底 | secondary 文字/底 |
|---|---|---|
| 深色 | **5.30:1** | 10.48:1 |
| 浅色 | **5.43:1** | 9.90:1 |

均过 4.5:1。视觉权重靠**色相与饱和**拉开（primary 是 accent 染色，secondary 是中性灰），
而不是靠不透明实心。

### 11.3 反馈三：全屏按钮浅色模式看不见 / embedded 徽章文字不清

**两个都核实为真，其中全屏按钮是我引入的。**

**(a) 预设阅览全屏按钮 —— 我引入的 bug，严重**

`templates/modals/detail_preset_popup.html:254`：

```html
class="preset-reader-header-icon-button btn-primary"
```

而 `.preset-reader-desktop-header .preset-reader-header-icon-button` 强制
`background: transparent !important`。第一轮我让 `.btn-primary` 的 `color` 变成
`--content-on-accent`（近白 `#f8fafc`），于是：

- 深色 header（`#17243a`）上白字：14.87:1 — 正常
- **浅色 header（`#f8fafc`）上白字：1.00:1 — 完全隐形**

复现路径明确：色块被模块规则强制透明，只剩文字色，而文字色被设成了"压在实心上"的颜色。

修正两处：
1. `.btn-primary` 的 foreground 改回 `--accent-text`（可压表面）；
2. 新增「图标按钮不得被文字语义污染」保护小节，把纯图标按钮的 primary 前景
   锁到 `--accent-text`，并注意特异性——模块规则
   `.preset-reader-desktop-header .preset-reader-header-icon-button.btn-primary`
   是 `(0,3,0)`，所以保护规则也必须抬到同档位以上，否则改了等于没改。

**(b) 世界书 embedded 徽章 —— 既有 bug（非我引入）**

`static/css/modules/view-wi.css` 原代码：

```css
html.light-mode .wi-badge.embedded {
  background: var(--decoration-violet);      /* #6d28d9 */
  color:      var(--decoration-violet-solid); /* #6d28d9  <- 同一个值 */
}
```

浅色模式下 `--decoration-violet` 与 `--decoration-violet-solid` **取值完全相同**，
对比度 **1.00:1**，徽章文字彻底隐形。

改成与其他徽章一致的配方：`--decoration-violet-surface` 底 + `--decoration-violet-solid`
文字 + 同色相描边，对比度 **1.00 → 6.03:1**。

### 11.4 反馈四：同类组件跨页面不一致

**成立，且是全局性问题。** 量化盘点：

| 组件 | 家族数 | 具体差异 |
|---|---|---|
| 关闭按钮 | **35 种 class 字符串** | 尺寸 2 / 2.4 / 2.5 / 2.65 / 2.75 / 3.35rem；圆角 0.45 / 0.6 / 0.65 / 999px；透明底 vs 实底混杂 |
| 图标按钮 | 15 个家族 | 2 / 2.25 / 2.4 / 2.5 / 2.65 / 2.75rem |
| 世界书来源徽章 | **4 套并行实现** | `.wi-badge`（999px 圆角、0.58rem）vs `.resource-source-badge`（5px、0.62rem）；`grid_wi.html:143` **同时挂了两个类** |
| 空状态 | 54 个 `*empty*` 类 | 结构、字号、间距各不相同 |
| 工具条 | 59 个 | 按钮高度与间距不齐 |

**用户举的两个例子都已坐实：**

1. **详情页 vs 设置页的关闭按钮**：
   - `.ui-detail-modal .detail-modal--workbench .detail-topbar-icon-action`：40px、`border-radius: 999px`（pill）、`transparent`
   - `.settings-icon-button`：44px、方角、`transparent`
   同类功能、两种形态。

2. **世界书徽章三处不一致**：列表页 / 卡片 / 全屏编辑各自实现，尺寸与配色都不同。

修正：新增**跨页面组件一致性层**（`ui-refresh.css` 末尾），用**普通类选择器**
（不是 `:where()`，见 11.5）把既有变体收拢到：
- 图标按钮尺寸三档（44 / 36 / 32px，按容器密度选，不一刀切）
- 统一 hover 语言（中性按钮 → 中性抬升；关闭按钮 → 危险语义）
- 徽章统一尺寸 + 四类来源统一「tint 底 + 同色相深文字 + 同色相描边」

### 11.5 关键教训：第一版一致性层用 `:where()`，完全无效

第一版我用 `:where(...)` 包裹所有选择器（以为低特异性更安全）。**这是错的**：

- `:where()` 特异性恒为 `(0,0,0)`；
- 模块规则如 `.ui-detail-modal .detail-modal--workbench .detail-topbar-icon-action`
  是 `(0,3,0)`，**直接盖掉**我的规则；
- 实测确认：详情页顶栏的 `border-radius: 999px` 和设置页的 44px 方形**都没被统一**。

第二版改为普通类选择器，并对高特异性模块规则双写同档位选择器 + `!important`。
契约测试里留了这条教训（`test_cross_page_consistency_layer_exists` 断言必须保留
「为何不用 :where()」的说明）。

### 11.6 中途失误：误删 `ui-refresh.css`

调整一致性层时用字符偏移截断文件，`IndexOf` 返回 -1 导致文件被写成 0 字节。
已 `git checkout` 恢复（原 1968 行），并重新应用了令牌层与一致性层。
教训：批量改写文件用精确字符串替换，不要用偏移量切割。

### 11.7 本轮量化结果

| 指标 | 第一轮后 | 本轮后 |
|---|---|---|
| 全站测试 | 3789 通过 / 11 失败 | **3794 通过 / 11 失败**（同 11 个既有失败） |
| 契约测试用例 | 8 | **13** |
| `--action-surface` 浅 tint 当 primary | 是 | 否（改用 strong 档） |
| 浅色全屏按钮对比度 | **1.00:1（隐形）** | 6.41:1 |
| 浅色 embedded 徽章对比度 | **1.00:1（隐形）** | 6.03:1 |
| 正文行宽限制 | 0 处 | 7 个阅读面 → 70ch |
| 图标按钮尺寸档 | 6+ 种散值 | 3 档标准 |
| 徽章实现 | 4 套并行 | 1 套（保留类名） |

### 11.8 本轮仍未做（附原因）

| 项 | 原因 |
|---|---|
| **小字 574 条 <12px 收敛** | 需逐屏视觉回归；本环境无法起浏览器（Playwright 在 DSH 沙箱创建管道被拒 `WinError 5`）。标尺已就位。 |
| **间距 66.3% 越界收敛** | 同上。`0.35/0.45/0.55rem` 合计 533 处，改 gap/padding 会真实改变盒模型。 |
| **删掉 35 个关闭按钮类名、合并为 1 个** | `tests/` 有 47 个文件断言 CSS 字符串，删类名会大面积撞契约。当前策略是"保留类名、统一观感"，视觉上已一致。 |
| **`@layer` 引入** | 引入后所有依赖特异性的覆盖关系重排，必须配合完整视觉回归。 |
| **触控目标 <24px 的 40+ 处** | 需逐个用伪元素扩展热区并验证不遮挡相邻元素。 |

### 11.9 需要真机复核的界面

本环境**只有静态验证**（契约测试 + CSS 语法 + 令牌可解析性 + 针对性对比度计算），
没有渲染截图。以下改动虽为布局安全（只动 color / border-radius / font-weight /
max-width），仍建议在真实浏览器逐屏确认：

1. 预设阅览模态（全屏按钮、header 图标组）— 浅色 + 深色各一遍
2. 世界书列表 / 卡片 / 全屏编辑（三处徽章并排对比）
3. 详情页顶栏（编辑 / 帮助 / 关闭三按钮，与设置页对照）
4. 聊天阅读器（正文行宽 70ch 后长消息的观感）
5. 自动化工作台（空状态与工具条）


## 十二、第三轮：级联实测推翻了我的实现方式

第二轮我把一致性层写进了 `ui-refresh.css`。**它实际上大部分没有生效**，而我当时
的判断是错的。这一节记录一次并行专项审计（含级联实测）得到的结论与修正。

### 12.1 根本错误：一致性层放在第 31 个 `@import`

`style.css` 的加载顺序里，`ui-refresh.css` 排第 **31** 位，后面还有 **13 个模块**：
`detail-card-workbench` / `automation-workbench` / `modal-preset-workbench` /
`advanced-editor` / `preset-rollback` / `resource-workbench` / `modal-plugin-manager` /
`modal-plugin-job` / `modal-gacha` / `ui-primitives` / `plugin-surfaces` /
`entry-dock` / `tooltip`。

CSS 同特异性时**靠源序决胜**。我的规则大多是 `(0,1,0)`～`(0,2,0)`，而后面这些模块
里同类选择器也是同档位 —— **它们在后面，所以它们赢**。结论：一致性层写了等于没写。

**修正**：拆出独立文件 `static/css/modules/consistency.css`，在 `style.css` 里作为
**最后一个** `@import`。并新增契约测试
`test_consistency_layer_is_imported_last` 守护这个顺序。

### 12.2 第二个错误：徽章规则特异性不足

`resource-workbench.css:916` 是
`.resource-grid-view .resource-source-badge.embedded` = `(0,3,0)`，
浅色模式那条 `html.light-mode .resource-grid-view .resource-source-badge.embedded`
更是 `(0,4,0)`。而我的规则只有 `(0,2,0)` —— 同样被压过。

这才是「世界书徽章在列表 / 卡片 / 弹窗 / 全屏编辑四处四种长相」的真正机制：

| 位置 | 生效规则 | 实际圆角 | 实际字号 |
|---|---|---|---|
| 列表卡片正面 `grid_wi.html:143` | `.resource-grid-view .resource-source-badge` (0,2,0) | **5px** | **0.62rem** |
| 列表卡片背面 `grid_wi.html:328` | 同上 + `.wi-card-back-source` | 5px | 0.6rem |
| 弹窗 `detail_wi_popup.html:56` | 仅 `.wi-badge`(0,1,0)，**无 `.resource-grid-view` 祖先** | **999px** | **0.58rem** |
| 全屏编辑 `detail_wi_fullscreen.html:37` | `view-wi.css:2859` 用 `!important` | **999px** | 10px |

**修正**：徽章四条变体全部抬到 `(0,4,0)`（用 `[class]` 补属性位 + `html.light-mode`
前缀双写），并加 `!important` 压过 `view-wi.css:2859` 的 `!important`。

### 12.3 实测确认的「真不一致」清单

专项审计对比了 5 组组件，逐项判断「真不一致」还是「合理差异」：

**关闭按钮**：8 档尺寸（2 / 2.4 / 2.5 / 2.65 / 2.75rem / 32 / 36 / 40px）、
7 种圆角（4 / 6 / 8 / 10px、0.45 / 0.6 / 999px）、4 种 hover 语义。

- **真不一致**：`.chat-reader-modal-close-button`(`reader-workbench.css:1080`)、
  `.batch-progress-close`(`components.css:580`)、`.forum-preview-close`
  (`modal-forum-preview.css:86`)、`.plugin-surface__close`(`plugin-surfaces.css:158`)
  这 4 个关闭按钮 hover 只有中性反馈，其余 10 个是危险红 ——
  用户学到「关闭悬停变红」，然后在聊天阅读器失效。
  **已全部并入危险 hover。**
- **合理差异**：`.batch-progress-close`(2rem) 在紧凑进度卡内（padding 0.9rem），
  小尺寸有理由。**保留 2rem 微缩档。**

**图标按钮**：17 个家族、7 档尺寸、7 档圆角、4 套 hover 变量
（`--state-hover-surface` / `--action-surface` / `--surface-container-hover` /
`--chat-reader-surface-hover`）。已收敛到 3 档尺寸 + 1 套 hover 语言。

**空状态**：CSS 内 **74 个** `*empty*` 类、6 档标题字号、3 种结构
（纯文本 / 图标+文字 / 图标+标题+描述+动作）、2 种边框（无 / 虚线）。
`plugin-manager-empty` 与 `plugin-job-empty` 是纯文本，而同屏
`extension-empty-state` 有图标+按钮 —— 同一产品内信息量差 3 倍。

### 12.4 相邻按钮分裂（用户投诉的原话）

**最刺眼的一处已坐实**，`templates/modals/detail_chat_reader.html:770-771`：

```
770: <button ... class="chat-toolbar-btn chat-toolbar-btn--primary chat-reader-regex-save-pill">保存</button>
771: <button ... class="chat-reader-icon-button chat-reader-modal-close-button">✕</button>
```

- 左「保存」：`border-radius: 999px` 胶囊 + 实心底 + 36px 高
- 右「关闭」：`border-radius: 4px` 方角 + `border: 0 !important` 全透明

**同一行、间隔 0.5rem，一个胶囊一个方角。** 同一模式在
`:1373/1376`、`:1423/1424`、`:1461/1469`、`:1501/1509` 重复 **5 次**。

**修正**：保存胶囊收回 `--radius-md`（不再用 999px），同容器按钮统一 36px 高。

其他相邻分裂（如实记录，未全改）：
- `detail_wi_fullscreen.html:427/436`：帮助按钮 accent hover vs 关闭 danger hover
  —— **合理差异**（语义不同），但确实是用户感知到的「左右两套」。
- `detail_card.html:317-357`：左工具条 36px + 20px 图标 vs 缩放条 26px + 16px 图标，
  同屏 38% 尺寸差。**真不一致，未改**（缩放条空间受限，需真机确认）。
- `grid_wi.html:160/170`：同一行 `wi-grid-tool-btn` 32px vs `wi-card-edit-btn` 28px。

### 12.5 关于测试冲突的一处误判（已更正）

专项审计报告称 `tests/test_advanced_editor_icon_contracts.py:82` 的
`assert '2.25rem' not in css` 是「反向断言，任何统一到 2.25rem 的方案都会立刻失败」。

**这条判断是错的。** 该断言的作用域是 `icons.css`（第 60 行
`css = read_project_file('static/css/modules/icons.css')`），约束的是**图标本身的
尺寸档**，不是图标按钮的容器尺寸。我在 `consistency.css` / `ui-refresh.css` 里用了
7 处 `2.25rem`，测试全绿即为证。

教训：引用「会撞什么测试」时必须先确认断言读的是哪个文件，不能只看断言文本。

### 12.6 本轮结果

| 指标 | 第二轮 | 本轮 |
|---|---|---|
| 全量测试 | 3794 通过 / 11 失败 | **3795 通过 / 11 失败**（同 11 个既有失败） |
| 契约测试用例 | 13 | **15** |
| 一致性层实际生效 | **大部分未生效**（源序输给 13 个后置模块） | 独立文件 + 最后加载，生效 |
| 关闭按钮 hover 语义 | 10 危险 / 4 中性分裂 | **14 全部危险** |
| 徽章特异性 | (0,2,0)，输给 (0,3,0)/(0,4,0) | 抬到 (0,4,0) + `!important` |
| 聊天阅读器保存胶囊 | 999px 胶囊 vs 4px 方角 | 统一 `--radius-md` + 同高 |

### 12.7 本轮仍未做

| 项 | 原因 |
|---|---|
| `detail_card.html` 36px 工具条 vs 26px 缩放条 | 缩放条在受限空间内，需真机确认放大后是否遮挡 |
| `grid_wi.html` 同屏 32px vs 28px 图标按钮 | 同上 |
| 空状态 74 个家族的逐一合并 | 只能逐屏改，且每个都要视觉确认信息量是否被改变 |
| 小字 / 间距 / `@layer` | 同 11.8，仍需视觉回归 |

### 12.8 方法论教训（写给后来的人）

1. **写 CSS 覆盖层之前，先确认加载顺序**。放在中间的文件，同特异性一定输给后面
   的模块。要么放最后，要么提高特异性，二者必须选一个 —— 我最初两个都没做。
2. **`:where()` 不是「安全」的同义词**。它让规则变得几乎不可能生效。
   要覆盖既有模块，必须正视特异性，而不是回避它。
3. **断言「会撞测试」前先读断言的读取路径**。只看文本会误判作用域。
4. **改文件用精确字符串替换，不要用字符偏移切割**。我用 `IndexOf` 返回值直接
   `Substring`，一次 -1 就把 2500 行文件写成了 0 字节。


---

## 附：证据复现方式

本报告所有数字均由脚本对本仓文件统计得出，主要口径：

| 指标 | 复现方法 |
|---|---|
| 字号分布 | 正则 `font-size:\s*([^;]+);` 全量 `static/css/**/*.css` 去重计数 |
| 标尺合规率 | 将 `rem` 换算为 px，比对 12/14/16/18/20/24/30/36/48/60/72 |
| 间距合规率 | 同上，比对 4/8/12/16/24/32/48/64/96/128/192/256 |
| 圆角/阴影去重 | 正则 `border-radius:` / `box-shadow:` 全量去重 |
| 字重分布 | 正则 `font-weight:\s*([^;!]+)`，排除 `!important` |
| 未定义令牌 | 收集所有 `--x:` 定义（含 JS 注入白名单），比对所有 `var(--x` 引用 |
| 对比度 | sRGB 相对亮度公式，逐对计算 token 组合 |
| 按钮/模态类名 | 正则 `^\.([a-z][a-z0-9-]*(?:btn|button))` / `modal` |

对比度验算覆盖：4 组 content × 6 组 surface、4 组 border、5 组 status-solid、6 组 decoration-solid、accent-action 上文字、action-surface 上文字与边框，深色与浅色主题各一遍。
