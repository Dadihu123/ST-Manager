# 角色卡「抽卡」改造 · 可行性分析与实施方案

> 目标：把「随机卡片」（`POST /api/random_card`，1 张）改造成二次元手游式抽卡：**单抽（开包动画）+ 十连抽（发牌 + 翻牌）+ 5 档稀有度**。
> 状态：**已实施完成，并按用户反馈返工一轮**。后端（§4.4 / §5.2）、图标（§5.1）、vendoring（§3）、前端弹窗、生图与无障碍均已落地，并在无头 Chrome 真机验证。
>
> **阅读顺序**：本文档第 8–148 行是**实施结果与返工记录（权威）**；从 §0 开始的 §0–§8 是**改造前的原始方案**，保留作为决策依据与技术勘察记录。两者冲突时**以实施结果为准** —— 原始方案里有几处已被实现推翻（例如「非交互卡注入静态光照」，见第 28 行的坑 5 及其勘误）。

---

## 实施结果（收尾记录）

### 落地文件

| 文件 | 说明 |
|---|---|
| `core/services/gacha_service.py` | 稀有度派生 + 抽取 + 保底 + 卡池边界 |
| `core/api/v1/cards.py` | `POST /api/draw_cards`；`_collect_draw_candidates` 补齐筛选；`random_card` 复用（顺带修掉 §5.2 末尾的既有 bug） |
| `tests/test_gacha_draw.py` | 40 passed |
| `templates/modals/gacha_draw.html` | 起手选择（点即开抽）/ 单抽舞台 / 单抽结果 / 十连网格 |
| `templates/components/gacha_card.html` | 揭晓用的「完整角色卡」macro（复用网格 CSS 类，不复用 grid_cards.html） |
| `static/js/components/gachaDraw.js` | Alpine 组件：抽取、pack-opener 编排、发牌、拖拽翻牌、WebAudio 音效 |
| `static/css/modules/modal-gacha.css` | 发牌 / 翻牌 / 卡背悬浮显影 / 稀有度辉光 / reduced-motion |
| `static/lib/pack-opener/` | dist + `pixi.min.mjs` + `LICENSE` + `SOUNDS-CREDITS.md`（音效已烘进 chunk，无需另发 mp3） |
| `static/lib/pokemon-cards-css/` | 4 个 CSS（`.gacha-reveal` 作用域 + 路径改写）+ 5 张图 + `LICENSE` |
| `static/images/gacha/pack.png` / `card-back.png` | 生图产物（各 ~1.5 MB，已裁到内容 bbox + 圆角 alpha） |
| `static/icons/ui.svg` | `icon-volume-on` / `icon-volume-off`（实心填充，已重跑生成器） |

接线：`templates/layout.html`（import map + pokemon CSS）、`templates/index.html`、`static/js/app.js`、`static/js/components/header.js` + `header.html`（桌面与移动端入口）、`static/css/style.css`、根 `LICENSE` 登记。

### 实测中发现的坑（方案里没预见到，实施时踩到）

1. **pokemon 的 `cards.css` 变量块不能删。** 计划里写的是「base.css 不取，cards.css 取变量」，但 pokemon 的稀有度层直接引用 `var(--glitter)` / `var(--foil)` / `var(--glittersize)` / `var(--imgsize)`；把变量块删掉会让引用回落到 `.holo-card` 的 `--glitter: none`，整个 `background-image` 列表塌成 `none` —— **特效完全消失**（`shineBgLen` 从 356 掉到 218 才看出来）。
   最终做法：变量块**整体保留**，但选择器从 `.gacha-reveal .card`（(2,0)）收窄成 `.gacha-reveal .card[data-rarity]`（(2,1)）—— 只有真正挂了 pokemon 稀有度的 SR/SSR/UR 才用 pokemon 自己的贴图，N/R 继续走 cards-css 按 `textureSeed` 生成的 `--hc-*` 纹理。

2. **import map 必须显式加，且要排在 module script 之前。** 漏了会直接 `Failed to resolve module specifier "pixi.js"`，单抽静默降级为直接揭晓。

3. **`x-show` 只切 `display`，元素始终在 DOM。** 验证脚本里用 `querySelector(...) !== null` 判断阶段会假阳性；必须判 `display !== 'none'` **且** `getBoundingClientRect()` 有尺寸。

4. **`.gacha-reveal` 默认是绝对定位的填充层。** 十连网格靠它铺满卡位，但单抽结果卡是「由内容决定高度」的容器，必须给 `.gacha-reveal--single` 单独覆盖成 `position: relative` + `aspect-ratio`；而且这条**必须排在基础规则之后**，否则被覆盖（实测卡面塌成 170×74）。

5. **非交互卡要给静态光照。** `--card-opacity` 默认 0，不挂 HoloCard 实例时 shine/glare 全透明；`gachaDraw.js` 里注入了固定的 `--pointer-*` / `--background-*` / `--card-opacity: 1`。十连因为同时有 10 张，额外把 `--hc-shine-opacity` / `--hc-glare-opacity` 调弱，让卡面本身看得清。

   > ⚠️ **这一条在第二轮被推翻了。** 静态光照是「没挂上实例」的遮羞布：它让卡面看着有质感，但**不跟随鼠标**，而且 `holo-cards.css` 的 `:not(.holo-card--interactive):hover` 兜底会把卡固定成一个姿态（正是用户反馈的「只能往一边移动」）。第二轮找到真因（见下文第 8 条 `this.$el`）后，揭晓卡**一律挂真实 HoloCard 实例**（单抽 + 十连），静态光照注入已全部移除。

6. **变体切换要 destroy + 重建。** `setOptions({variant})` 不支持换机制（README 明确），已加 `$watch('gachaVariant')` → `restartSingleCeremony()`，并用 `_stageToken` 让 in-flight 的旧 `createPackOpener` 回调失效。实测切换后 canvas 数始终为 1（不叠加）。

7. **Jinja 在非 debug 模式下缓存模板。** 改完 `.html` 不重启 `app.py` 看不到变化（曾导致一轮「代码对了但断言失败」）。

### 验证产物

`tmp/重置/` 下的可复跑脚本（复用 `ST-Manager-Pet/tools/cdp.mjs`，无 playwright/puppeteer）：

| 脚本 | 覆盖 | 结果 |
|---|---|---|
| `verify-gacha.mjs` | （第一轮，已被 `verify-gacha2.mjs` 取代）起手 → 十连发牌 → 卡背一致性 → 悬浮显影 → 拖拽批量翻 → 全部翻开 → 单抽三阶段 → canvas 回收 | PASS |
| `verify-gacha-edge.mjs` | 三变体起场景 + 仪式中换变体不叠加 + 空池 toast + 键盘 Space/Enter + 音量 localStorage + reduced-motion | PASS（17/17） |
| `verify-gacha-pool.mjs` | 小池（1 张）十连：发满 10 张 + 「可能出现重复」提示 + 重复角标 | PASS |
| `verify-gacha-effects.mjs` | `card_effects_enabled=false` 降级（单抽 + 十连）+ 恢复 | PASS（6/6） |
| `probe-*.mjs` | 定向探针（阶段切换 / 结果卡布局 / foil 透明度 / 特效 getter） | — |

关键实测值：
- 卡背一致性：10 张的 `border-color` + `box-shadow` 计算值 **unique = 1**（不悬浮时完全一致），悬浮才按 `--rarity-color` 显影。
- pokemon 作用域生效：`rare secret` → `background-blend-mode: soft-light, hard-light, overlay, soft-light`、`filter: brightness(0.386) contrast(2) saturate(0.75)`（若作用域失效会与 cards-css 逐属性交错成杂合值）。
- 拖拽批量翻牌：0 → 10 张。
- WebGL 生命周期：关闭弹窗后 canvas = 0。

### 测试

`python -m pytest tests/` → **3437 passed, 9 failed**。9 个失败全部在 `tests/test_worldbook_content_update.py` + `tests/test_worldbook_update_frontend.py`，是**既存失败**（`UnicodeDecodeError: 'gbk' codec can't decode byte 0xa1`，与本改动无关，已按要求不去修）。

---

## 实施结果 · 第二轮（按用户反馈返工）

首轮交付后用户提了 7 条反馈，逐条落地如下。

### 1. 「替换」而非「新增」

- `templates/components/header.html`：桌面端**移除**新增的 `header-tool-btn--gacha`（package 图标）按钮，改为让原有的 `.header-tool-btn--random` 在角色卡模块直接调 `openGachaDraw()`，**沿用原来的骰子图标**（`dice_icon('ui-dice-icon--header')`）；世界书/聊天模块仍走 `randomByMode()`。移动端同理，去掉新增的「抽卡」项，把「随机」项改成角色卡模块下开抽卡。
- `static/js/components/header.js`：`randomCard()` 保留为转发到 `openGachaDraw()`（外部插件/快捷键仍可能调用），移除随之失效的 `getRandomCard` 导入。
- 弹窗左上角图标从 `package` 换成 `dice_icon`，并去掉 `.gacha-heading-icon` 的边框与底色（骰子是彩色实心图形，套框不好看）。
- `POST /api/random_card` **保留**（`tests/test_gacha_draw.py` 有回归用例，插件也可能在用），只是 UI 入口不再指向它。

### 2. 起手两个大按钮直接开抽

- `templates/modals/gacha_draw.html`：`.gacha-choice` 的 `@click` 从 `chooseMode(...)` 改成 `startDraw('single' | 'multi')` —— 点哪个就直接抽哪个。
- 删掉页脚重复的「关闭」按钮（右上角已有）。页脚改为：状态文本 + `重新选择`（回起手）+ `再抽一次 / 再来一发`（同模式重抽）。
- `gachaDraw.js` 新增 `backToChooser()`；`startDraw(mode)` 支持带模式参数。

### 3. 揭晓结果是「完整角色卡」

- 新增 `templates/components/gacha_card.html`（Jinja macro `gacha_card(card, compact)`）。**刻意不复用** `templates/components/grid_cards.html`：那份模板被多个字符串契约测试精确断言，抽卡需求不该牵动它。这里改用**同一套 CSS 类**（`.st-card` / `.card-effect-shell` / `.card-image-*` / `.card-meta-*`）复刻同样的视觉：顶栏 Token chip + 稀有度徽标 + 版本 chip、图片、标签行（最多 3 个 + 「+N 个标签」）、角色名。
- 尺寸：单抽 `15rem × 23rem`，十连网格 `17.5rem` 高 + `--compact` 修饰符收窄顶栏/标签留白。`.gacha-full-card` 把网格的 `--card-height: 24rem` 换成 `100%`，圆角来自 `.st-card`（12px）。
- 隐藏 `.card-toolbar-layout-spacer`：网格卡在图片下方留了一条工具条（本地备注/类脑搜索/发送 ST），抽卡卡面没有这些动作，留着就是一条空白带。

### 4. 中间流程只出图

- 单抽仪式阶段保持 pack-opener 舞台（只有包与卡的图，不铺完整卡），揭晓后才切到完整卡。十连中间态是卡背。**未搁置**，已按预期实现。

### 5. 揭晓卡可点进详情

- 单抽：整张卡包在 `.gacha-result-hit` 按钮里，`@click="openDetail(singleCard)"`；十连：`.gacha-card` 加 `role="button"` + `tabindex="0"`，`@click` / `Enter` / `Space` → `onCardClick(index)`（未翻开先翻，已翻开进详情）。`openDetail()` 派发 `open-detail` + `highlight-card`，与网格卡走同一条通路。
- **详情页打开时抽卡弹窗保持在下层**（用户反馈：十连抽十张，点一张就被关掉，点不了第二张）。三个配套改动：
  1. `openDetail()` **不再** `showGachaModal = false`。
  2. `.gacha-overlay` 的 z-index 压到 `var(--z-modal)`(1000)，低于详情页的 `--z-modal-std`(1100)。两者都是 `.modal-overlay`（默认同为 1100），而 `detail_card.html` 在 DOM 里排在 `gacha_draw.html` **前面** —— 同 z-index 时后出现者胜，不压层级的话详情页会被抽卡弹窗盖住。
  3. `requestClose()` 加守卫：详情页开着时直接返回。否则点详情页里任意位置都算「点在 `.gacha-shell` 之外」，`@click.away` 会把抽卡弹窗一起关掉；Esc 更糟 —— 两个组件都监听 `keydown.escape.window`，会一次关两层。守卫用 `isDetailModalOpen()` 查 DOM（详情页是独立组件，不去读它的内部 `showDetail`，避免耦合）。

  最终行为：详情盖在抽卡结果上 → Esc / 点遮罩只关详情 → 回到抽卡结果继续点下一张；详情全关后 Esc 才关抽卡弹窗。

### 6. 开发用测试卡池

`tmp/重置/_make_test_pool.py` 生成 **12 张**卡到 `data/library/characters/测试卡池/`（`data/` 是 gitignore，属本地开发夹具，整目录可删）：

- 5 档稀有度各 2 张以上（N/R/SR/SSR 靠 Token 分档，UR 靠 `fav`），另有边界卡：12 个标签（溢出）、超长名字、0 标签 0 版本。
- 子分类 `学院/都市/幻想/特别` + 不同标签组合，便于验证分类筛选与标签渲染。
- Token 数用 `core.utils.text.calculate_token_count` **真实计算**后补齐（纯中文 filler，1 字 = 1 token），脚本末尾打印 target/actual/tier 便于核对。
- 卡面图片：9 张由图像模型生成的角色立绘（`dsh-image-gen/`）+ 仓库已有的 2 张 beautify 预览图。生成器脚本里点名引用，换图只改一行。

### 7. 卡背悬浮按稀有度区分

首轮虽然写了规则，但用户实测「看不出区别」。两个原因，都已修：

1. **N 档的 `--rarity-color` 原本等于 `--border-default`** —— 那就是卡背的默认边框色，浅色主题下悬浮前后**完全同色**，等于没反馈。改成 `var(--content-muted)`（两个主题下都与默认边框不同）。
2. 反馈太弱：现在悬浮除边框 + 辉光外，**还在卡背正中显示稀有度文字**（`UR` / `SSR` / `SR` / `R` / `N`）。不悬浮时该层 `opacity: 0`，十张卡背仍然一模一样（实测 `border-color + box-shadow` 计算值 unique = 1），悬念不丢。

### 第二轮踩到的两个硬坑

8. **`this.$el` 在 Alpine v3 里不是组件根元素。** `$el` 是按「当前表达式求值上下文」注入的：由按钮 click 触发的调用链（`startDraw → finishSingleCeremony → attachHoloCard`）里，`this.$el` 解析成的是**那个按钮**（实测 `elTag=BUTTON` / `elClass=gacha-choice` / `elChildren=3`），于是 `this.$el.querySelector('.gacha-result-card ...')` 永远落空。

   后果：揭晓卡一直没挂 HoloCard 实例 → 退化到 `holo-cards.css` 里 `:not(.holo-card--interactive):hover` 的**固定姿态**（`--rotate-y: -19deg` + `--translate-y: -10px`），看起来正是用户说的「只能往一边移动」。**这就是反馈 3 里鼠标跟随异常的根因**，不是 tilt 参数问题。
   修法：`init()` 里把组件根元素抓进 `this._rootEl`，之后所有 DOM 查询都走它。（`$refs` 不受影响 —— 它按组件作用域注入，所以 `this.$refs.stage` 一直是好的，这也是为什么单抽舞台能正常起来、只有卡面挂载失败。）

9. **揭晓区块由 `x-show` 切到可见后，`$nextTick` 里仍可能取不到节点。** 已改成「取不到就重试几帧」（`setTimeout` 16ms × 最多 60 次）。注意不能用 `requestAnimationFrame`：无头 Chrome 下 rAF 不一定触发。

10. **`overflow: hidden` 会裁掉倾斜的卡面。** 首轮 `.gacha-reveal-card.holo-card` 写了 `overflow: hidden`（为了圆角），倾斜时图片被切边 —— 正是用户说的「随着卡牌的移动，图片超出方框的部分还会被截断」。现在复用网格的 `.st-card.card-effect-host`（`overflow: visible`），圆角交给 `border-radius`。

### 第二轮验证产物

| 脚本 | 覆盖 | 结果 |
|---|---|---|
| `verify-gacha2.mjs` | 骰子入口/无新增按钮 · 大按钮直接开抽 · 无重复关闭 · 卡背一致性与**真实鼠标悬浮**显影（含稀有度文字、各档配色互不相同）· 拖拽批量翻 · 完整卡结构/圆角/Token/标签审计 · HoloCard 实例与 `overflow: visible` · 倾斜双向 · 单抽/十连点卡进详情（弹窗保留）· canvas 回收 | PASS（26/26） |
| `verify-gacha-detail.mjs` | 详情盖在抽卡结果上：弹窗保留 + 层级正确 + 展示的是被点那张 · Esc 只关详情 · 关掉后能点第二张 · 点遮罩不连带关弹窗 · 详情全关后 Esc 才关弹窗 | PASS（10/10） |
| `verify-gacha-fixes.mjs` | 再抽一次的 canvas 尺寸/backing store 一致 · 背面**真实指针**点一次只翻牌不进详情 · 已翻开再点才进详情 · 拖拽不误开详情 · 逐档揭晓特效参数（颜色/光环/闪光/光条/顶起） | PASS（20/20） |
| `verify-gacha-edge.mjs` | 三变体 + 换变体不叠加 + 空池 toast + 键盘 + 音量 + reduced-motion | PASS |
| `verify-gacha-pool.mjs` | 小池十连重复与提示 | PASS |
| `verify-gacha-effects.mjs` | `card_effects_enabled=false` 降级（单抽 + 十连）与恢复后重新挂实例 | PASS |
| `probe-holo.mjs` / `probe-overlay.mjs` / `probe-detail.mjs` / `probe-redraw*.mjs` | 定向探针（HoloCard 挂载、抽卡卡 vs 网格卡样式差异、详情弹窗可见性、再抽一次的画面尺寸） | — |

### 第三轮（又三条反馈）

11. **「再抽一次」后卡包被左右压窄。** 根因是尺寸竞态，不是 CSS 比例问题：
    pack-opener 用 Pixi 的 `resizeTo: host` 定尺寸，宿主若是 `display: none`（刚由 x-show 切过来、布局还没跑完）就会量到 0，Pixi 回落到默认 800×600。
    第一次抽卡时 pack-opener 模块要现下载，等待期间布局已稳定；**第二次模块命中缓存，`await import` 几乎立刻返回，反而抢在布局前建场景** —— 这就是「第一次正常、再抽一次才压窄」。
    两处修：① 建场景前 `waitForStageSize()` 等宿主宽高都 > 0（rAF 轮询，最多 60 帧）；② 删掉 `.gacha-canvas-host canvas { width/height: 100% !important }` —— 它会覆盖 Pixi 自己写的行内尺寸，backing store 与显示尺寸一旦不一致就会被非等比拉伸。尺寸完全交给 Pixi。

12. **十连点一次既翻牌又跳详情。** `pointerdown` 已经把卡翻开了（`onGridPointerDown → flipAt`），紧接着 `pointerup` 触发的 `click` 看到「已经翻开」就进了详情 —— 一次点击走两条路。
    修法：`revealCard(index, viaPointer)` 在指针路径下把下标记进 `_flippedByPointer`，随后的 `onCardClick` 消费掉该记录（只确认翻开，不跳转）；带 600ms 兜底清理，防止某些情况下不补发 click 导致记录残留。键盘 Enter/Space 不走指针路径，行为不变。

13. **不同稀有度的翻牌特效看不出区别。** 之前只有音效有分档，视觉上完全没有。现在加了逐档揭晓特效（`.gacha-reveal-fx` 三层：中心闪光 / 外扩光环 / 放射光条），靠 `--reveal-color`、`--reveal-flash-peak`、`--reveal-ring-size` 三个变量拉开梯度：

    | 档位 | 颜色 | 闪光峰值 | 光环 | 放射光条 | 卡片顶起 |
    |---|---|---|---|---|---|
    | N | — | — | — | — | —（完全不加） |
    | R | `#3b82f6` | 0.34 | 2px | 无 | 无 |
    | SR | `#a855f7` | 0.5 | 3px | 无 | 轻微 |
    | SSR | `#fbbf24` | 0.72 | 4px | 有 | 明显 |
    | UR | `#e879f9` | 0.9 | 5px | 有 | 明显 |

    为此新增 `rarityKey()` 返回 N/R/SR/SSR/UR 短键，挂到 `data-rarity-key`：原来的 `data-rarity` 存的是 pokemon 稀有度字符串（N 与 R 都是空串），没法区分档位。卡背的 UR 彩虹描边也一并改用它。

    批量划开时每张卡各自触发一次，所以一眼能看出哪几张是高稀有度。

第二轮关键实测值：
- HoloCard 挂载：`_holoCards` size = 1，shell 带 `holo-card--interactive`；倾斜左/右 `rotate-y` = `-0.001deg` / `0.2deg`（双向）。
- 卡背：悬浮 `border-color: rgb(168,85,247)` + 紫色辉光 + 标签 `SR`（opacity 1）；未悬浮 `rgb(130,147,168)` + 默认阴影 + 标签 opacity 0。各档配色 `{N:#5b6b82, radiant rare:#a855f7, rare secret:#fbbf24, rare rainbow:#e879f9}` 互不相同。
- 完整卡：`.st-card` 结构、`border-radius: 12px`、Token `3927T`、标签数 = `min(数据标签数, 3)`、溢出显示「+9 个标签」。
- 详情通路：十连与单抽点卡都打开详情弹窗（`.modal-overlay` 可见数 = 1），且抽卡弹窗自动收起。

> 排查提示：`.modal-overlay` 是 `position: fixed`，`offsetParent` **恒为 null**；`x-show` 也是把 `display: none` 打在 overlay 上，子元素 `.gacha-shell` 的 computed `display` 不变。判断可见性必须看 overlay 自己（`getComputedStyle(el).display` + `getBoundingClientRect().width`）。这两点各浪费过一轮排查。

---

## 0. 勘误与结论先行

### 0.1 勘误：GPL-3.0 ↔ AGPL-3.0 可以混用（上一版判断错误）

上一版把 `pokemon-cards-css`（GPL-3.0）标为「不可 vendoring」，**这是错的**。FSF 官方 FAQ 明确写着（[gnu.org/licenses/gpl-faq.html#AGPLGPL](https://www.gnu.org/licenses/gpl-faq.html#AGPLGPL)）：

> "Each of these licenses explicitly permits linking with code under the other license. **You can always link GPLv3-covered modules with AGPLv3-covered modules, and vice versa.** That is true regardless of whether some of the modules are libraries."

本项目是 AGPL-3.0，因此**可以合法 vendoring `pokemon-cards-css`**。唯一义务：保留其 GPL-3.0 许可与版权声明（仿现有 `static/lib/cards-css/LICENSE` 的写法），并在根 `LICENSE` 第 10 行那类 notice 段落里登记。

> 附带发现：`cards-css`（MIT）与 `pokemon-cards-css`（GPL-3.0）**变量名与架构高度同源**（`--sunpillar-*`、`--glitter`、`--grain`、`--space`、`--angle`、`--imgsize`、`--foil`、`--mask`、`--pointer-*`、`--card-opacity`、`--rotate-x/y`、`--background-x/y`、`--card-scale`、`--translate-x/y` 全部一致）。`cards-css` 很可能是后者的再实现/衍生，其 MIT 声明在严格意义上存疑。**对本项目无实际影响**（AGPL-3.0 与两者都兼容），但这也是「两者能无缝共存」的根本原因 —— 见 §3.2。

### 0.2 关键技术验证：`pack-opener` 免打包可用 ✅

上一版判断「pack-opener 必须 bundler、不可用」，**这个结论也被推翻了**。实测证明：它的 dist 只 `import ... from "pixi.js"` 这一个裸标识符，而 `pixi.js` 官方发布了自包含的 `pixi.min.mjs`（819 KB，无进一步裸导入）。用 **import map** 即可在无 bundler 的原生 ESM 环境里跑起来。

已在无头 Chrome 里真机验证（见 §2 的实测记录）：`slice` 与 `burst` 两个变体都正常渲染，`destroy()` 能干净回收 WebGL canvas，控制台零错误。**这是单抽方案成立的前提。**

### 0.3 结论

| 结论 | 说明 |
|---|---|
| **可行性：高，且已验证** | 单抽用 `pack-opener`（WebGL 真机跑通），十连用纯 CSS 发牌 + 翻牌 |
| **GPL-3.0 ↔ AGPL-3.0 可混用** | FSF 官方 FAQ 明确许可（见 §0.1），`pokemon-cards-css` **可以合法 vendoring** |
| **两个 CSS 库可共存，但需一层作用域前缀** | 共享同一套 CSS 变量契约（cards-css 已外发 pokemon 需要的全部变量），但基础层同源 → 稀有度规则与效果规则特异性都是 (2,1)，实测会**逐属性交错**。加 `.gacha-reveal` 前缀即可稳定，见 §3.2 |
| **单抽只需生成 1 张图**（卡包） | 卡面直接用真实卡缩略图（`card.thumb_url`） |
| **十连只需生成 1 张图**（卡背） | 同底图 + **悬浮才显影**，见 §3.4 |
| **单抽三种动画全可用** | `slice` / `burst` / `carousel` 三个 variant **均已真机验证**，见 §2 |
| **下拉框零开发** | 复用现有 `styled_select` 宏（已主题化 + 键盘可达），见 §3.6 |
| **稀有度映射完美命中现有配置** | `TOKEN_THRESHOLDS` 正好 4 档 + 收藏 = 5 档，与你的设想完全一致，**零新增配置** |

---

## 1. 现状勘察（改动落点）

### 1.1 后端

| 项 | 位置 |
|---|---|
| 随机接口 | `core/api/v1/cards.py:3360` `api_random_card()` |
| 抽取逻辑 | `cards.py:3428` `picked_card = random.choice(candidates)` |
| 筛选参数 | `cards.py:3364-3381`（`category` / `tags` / `search` / `search_type` / `search_scope` / `recursive` …） |
| 候选来源 | `ctx.cache.cards`（`core/data/cache.py:55`，已聚合 bundle） |
| 卡片字段 | `cache.py:565-581`：`id` `char_name` `tags` `category` `creator` `char_version` `last_modified` `token_count` `is_favorite` `thumb_url` … |
| 缩略图 | `card['thumb_url']` = `/api/thumbnail/<quote(rel_path)>?t=<mtime>`（`cache.py:803`） |

### 1.2 前端

| 项 | 位置 |
|---|---|
| API 封装 | `static/js/api/card.js:248` `getRandomCard(params)` |
| 触发 | `static/js/components/header.js:887` `randomCard()`；`:928` `randomByMode()` |
| 抽中行为 | 派发 `open-detail` + `highlight-card` |
| 按钮 | `templates/components/header.html:728`（骰子 `dice_icon`）；`:1049` 移动端菜单 |
| 特效接入 | `cardGrid.js:25` import；`:727` `attachHoloCard(shell, {...})` |
| 稀有度→特效 | `cardGrid.js:27-30` `CARD_EFFECT_NAMES = { regular: "cosmos", favorite: "glitter" }` |
| 开关 | `core/config.py:81` `card_effects_enabled`（另见 `settingsModal.js:61`、`state.js:756`、`settings.html:121`） |
| 翻面状态 | `cardGrid.js:87` `flippedCardIds`；`:1237` `toggleCardFace()` |
| 弹窗范式 | `.modal-overlay`（`components.css:690`）+ Alpine `x-data`/`x-show`/`x-cloak`，`app.js` 里 `Alpine.data()` 注册 |

### 1.3 ⚠️ 契约测试约束

本仓库大量使用**字符串契约测试**。新增功能应**新增文件**，尽量少改既有结构：

- `tests/test_source_update_monitor_frontend_contracts.py:275-291` 精确断言 `regular: "cosmos"`、`favorite: "glitter"`、`class="card-effect-shell holo-card"` 等字符串。
- `tests/test_card_grid_update_contracts.py:155-199` 断言 `card-effect-controls-layer` 内部**元素顺序**。
- `tests/test_settings_frontend_contracts.py:237-245` 断言 `card_effects_enabled: true` 等。

---

## 2. 实测验证记录（`pack-opener` 免打包）

### 2.1 验证方法

复用 `ST-Manager-Pet/tools/cdp.mjs` 的极简 CDP 客户端（Node 内置 `fetch`/`WebSocket` + 系统 Chrome，**无需 playwright/puppeteer**）。

**验证目录**：`D:\Workspace\MyOwn\pack-opener-testlib\`

```
index.html             import map + 原生 ESM 测试页（slice）
burst.html             burst 变体 + destroy 清理测试页
verify-importmap.mjs   CDP 断言脚本
verify-burst.mjs       CDP 断言脚本
shoot-phases.mjs       分相位截图脚本
lib/index.js           pack-opener dist 入口（240 B）
lib/chunks/*.js        dist chunk（261 KB + 804 KB）
lib/pixi.min.mjs       pixi.js 自包含 ESM（819 KB）
shots/*.png            6 张分相位截图
```

**核心机制**（`index.html`）：

```html
<script type="importmap">
{ "imports": { "pixi.js": "/lib/pixi.min.mjs" } }
</script>
<script type="module">
  const { createPackOpener } = await import('/lib/index.js');
  const opener = await createPackOpener(stage, {
    variant: 'slice', preset: 'classic',
    assets: { pack: { url: packDataUrl }, card: { url: cardDataUrl } },
    theme: { glow: '#a855f7' },
    sound: { enabled: false },
  }, { onEvent: e => log(e.type) });
  opener.autoSlice();
</script>
```

### 2.2 验证结果

```
=== 页面日志 ===
OK import. exports = MESSAGES, VARIANTS, createPackOpener, resolveOptions, variantOf
VARIANTS = ["slice","burst","carousel"]
event: ready → event: timeline → event: interactionStart → event: phase
OK createPackOpener. handle keys = setOptions, autoSlice, shuffle, reset, setEnabled, destroy
=== canvas 检查 ===
{"hasCanvas":true,"w":420,"h":620,"hasGL":true}
=== 控制台错误: 无 ===
RESULT: PASS — 免打包可行
```

`burst` 变体 + 清理：

```
OK createPackOpener(burst)
canvas before destroy = 1
event: phase autoCharge → beat → swarm → assemble → snap
destroy() OK. canvas after = 0
DESTROY_CLEANED
RESULT: PASS — burst 可用且 destroy 清理干净
```

`carousel` 变体：

```
OK createPackOpener(carousel)
event: phase shuffle → step ×12 → committed → drop → rise → float
RESULT: PASS — carousel 可用（转盘选包 → 揭晓）
```

**分相位截图**确认三个变体都真实渲染：

| 变体 | 截图 | 观察到的内容 |
|---|---|---|
| `slice` | `shots/phase-0000ms.png` / `phase-2800ms.png` | 切割火花 → 光爆 → 卡片升起立于底座 |
| `burst` | — | 蓄力 → 爆开 → 碎片重组 |
| `carousel` | `shots/carousel-00.png` / `carousel-04.png` | **转盘环（3 个包呈透视排布 + 地面镜像反射）** → 选中的包升起至中央舞台悬浮 |

### 2.3 由此确认的工程事实

| 事实 | 影响 |
|---|---|
| dist 只依赖裸标识符 `pixi.js` | import map 可解，**无需 bundler** |
| `pixi.min.mjs` 自包含（819 KB / 约 184 KB gzip） | 一次性成本，可接受 |
| `assets.pack.url` / `assets.card.url` 接受 data URL | **无需后端路由**，前端生成或 fetch 后转 data URL 均可 |
| `theme.background: 'transparent'` 可用 | 可叠加在管理器自己的模态框上，**风格可统一** |
| `sound.enabled` 默认 false，内置 CC0 音效 | 开启即得「抽卡感」，无需自备音频 |
| `destroy()` 干净回收 canvas | 关弹窗/切换变体即释放 WebGL，**无泄漏** |
| **三个 variant 全部可用** | `slice` / `burst` / `carousel` 都可选，见 §3.5 |
| `carousel` 有 `facts` / `badge` 机制 | 揭晓前可「念」稀有度与 Token 数，**最有手游味** |
| `setOptions({ variant })` **不支持换 variant** | 切换方式 = `destroy()` + 重建（实测安全） |
| 200+ 可调项（`theme`/`layout`/`motion`/`performance`） | 足以调到与管理器视觉一致 |

**构建命令**（若要自己出 dist）：

```powershell
cd D:\Workspace\MyOwn\pack-opener
npm install --no-save --ignore-scripts pixi.js@8.20.0 vite@7.1.3 typescript@5.9.3 esbuild@0.28.2 react@19.2.8 react-dom@19.2.8
node scripts/build.mjs        # → dist/（esm + cjs + types）
```

---

## 3. 特效库分析与选型

### 3.1 三个主力库定位

| 库 | 许可 | 在本方案中的角色 |
|---|---|---|
| `cards-css`（已 vendored） | MIT | **卡面 foil 引擎**（14 种效果 + 交互运行时） |
| `pokemon-cards-css` | **GPL-3.0**（可混用） | **稀有度专用卡面效果**（更「宝可梦正卡」的质感） |
| `pack-opener` | MIT（代码）+ CC0（音效） | **单抽开包动画**（WebGL） |

其余 8 个（`lucky-boy` / `holo3D-card` / `canvas-confetti` / `atropos` / `party-js` / `fireworks-js` / `html5-slot-machine` / `holo-card`）按需取小件，见 §6。

### 3.2 ★ 关键发现：两个 CSS 库共享同一套变量契约

`cards-css` 的 `holo-card.js` 在 `RENDER_VARS`（`:203-221`）里**外发了 `pokemon-cards-css` 需要的全部变量**：

```
--pointer-x  --pointer-y  --pointer-from-center  --pointer-from-top  --pointer-from-left
--pointer-dx --pointer-dy --card-opacity
--rotate-x   --rotate-y   --tilt-x  --tilt-y
--background-x --background-y --card-scale --translate-x --translate-y
```

再加上 `holo-cards.css:8-54` 里已定义的 `--sunpillar-1..6` / `--sunpillar-clr-1..6` / `--glitter` / `--grain` / `--space` / `--angle` / `--imgsize` / `--foil` / `--mask*` —— **`pokemon-cards-css` 的所有输入变量都已被现成运行时驱动**。

**结论：不需要第二套交互引擎。** 只需：

1. **类名桥接**：给 shine/glare 元素**同时挂两个类**，让 pokemon 的选择器能命中：
   ```html
   <div class="holo-card__shine card__shine"></div>
   <div class="holo-card__glare card__glare"></div>
   ```
2. **根节点加 `data-rarity`**：`<div class="holo-card card" data-rarity="rare holo cosmos">`。
3. **图片路径改写**：pokemon CSS 里全是绝对路径 `url("/img/...")`，需改为 `/static/lib/pokemon-cards-css/img/...`（机械替换）。

#### ⚠️ 特异性会「逐属性交错」，必须显式处理（实测，勿凭直觉）

我最初以为 pokemon 的规则「特异性更高会稳定覆盖」，**实测证明这个直觉不可靠**。两者的基础层完全同源（cards-css 明显是从 pokemon 派生的，只多了 `--hc-*` 乘数钩子）：

| 规则 | 选择器 | (类, 属性) |
|---|---|---|
| pokemon 基础 | `.card__shine` | (1, 0) |
| cards-css 基础 | `.holo-card__shine` | (1, 0) |
| **pokemon 稀有度** | `.card[data-rarity="rare secret"] .card__shine` | **(2, 1)** |
| **cards-css 效果** | `.holo-card[data-effect=rainbow] .holo-card__shine` | **(2, 1)** |
| pokemon（带 `:not`） | `.card:not(.masked)[data-rarity="rare secret"] .card__shine` | **(3, 1)** |

**稀有度规则与效果规则特异性完全相同 (2,1) → 胜负由加载顺序决定，而非选择器强度。**

**实测结果**（`pack-opener-testlib/specificity.html` + `verify-specificity.mjs`，无头 Chrome，pokemon 故意排在 cards-css 之后）：

| 属性 | A 组（原始选择器） | B 组（`.scoped` 前缀） |
|---|---|---|
| `background-image`（含 glitter+conic） | ✅ 来自 pokemon | ✅ 来自 pokemon |
| `background-blend-mode` | `soft-light, hard-light, overlay, soft-light`（**4 个值**） | `soft-light, hard-light, overlay, soft-light`（**4 个值**） |
| `filter` | `brightness(0.44) contrast(2) saturate(0.75)` | `brightness(0.56) contrast(1) saturate(2.7)` |
| `mix-blend-mode` | `color-dodge` | `color-dodge` |

**关键发现：不是「一层干净地赢」，而是逐属性交错。** `background-blend-mode` 出现 **4 个值** —— pokemon 给了 3 个，cards-css 基础层又追加了 1 个。`filter` 在两组的取值也各不相同。这意味着**混合结果不可预测，且不同属性来自不同库**，视觉上会得到两边都没设计过的「杂合体」。

**因此唯一稳健的做法：作用域前缀 + 在作用域规则里把 `filter` / `background-blend-mode` / `mix-blend-mode` 一并显式重声明。**

```html
<div class="gacha-reveal">                     <!-- 抽卡揭晓容器 -->
  <div class="holo-card card" data-rarity="rare secret" data-effect="rainbow">…</div>
</div>
```

```css
/* 前缀统一加作用域 → (3,1) 稳定胜出，并且把所有相关属性一次写全 */
.gacha-reveal .card[data-rarity="rare secret"] .card__shine {
  background-image: …;            /* 来自 pokemon */
  background-size: …;
  background-position: …;
  background-blend-mode: soft-light, hard-light, overlay;   /* 显式写全，不依赖继承 */
  mix-blend-mode: color-dodge;
  filter: brightness(calc(0.4 + (var(--pointer-from-center) * 0.2))) contrast(1) saturate(2.7);
}
```

改写方式：把 pokemon 的 `cards/*.css` 里 `.card[data-rarity=` 批量替换为 `.gacha-reveal .card[data-rarity=`，并**逐条补齐** `filter`/`background-blend-mode`/`mix-blend-mode`（原始文件里已声明这些属性的规则，替换前缀即可；未声明的才需要补）。`base.css` 里的裸 `.card__shine` 基础规则**保持不动**，交给 cards-css 的基础层（它带 `--hc-*` 可调乘数）。

**这样分工**：
- **基础层**（`display: grid` / `translateZ` / `border-radius` / 几何）→ cards-css 提供，可调；
- **稀有度层**（`background-image` / `filter` / 混合模式）→ pokemon 提供，作用域内以 (3,1) 稳定胜出。

> **备选（省事但脆弱）**：仅依赖加载顺序（pokemon 排在 `holo-cards.css` 之后）。实测 A 组「能用」但不干净（blend 多出第 4 个值、filter 取值异常）。**不建议**，除非接受视觉杂合。

#### 最小 vendoring 集（若只做 SR/SSR/UR 的差异化）

若不需要全 15 种稀有度，只需 5 个文件 + 6 张图：

| 文件 | 大小 |
|---|---|
| `cards.css` | 1,023 B |
| `cards/base.css` | 8,927 B |
| `cards/radiant-holo.css`（SR） | 5,527 B |
| `cards/secret-rare.css`（SSR 金） | 3,242 B |
| `cards/rainbow-holo.css`（UR 彩虹） | 3,320 B |
| **CSS 小计** | **约 22 KB** |

| 图片 | 大小 |
|---|---|
| `grain.webp`（base 变量） | 59,244 B |
| `glitter.png`（base 变量） | 113,310 B |
| `trainerbg.png`（radiant） | 10,268 B |
| `geometric.png`（secret-rare） | 24,166 B |
| `illusion-mask.png`（rainbow） | 95,933 B |
| `illusion.png`（备用） | 50,294 B |
| **图片小计** | **约 353 KB** |

**总计约 375 KB**（全 25 个文件 + 9 张图则为 636 KB）。若 N/R 也走 pokemon 的 `cosmos-holo`，再加 3 张 cosmos 图（273 KB）—— 但 N/R 用 cards-css 的 `metal`/`cosmos` 已足够，**建议不引**。

**vendoring 成本实测**：

| 项 | 量 |
|---|---|
| CSS | 25 个文件 / **83,717 B** |
| 稀有度 CSS 引用的图片 | 9 个 / **552,233 B**（cosmos 三层 273 KB 最大，vmaxbg 76 KB，其余 < 132 KB） |
| 合计 | **约 636 KB**（gzip 后远小于此，PNG 本身已压缩） |

### 3.3 建议的稀有度 → 特效映射（5 档）

稀有度**完全由现有字段派生，零新增配置**：

| 稀有度 | 判定条件 | `cards-css` foil | `pokemon-cards-css` 叠加 | 飞入特效 | 音效 |
|---|---|---|---|---|---|
| **N** | `token_count ≤ 5000`（`ok`） | `metal` | `basic`（仅边框） | 无 | `tick` |
| **R** | `> 5000`（`warn`） | `cosmos` | `cosmos-holo` | 无 | `tick` |
| **SR** | `> 20000`（`danger`） | `aurora` | `radiant-holo` | 淡色光晕拖尾 | `whoosh` |
| **SSR** | `> 100000`（`extreme`） | `gold` + `glitter` | `secret-rare`（金） | **金色粒子 + 揭晓前停顿** | `impact` + `boom` |
| **UR** | `is_favorite === true` | `rainbow` 或 `prism` | `rainbow-holo` / `shiny-v` | **全屏彩光 + 撒花 + 屏震** | 全套 + 撒花 |

**为什么这样分**：

- 判定条件**直接复用 `static/js/utils/format.js:74-92`** 的 `TOKEN_THRESHOLDS`（`CARD_WARN: 5000` / `CARD_DANGER: 20000` / `EXTREME: 100000`）与 `getTokenLevel()`（返回 `ok`/`warn`/`danger`/`extreme`）——**正好 4 档 + 收藏 = 5 档，与你说的完全吻合**。
- `SSR`/`UR` 用 `gold`/`secret-rare` 与 `rainbow`/`shiny-v`，视觉上天然形成「金 → 彩虹」的顶阶阶梯。
- 强度递进单调：`metal`（哑光）→ `cosmos`（宇宙纹理）→ `aurora`（极光）→ `gold`（金箔+闪粉）→ `rainbow`（彩虹+全息）。

### 3.4 卡背方案：同底图 + 悬浮显影（已定稿）

**决定：同底图**，且**不悬浮时看起来完全一样**，只在**鼠标悬浮/聚焦时**才显现稀有度差异。

**理由**（这是「保留惊喜」与「可辨稀有度」的最佳平衡）：

| 方案 | 剧透程度 | 生图成本 | 评价 |
|---|---|---|---|
| 5 张不同卡背 | **完全剧透**（翻开前就知道结果） | 5 张 | ❌ 抽卡乐趣折半 |
| 同底图 + 常驻光效 | 部分剧透（扫一眼就知道有没有 SSR） | 1 张 | ⚠️ 十连时「一眼扫完」，失去逐个翻开的张力 |
| **同底图 + 悬浮显影** | **不剧透**（初始全同） | **1 张** | ✅ **已采纳** |

**实现**：卡背默认统一（品牌卡背图 + 中性描边），`hover` / `:focus-visible` / `.is-peeking` 时才按稀有度上色：

```css
/* 默认：所有卡背一模一样 */
.gacha-card__back { border-color: var(--border-default); box-shadow: none; }

/* 悬浮/聚焦才显影 —— 稀有度色由 --rarity-color 注入 */
.gacha-card:hover .gacha-card__back,
.gacha-card:focus-visible .gacha-card__back,
.gacha-card.is-peeking .gacha-card__back {
  border-color: var(--rarity-color);
  box-shadow: 0 0 12px 2px color-mix(in srgb, var(--rarity-color) 45%, transparent);
}
```

**这样同时满足**：
- 初始状态十张牌**视觉完全一致** → 保留「逐个翻开」的悬念与节奏；
- 鼠标划过时**光效颜色泄露稀有度** → 想先挑好卡翻的玩家有据可依（这正是你说的「悬浮时能够有区分」）；
- **触屏**：`hover` 不存在 → 用 `.is-peeking`（长按 120ms 触发微光）或直接跳过（触屏用户本来就会拖拽批量翻）；
- **键盘**：`:focus-visible` 覆盖，无障碍不缺失；
- **SSR/UR 额外**：可给背面加**极弱的呼吸微光**（不泄露颜色，只泄露「有东西」），制造期待感。

`--rarity-color` 取值（与 §3.3 的 foil 阶梯一致）：

| 稀有度 | 色值 | 观感 |
|---|---|---|
| N | `--border-default`（灰） | 无感 |
| R | `#3b82f6`（蓝） | 微亮 |
| SR | `#a855f7`（紫） | 明显 |
| SSR | `#fbbf24`（金） | 醒目 |
| UR | 彩虹 `conic-gradient` | 一眼锁定 |

### 3.5 单抽：三种方式全部支持（已定稿）

`pack-opener` 的三个 variant **全部实测可用**（见 §2），因此三种都接，右上角下拉切换：

| variant | preset | 交互 | 手感 |
|---|---|---|---|
| `slice` | `classic` | **手指/鼠标划过封条**切开 | 有参与感，推荐默认 |
| `burst` | `charged` | **长按蓄力**至爆开 | 期待感最强，等待即卖点 |
| `carousel` | `showcase` | **拖动转盘**选包 → 点选 | 先「念」稀有度再揭晓，仪式感 |

**`carousel` 的额外能力**（实测确认）：揭晓前会先逐条显示 `assets.card.facts`（`{label, value}` 数组）和 `assets.card.badge`（`{label, color}`）——**正好可以把「Token 数 / 来源 / 稀有度」当作开包前的「情报」念出来**，这是三个变体里最有「二次元手游」味的。

```js
assets: {
  card: {
    url: card.thumb_url,
    facts: [
      { label: '稀有度', value: 'UR · 传说' },
      { label: 'Token',  value: String(card.token_count) },
      { label: '分类',   value: card.category || '根目录' },
    ],
    badge: { label: rarity, color: RARITY_COLOR[rarity] },
  },
}
```

**切换方式**：`opener.setOptions({ variant })` **不支持运行时换 variant**（README 明确：「a different `variant` … cannot be retuned」）。因此切换 = **`destroy()` 后重建**。实测 `destroy()` 能干净回收 canvas，重建安全。

> **注意**：`slice`/`burst` 变体忽略 `facts`/`badge`（那是 `carousel` 专属）。切换时统一传入即可，不会报错。

### 3.6 下拉框：复用现有 `styled_select`（不要自造）

管理器**已有**一套主题化下拉框，正是你要的效果，直接用：

- **宏**：`templates/components/styled_select.html` → `styled_select(model, ...)` / `styled_select_controlled(...)`
- **行为**：`static/js/components/styledSelect.js`（隐藏原生 `<select>` 作 state bridge + 主题化 listbox）
- **样式**：`static/css/modules/components.css:183-414`（`.icon-select*`），已含 `--compact` / `--tiny` / `--fit` / `--align-right` 变体，并已处理 `prefers-reduced-motion`

**表头右侧的紧凑用法**（照抄 `header.html:563-566` 的既有写法）：

```jinja
{% call styled_select(
    "gachaDrawMode",
    wrapper_class="icon-select--compact",
    trigger_class="icon-select-trigger--compact",
    menu_class="icon-select-menu--fit icon-select-menu--align-right",
    aria_label="单抽动画方式"
) %}
  <option value="slice">划开封条</option>
  <option value="burst">长按蓄力</option>
  <option value="carousel">转盘选包</option>
{% endcall %}
```

**要点**：
- `icon-select-menu--align-right` 让菜单右对齐，避免溢出模态框右边界（表头/右上角场景必需）。
- 该组件**已支持键盘**（↑↓ / Home / End / Enter / Space / Esc）与 `aria-haspopup`/`role="listbox"`，无障碍免做。
- **不要**在抽卡模态框里另写 `<select>` 或第三方下拉——契约测试与样式一致性都会受影响。

---

## 4. 实施方案

### 4.1 单抽：`pack-opener` 开包动画（三种方式）

```
点击「单抽」
  → 打开全屏模态框（复用 .modal-overlay 范式）
  → 右上角 styled_select 选择方式（slice / burst / carousel，默认 slice）
  → 调 POST /api/draw_cards { count: 1, ...筛选 }
  → 拿到 card（含 rarity）
  → createPackOpener(stage, {
       variant: gachaDrawMode,                 // slice | burst | carousel
       preset: PRESET_OF[gachaDrawMode],       // classic | charged | showcase
       assets: {
         pack: { url: '/static/images/gacha/pack.png' },   // 1 张生图
         card: {
           url: card.thumb_url,                            // 真实卡面，无需生图
           facts: [...],                                   // carousel 专属
           badge: { label: rarity, color: ... },           // carousel 专属
         },
       },
       theme: { glow: RARITY_COLOR[rarity], background: 'transparent' },
       sound: { enabled: true, badge: rarity },            // 内置 CC0 音效
     })
  → 交互交给变体本身：
       slice    → 用户划过封条（autoSlice() 作为「跳过」兜底）
       burst    → 用户长按蓄力
       carousel → 用户拖动转盘选包
  → onRevealComplete: 交叉淡入到 cards-css + pokemon 渲染的真实卡面
  → 底部按钮：「查看详情」/「再抽一次」/「关闭」
```

**切换方式**：`setOptions({ variant })` **不支持运行时换 variant** → 切换时 **`destroy()` 后重建**（实测安全）。

**要点**：

- **卡包图只需 1 张**（生图产出），卡面用真实缩略图。
- `theme.glow` 设成稀有度色 → pack-opener 自己的光晕就是稀有度信号。
- pack-opener 自身**不渲染 foil**，所以揭晓后交叉淡入到真实卡面，让 SSR 金箔/UR 彩虹真正显现。
- ⚠️ **需确认缩略图分辨率**：pack-opener 按 ~620×900 渲染，`/api/thumbnail/` 若尺寸偏小会糊。必要时加尺寸参数或直接用原图路由。
- ⚠️ **WebGL 上下文**：每次切换方式都要 `destroy()` 旧实例，避免累积（浏览器上限约 16 个）。

### 4.2 十连抽：纯 CSS 发牌 + 翻牌

```
点击「十连抽」
  → POST /api/draw_cards { count: 10, ...筛选 }
  → 全屏模态框，5×2 网格（移动端 2×5）
  → 每张牌从屏幕上方飞入（stagger 80~120ms），落位时背面朝上
  → 背面显示稀有度光效（边框颜色 + 光环强度）
  → 用户点击 / 按住拖过 来翻牌
  → 全部翻开后显示「再来一次 / 查看详情 / 关闭」
```

**发牌动画**（CSS，无需库）：

```css
@keyframes gacha-deal-in {
  from { transform: translate(var(--from-x), -120vh) rotate(var(--from-rot)) scale(.7); opacity: 0; }
  to   { transform: translate(0, 0) rotate(0) scale(1); opacity: 1; }
}
.gacha-card { animation: gacha-deal-in var(--deal-dur, 620ms) cubic-bezier(.2,.9,.3,1.2) backwards; }
.gacha-card:nth-child(1) { animation-delay: 0ms }
.gacha-card:nth-child(2) { animation-delay: 90ms }
/* … 依次 +90ms */
```

**翻牌**：复用现有 `.card-flip-inner` 结构（`view-cards.css:787-895`，已含 `preserve-3d` + `backface-visibility: hidden` + `.is-flipped`）。

### 4.3 ★ 拖拽批量翻牌（你的需求，实现方案）

```js
let dragging = false;

grid.addEventListener('pointerdown', (e) => {
  dragging = true;
  grid.setPointerCapture(e.pointerId);
  flipAt(e.clientX, e.clientY);
});

grid.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  flipAt(e.clientX, e.clientY);      // 连续命中，划过即翻
});

['pointerup', 'pointercancel'].forEach(t =>
  grid.addEventListener(t, () => { dragging = false; }));

function flipAt(x, y) {
  const el = document.elementFromPoint(x, y)?.closest('.gacha-card:not(.is-flipped)');
  if (el) flipCard(el);              // 加 .is-flipped + 播翻牌音
}
```

**必须配套的 CSS**（否则会选中文字 / 触发页面滚动）：

```css
.gacha-grid { touch-action: none; user-select: none; -webkit-user-select: none; }
.gacha-overlay { overflow: hidden; overscroll-behavior: contain; }
```

**无障碍补充**（拖拽不可达）：
- 每张牌可聚焦，`Space`/`Enter` 翻开；
- **「全部翻开」按钮** —— 既解决无障碍，也解决「嫌墨迹」；
- `prefers-reduced-motion` 时跳过飞入动画，直接显示网格。

### 4.4 后端：新增 `POST /api/draw_cards`

**保留 `random_card` 不动**（有契约测试引用）。

```python
# 入参
{ "count": 1 | 10, "category": ..., "tags": [...], "search": ..., ... }  # 沿用 random_card 全部筛选参数

# 出参
{ "success": true,
  "cards": [ { ...card, "rarity": "N|R|SR|SSR|UR" }, ... ],
  "pool_size": 1234,
  "pity_applied": false }
```

**稀有度派生**（放 `core/services/`，纯函数放 `core/utils/`）：

```python
# 阈值与前端 format.js 的 TOKEN_THRESHOLDS 保持一致
TOKEN_WARN, TOKEN_DANGER, TOKEN_EXTREME = 5000, 20000, 100000

def derive_rarity(card) -> str:
    if card.get('is_favorite'):
        return 'UR'
    t = int(card.get('token_count') or 0)
    if t > TOKEN_EXTREME: return 'SSR'
    if t > TOKEN_DANGER:  return 'SR'
    if t > TOKEN_WARN:    return 'R'
    return 'N'
```

**抽取策略**：

- **不加权**（推荐起步）：稀有度分布 = 卡库自然分布。绝大多数卡库以 N/R 为主，SSR/UR 天然稀有，**零配置即得真实手感**。
- **卡池充足**（`len(candidates) >= count`）：`random.sample()` 无放回，十连不重复。
- **卡池不足**（`len < count`）：`random.choices()` 有放回，重复项标 `duplicate: true`，并返回 `pool_size` 让前端提示。**详见 §5.2。**
- **十连保底**：先随机定一个保底位，确保至少 1 张 SR+；**卡池无 SR+ 时静默跳过**（`pity_applied: false`），不报错。
- **可选**：返回 `seed` 便于复现/晒图。

**筛选参数必须补全**（见 §5.2 末尾的既有 bug）：`/api/draw_cards` 应接受与 `/api/list_cards` 对齐的**全部**筛选条件 —— `fav_filter`、`excluded_tags`、`token_min/max`、`import_date_*`、`modified_date_*`，而不只是 `random_card` 现在的那 7 个。

### 4.5 新增文件清单

| 文件 | 用途 |
|---|---|
| `templates/modals/gacha_draw.html` | 抽卡模态框（单抽 / 十连两个视图 + 右上角 `styled_select`） |
| `static/js/components/gachaDraw.js` | Alpine 组件：抽取、发牌、拖拽翻牌、pack-opener 编排 |
| `static/css/modules/modal-gacha.css` | 发牌/翻牌/稀有度光效/卡背悬浮显影样式 |
| `static/lib/pack-opener/` | vendored：`index.js` + `chunks/` + `pixi.min.mjs` + `LICENSE` + `sounds/`（CC0） |
| `static/lib/pokemon-cards-css/` | vendored：`css/`（加 `.gacha-reveal` 前缀 + 路径改写）+ `img/` + `LICENSE` |
| `static/images/gacha/pack.png` | 单抽卡包图（生图，1 张） |
| `static/images/gacha/card-back.png` | 十连卡背图（生图，1 张，同底图） |
| `static/icons/ui.svg`（改） | **新增 `icon-volume-on` / `icon-volume-off`**（见 §5.1）→ 需重跑 `tools/gen_plugin_ui_icons.py` |
| `core/services/gacha_service.py` | 稀有度派生 + 抽取 + 保底 + 卡池边界（见 §5.2） |
| `tests/test_gacha_draw.py` | 后端测试（含空池 / 不足 10 张 / 无 SR+ 保底 / 重复标记） |

**接线点**（各 1 行）：
- `templates/index.html`：`{% include "modals/gacha_draw.html" %}`
- `static/js/app.js`：`Alpine.data("gachaDraw", gachaDraw)`
- `templates/layout.html`：`<link rel="stylesheet" href="/static/css/modules/modal-gacha.css" />`
- 入口按钮：`templates/components/header.html:728` 附近新增（保留原「随机」为次要动作）

---

## 5. 已定稿的决策

| # | 决策 | 结论 |
|---|---|---|
| 1 | **卡背方案** | **同底图 + 悬浮/聚焦才显影**（不悬浮时十张完全一致，保留悬念），见 §3.4 |
| 2 | **单抽方式** | **三种全支持**（`slice`/`burst`/`carousel`），右上角下拉切换，默认 `slice`，见 §3.5 |
| 3 | **下拉框** | **复用现有 `styled_select` 宏 + `styledSelect()`**，不自造，见 §3.6 |
| 4 | **抽卡历史** | **不做**（避免持久化与复杂度） |
| 5 | **音效** | **默认开启** + 右上角音量按钮可关闭，见 §5.1 |
| 6 | **稀有度文字** | 按推荐：仅 `carousel` 显示（它有 `facts` 机制），另两个靠光效+音效暗示 |
| 7 | 十连是否加权 | **不加权**（自然分布最真实）；保底另算 |
| 8 | 十连保底 | **加**，至少 1 张 SR+ |
| 9 | 十连翻牌 | 拖拽批量翻 + 「全部翻开」按钮 |
| 10 | 单抽/十连共用弹窗 | 共用（一个模态框两个视图） |
| 11 | **卡池不足 / 空池** | 见 §5.2（已给出完整处理） |

### 5.1 音效开关：需要你设计 2 个图标

**实测确认：全部 192 个图标里没有任何音量/喇叭/静音图标**（`ui.svg` 143 个，`detail.svg` 26 个，`sidebar.svg` 10 个，`preset.svg` 13 个 —— 全部扫过，无 `volume`/`speaker`/`mute`/`sound`/`audio`/`bell`/`music`）。

需要你出 **2 个**：

| 图标 id | 语义 | 建议图形 |
|---|---|---|
| `icon-volume-on` | 音效开启 | 喇叭 + 右侧 2 道声波弧线 |
| `icon-volume-off` | 音效关闭 | 同喇叭 + 斜杠（或声波换成 ×） |

**作者规范**（照 `static/icons/ui.svg` 现有约定，`docs/svg-icon-system.md` + `icons.css:2-14`）—— **已实测验证**（见下）：

```xml
<symbol id="icon-volume-on" viewBox="0 0 24 24">
  <path d="M11 5 6 9H3v6h3l5 4V5Z" />        <!-- 喇叭本体 -->
  <path d="M15.5 8.5a5 5 0 0 1 0 7" />       <!-- 声波 1 -->
  <path d="M18.5 6a9 9 0 0 1 0 12" />        <!-- 声波 2 -->
</symbol>

<symbol id="icon-volume-off" viewBox="0 0 24 24">
  <path d="M11 5 6 9H3v6h3l5 4V5Z" />        <!-- 同喇叭本体，切换时不跳形 -->
  <path d="m16 9 5 6" />
  <path d="m21 9-5 6" />
</symbol>
```

（上面是可直接用的**候选实现**，你可以直接用或按自己审美调整。）

- **放在 `static/icons/ui.svg`**（跨页面通用 → 归 `ui.svg`）。
- **`viewBox="0 0 24 24"`** —— 全局统一坐标系，`icon()` 宏硬编码了这个 viewBox。
- **描边式，不要在 symbol 里写 `fill`/`stroke`** —— 由 CSS 统一给：
  ```css
  .ui-icon { fill: none; stroke: currentColor; stroke-width: 2;
             stroke-linecap: round; stroke-linejoin: round; }
  ```
  路径要用 `d` 描述**轮廓线**（像 `icon-eye`/`icon-eye-off` 那样），不要实心填充。参考 `ui.svg` 的 `icon-eye-off`（喇叭+斜杠，与静音图标几乎同构）。
- **颜色交给 `currentColor`**（自动跟随主题/浅深色/强调色/禁用态）。
- 尺寸用现成修饰符：`ui-icon--xs`(12) / `--sm`(14) / `--md`(16) / `--lg`(20) / `--xl`(24)。
- **加完必须重跑生成器**（否则 `tests/test_plugin_icons.py` 失败）：
  ```powershell
  python tools/gen_plugin_ui_icons.py
  python tools/gen_plugin_ui_icons.py --check   # 校验
  python -c "import xml.etree.ElementTree as ET; ET.parse('static/icons/ui.svg')"   # XML 合法性
  ```

> **已实测**（`pack-opener-testlib/icons.html` + `verify-icons.mjs`，无头 Chrome）：symbol 内不写 `fill`/`stroke` 时，computed style 正确解析为 `fill: none; stroke: rgb(241,245,249); stroke-width: 2px; stroke-linecap: round`，深/浅色/强调色/禁用态全部正确跟随。截图见 `shots/icons.png`。

**音量状态的持久化**：用 `localStorage`（仓库既有做法，如 `state.js:926` 的 `st_manager_per_page`）。建议 key `st_manager_gacha_sound`，值为 `"1"`/`"0"`。**不写进 `ui_data`/`config.json`** —— 这是纯前端娱乐偏好，不值得进后端配置与持久化层。

> 若你希望它跟随全局设置（像 `card_effects_enabled` 那样进设置页），告诉我，那就要改 4 处（`core/config.py`、`settingsModal.js`、`state.js`、`settings.html`）。**我建议先用 localStorage**。

### 5.2 ★ 卡池不足 / 空池的处理

这是必须处理的边界。**三档情况，行为各不相同**：

#### 情况 A：候选 0 张（当前筛选条件下没有任何卡）

```json
{ "success": false, "code": "EMPTY_POOL", "msg": "当前筛选条件下没有角色卡", "pool_size": 0 }
```

**前端**：**不打开抽卡动画**（没意义），直接弹 toast：
> `当前筛选条件下没有角色卡，请调整筛选条件后再试`

复用现有 toast（`layout.html:53` 的 `.toast-notification`）或 `$store.global.showToast()`。**不要**进入弹窗后再报错 —— 用户会以为功能坏了。

#### 情况 B：候选 ≥ 1 但 < 10（十连抽卡池不够）

**这是最需要设计的一档。** 三种可选策略：

| 策略 | 行为 | 评价 |
|---|---|---|
| ① 拒绝十连 | 报错「卡池不足 10 张」 | ❌ 差体验，用户会困惑 |
| ② **允许重复**（推荐） | 抽满 10 张，重复的标记 `duplicate: true` | ✅ **符合真实抽卡**（重复卡本来就是常态） |
| ③ 降级为 N 张 | 有几张抽几张 | ⚠️ 可接受，但十连变「三连」很怪 |

**推荐策略 ②**：`random.choices()`（有放回）而非 `random.sample()`。理由：
- 真实手游的「重复」是常态，本来就有「重复转碎片」的机制；
- 用户体验连续，不会因为卡池小就功能不可用；
- 前端可以在重复卡上打一个「重复」角标（这也是抽卡游戏的标配）。

```python
if len(candidates) >= count:
    picks = random.sample(candidates, count)          # 无放回，不重复
else:
    picks = random.choices(candidates, k=count)       # 有放回，会出现重复
    # 标记重复项
    seen = set()
    for p in picks:
        if p['id'] in seen:
            p['duplicate'] = True
        seen.add(p['id'])
```

**前端提示**：若 `pool_size < 10`，在弹窗顶部显示一行淡色提示：
> `卡池仅 3 张，本次十连可能出现重复`

**返回 `pool_size`** 让前端能显示这个提示。

#### 情况 C：候选只有 1 张

策略 ② 自然覆盖：十连出 10 张同一张卡（全标 `duplicate`）。视觉上略滑稽但**不算 bug**，且比报错好。可加一句提示：`卡池仅 1 张`。

#### 保底与卡池的交互（重要）

十连保底「至少 1 张 SR+」在**卡池里根本没有 SR+** 时会失效：

```python
high = [c for c in candidates if derive_rarity(c) in ('SR', 'SSR', 'UR')]
if high:
    # 正常保底：先把保底位定下来
    picks[random.randrange(count)] = random.choice(high)
    pity_applied = True
else:
    # 卡池无高稀有度 → 跳过保底，不算失败
    pity_applied = False
```

**关键**：卡池无高稀有度时**静默跳过保底**，不要报错。前端也不提示（用户无从判断，提示反而困惑）。

#### 前端空态与降级总表

| 场景 | 后端 | 前端 |
|---|---|---|
| 0 张 | `success: false, code: EMPTY_POOL` | **不开弹窗**，toast 提示 |
| 1–9 张（十连） | `success: true`，可能含 `duplicate`，带 `pool_size` | 开弹窗 + 顶部淡色提示「卡池仅 N 张，可能出现重复」+ 重复卡角标 |
| ≥10 张 | 正常 | 正常 |
| 无 SR+ 且请求保底 | `pity_applied: false` | 不提示（静默） |
| 单抽 0 张 | 同「0 张」 | 同「0 张」 |
| 单抽 1 张 | 正常 | 正常 |

#### ⚠️ 顺带发现一个既有 bug（与本次改动相关，建议一并修）

**`/api/random_card` 丢失了大部分筛选条件。** 对比两个接口接受的参数：

| 筛选 | `/api/list_cards`（网格用） | `/api/random_card`（随机用） |
|---|---|---|
| `category` / `tags` / `search` / `search_scope` | ✅ | ✅ |
| `fav_filter`（收藏筛选） | ✅ | ❌ **缺失** |
| `excluded_tags`（排除标签） | ✅ | ❌ **缺失** |
| `token_min` / `token_max` | ✅ | ❌ **缺失** |
| `import_date_*` / `modified_date_*` | ✅ | ❌ **缺失** |
| `sort` | ✅ | ❌ 不适用 |

而 `viewState`（`state.js:799-820`）里**这些字段都存在**，`header.js:894-903` 却**只传了 7 个**。

**后果**：用户在侧边栏勾了「仅收藏」或设了 Token 范围，点随机 —— **随机结果不遵守这些筛选**，会在网格里高亮出一张当前视图看不见的卡。这是既有行为，不是本次改动引入的。

**建议**：新的 `/api/draw_cards` **把筛选参数补全**（对齐 `/api/list_cards`），顺手也修 `random_card`。否则抽卡会出现「抽到不在当前筛选里的卡」的诡异现象 —— 对抽卡功能来说这尤其致命（用户会认为概率有问题）。

---

## 6. 可借用清单（按性价比）

| 优先级 | 来源 | 搬什么 | 许可 |
|---|---|---|---|
| ⭐⭐⭐⭐⭐ | `pack-opener` | dist + `pixi.min.mjs`（import map 免打包，**已实测**） | MIT + CC0 音效 |
| ⭐⭐⭐⭐⭐ | `pokemon-cards-css` | 稀有度 CSS + 9 张图（约 636 KB），**类名桥接到 cards-css 运行时** | GPL-3.0（与 AGPL 兼容） |
| ⭐⭐⭐⭐⭐ | `cards-css` | 已 vendored，14 foil + 变量外发 | MIT |
| ⭐⭐⭐⭐ | `lucky-boy` | `lottery-table/src/utils/audio.ts`(61 行) + `lottery-helix/src/utils/audio.ts`(73 行)，纯 WebAudio 零依赖 | MIT |
| ⭐⭐⭐ | `canvas-confetti` | UMD 10.8 KB，`shapeFromText('★')` 做稀有度粒子 | ISC |
| ⭐⭐⭐ | `pack-opener` | `shared/geometry.js`(162 行零依赖数学) + `runtime/color.js`(73 行) | MIT |
| ⭐⭐ | `lucky-boy` | 跑马灯减速数值配方（`delay = 100 + 400t²`）+ `@keyframes rotate-border` | MIT |
| ⭐⭐ | `html5-slot-machine` | `Reel.js` WAAPI 滚动（「摇奖」阶段） | MIT |
| ⭐ | `atropos` / `party-js` / `fireworks-js` | 若需要更强 3D 倾斜 / 稀有度粒子模板 / 传奇档烟花 | MIT |

**明确不做**：不引入 React、three.js（`holo3D-card` 的 POM 浮雕在无 depth map 时是死代码，补齐需 torch+easyocr 数 GB 依赖）。

---

## 7. 风险与注意事项

1. **契约测试**：改动 `grid_cards.html` / `cardGrid.js` / `settings.html` 会触发字符串断言失败 → **新增文件优先**，或同步更新断言。
2. **性能**：十连 = 10 张卡 × pokemon 的重度混合模式（`color-dodge`/`overlay` + 多层背景 + `will-change`）。建议：
   - 落位阶段只用轻量样式，**翻开后才挂载重特效**；
   - 静态网格去掉 `will-change`（那是给拖拽交互用的）；
   - `prefers-reduced-motion` 直接降级。
3. **WebGL 生命周期**：单抽弹窗关闭时**必须调 `opener.destroy()`**（已实测能回收 canvas）。避免多次抽卡累积 WebGL 上下文（浏览器上限约 16 个）。
4. **`card_effects_enabled` 关闭时**：抽卡揭晓也要降级（无 foil、直接显示结果），与现有 `card-effect-disabled` 路径一致。
5. **缩略图分辨率**：pack-opener 按 ~620×900 渲染，需确认 `/api/thumbnail/` 尺寸够用，否则单抽卡面会糊。
6. **许可登记**：`pokemon-cards-css` 是 GPL-3.0，需保留其 `LICENSE` 并在根 `LICENSE` 的 notice 段落登记（仿现有 `static/lib/cards-css/` 的做法）。
7. **拖拽翻牌**：`touch-action: none` + `user-select: none` 必须加，否则移动端会滚动/选中文字。
8. **可复现性**：若要做「晒十连」，接口返回 `seed`。

---

## 8. 建议落地顺序

1. **后端**：`gacha_service.py`（稀有度派生 + 抽取 + 保底 + **卡池边界**）+ `POST /api/draw_cards`（**筛选参数对齐 list_cards**）+ `tests/test_gacha_draw.py`
2. **稀有度映射表**：前端集中一处 `RARITY_FOIL_MAP` / `RARITY_COLOR` / `RARITY_LABEL`
3. **图标**：你出 `icon-volume-on` / `icon-volume-off` → 合入 `ui.svg` → 重跑 `tools/gen_plugin_ui_icons.py`
4. **vendoring**：`pack-opener`（含 pixi + import map）+ `pokemon-cards-css`（加作用域前缀 + 改写图片路径）
5. **十连**：弹窗骨架 + 发牌动画 + 翻牌 + 拖拽批量翻 + 卡背悬浮显影 + **卡池不足提示 / 重复角标**
6. **单抽**：接 pack-opener 三变体 + 右上角 `styled_select` + 音量按钮 + 交叉淡入到真实卡面
7. **生图**：卡包图 + 卡背图（各 1 张）
8. **打磨**：音效、SSR/UR 专属飞入、撒花、「全部翻开」按钮
9. **设置开关** + 入口按钮 + 无障碍
10. **顺手修**：`/api/random_card` 的筛选参数缺失（§5.2 末尾）

---

## 附：验证产物清单

`D:\Workspace\MyOwn\pack-opener-testlib\`（可复跑的独立验证沙盒，不属于生产代码）：

| 文件 | 用途 |
|---|---|
| `index.html` | import map + `slice` 变体验证页 |
| `burst.html` | `burst` 变体 + `destroy()` 清理验证页 |
| `carousel.html` | `carousel` 变体（含 `facts`/`badge`）验证页 |
| `specificity.html` | cards-css × pokemon 特异性冲突实测页 |
| `icons.html` | **音量图标作者规范验证页**（含可直接用的候选实现） |
| `verify-importmap.mjs` | CDP 断言：免打包可行 |
| `verify-burst.mjs` | CDP 断言：burst + 清理 |
| `verify-carousel.mjs` | CDP 断言：carousel |
| `verify-specificity.mjs` | CDP 断言：作用域前缀方案 |
| `verify-icons.mjs` | CDP 断言：图标描边/着色继承 |
| `shoot-phases.mjs` / `shoot-carousel.mjs` | 分相位截图 |
| `lib/` | pack-opener dist + `pixi.min.mjs` + pokemon 最小 CSS 集 |
| `shots/` | 实测截图（slice / burst / carousel / specificity / icons） |

复跑：先 `python -m http.server 4321 --bind 127.0.0.1`（在该目录），再 `node verify-*.mjs`。

---

## 附：环境备注

- `git clone` 曾因 `CRYPT_E_REVOCATION_OFFLINE`（schannel 吊销检查）全部失败，`git config --global http.schannelCheckRevoke false` 可解。
- `pnpm` 对 `packageManager` 字段做签名校验，pin 旧版本会拒绝运行；加 `--config.pm-on-fail=ignore --config.manage-package-manager-versions=false` 绕过。
- `pack-opener` 的 `react-native` peer 依赖拉不下来，但 **web 侧不需要**（`npm install --no-save` 只装 web 侧即可）。
- 本机 npm registry 连接不稳，`--network-concurrency=3` + 重试可缓解。
