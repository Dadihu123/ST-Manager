/**
 * static/js/utils/pluginReleaseNotes.js
 * 插件「本次更新说明」的纯函数工具（无 DOM 依赖，可在 Node 里直接测）。
 *
 * 数据来自 `POST /api/plugins/catalog/check_updates` 的 `release_notes` /
 * `release_notes_source` / `release_notes_truncated`。这三段内容**全部是外部
 * 不可信输入**（GitHub Release body 由插件作者写，CHANGELOG 来自插件仓库），
 * 因此这里承担两件事：
 *
 * 1. **净化**：先剥掉正文里的原始 HTML，再交给 `updateShadowContent()` 渲染。
 *    `static/js/utils/dom.js` 的 `updateShadowContent()` 有一条
 *    `looksLikeTrustedHtml` 直插分支（内容以 `<tag` 开头就原样 `innerHTML`
 *    插入），`htmlFragmentRegex` 还会对 `<div|style|details|section|…` 开头的内容
 *    `forceHtmlMode` 走隔离 HTML 运行时的直通路径——两条都以「正文里没有裸标签」
 *    为前提。所以净化必须发生在渲染之前，且必须保证结果不以 `<` 开头。
 *
 * 2. **兜底文案**：来源徽标、版本变化、无说明提示等纯文本，全部走 `x-text`，
 *    不进 HTML。
 *
 * 约束：任何函数都不得抛异常；最差返回空串 / 空结构。净化必须幂等
 * （模板里的 `x-effect` 会随 `updateConfirm` 反复求值）。
 *
 * 已知取舍：围栏代码块里的原始 HTML 也会被剥掉（净化发生在 markdown 解析之前，
 * 不认识围栏边界）。这是有意的——代码块里的 `<script>` 与正文里的没有任何区别，
 * 而「更新说明里的示例代码被吃掉」远比「执行插件作者写的脚本」便宜。
 */

/** 说明来源 → 中文文案（后端 `release_notes_source` 的三态）。 */
const NOTES_SOURCE_LABELS = {
  release: "来自 GitHub Release",
  changelog: "来自插件 CHANGELOG",
};

/** 会连内容一起丢掉的危险块（脚本 / 样式 / 注释 / CDATA）。 */
const DANGEROUS_BLOCKS = [
  /<script\b[^>]*>[\s\S]*?<\/script\s*>/gi,
  /<style\b[^>]*>[\s\S]*?<\/style\s*>/gi,
  /<iframe\b[^>]*>[\s\S]*?<\/iframe\s*>/gi,
  /<!--[\s\S]*?-->/g,
  /<!\[CDATA\[[\s\S]*?\]\]>/g,
];

/** 剩余标签（含属性、自闭合、孤立 `<` + 标识符）。 */
const HTML_TAG = /<\/?[a-zA-Z][^>]*>/g;

/** 同上的非全局版本：`RegExp#test` 带 `/g` 会推进 `lastIndex`，判断用这个。 */
const HAS_TAG = /<\/?[a-zA-Z][^>]*>/;

/**
 * 命中 `dom.js` 直插分支的「危险开头」判定。
 *
 * 与 `static/js/utils/dom.js:860` 的 `looksLikeTrustedHtml` 同形——**必须同形**，
 * 不能更松也不能更严：
 * - 更松（比如原来的 `/^\s*</`）会误判 `< b`、`<3` 这类字面文本，把无害内容
 *   拖进二次净化；
 * - 更严则会漏掉真正会被 `innerHTML` 直插的形状。
 *
 * `htmlFragmentRegex`（dom.js:706）匹配的 `<div|style|details|…` 都是
 * `<` 紧跟字母，已被这条覆盖。
 */
const LEADING_ANGLE = /^\s*<(?:[a-z][\w:-]*|!doctype|!--)/i;

function asString(value) {
  if (value === null || value === undefined) return "";
  try {
    return String(value);
  } catch (_error) {
    return "";
  }
}

/**
 * 转义剩余的特殊字符（保留既有实体，保证重复调用结果不变）。
 *
 * 两条约束同时成立：
 *
 * 1. **幂等**：`&` 只在「不是某个实体的一部分」时转义，因此 `&lt;` 不会被
 *    二次转义成 `&amp;lt;`——模板里的 `x-effect` 会反复求值。
 *
 * 2. **不产生二次转义**：净化后的文本还要交给 `marked.parse()` 渲染，而 marked
 *    在代码块 / 行内代码里会把 `&` 再转义一次。所以这里**只转义真正可能开启
 *    标签的 `<`**（后面紧跟 `/`、`!`、`?` 或字母），`a < b` 这种 `<` 后是空格
 *    的写法在 HTML 里本来就是字面文本，转义它只会在 marked 之后变成
 *    `&amp;lt;`，让用户看到字面 `&lt;`。
 *
 *    `>` 同理不转义：它永远无法开启标签，转义只会让代码块里的 `a > b` 变成
 *    字面 `&gt;`，还会把 markdown 引用块（`> 引用`）打回普通段落。
 */
function escapeHtml(text) {
  return asString(text)
    .replace(/&(?!(?:[a-zA-Z][a-zA-Z0-9]*|#\d+|#x[0-9a-fA-F]+);)/g, "&amp;")
    .replace(/<(?=[/!?a-zA-Z])/g, "&lt;");
}

/**
 * 代码段占位 token。
 *
 * **必须是纯 ASCII**：早期方案用 `\u0000CODE0\u0000`，但 DOMPurify 走 HTML 解析，
 * NUL 会被替换成 U+FFFD，token 就再也还原不回来（占位符会漏进正文）。
 * `STMRELEASENOTES<n>END` 全大写字母数字，既不会被 HTML 解析改写，也不会被
 * markdown 当成语法。
 */
const TOKEN_PREFIX = "STMRELEASENOTES";
const TOKEN_RE = /STMRELEASENOTES(\d+)END/g;

/** 围栏代码块（``` / ~~~）。 */
const FENCE_CODE = /```[\s\S]*?```|~~~[\s\S]*?~~~/g;

/** 行内代码（`` `...` ``，不跨行、不允许内部再有反引号）。 */
const INLINE_CODE = /`[^`\n]+`/g;

/**
 * 把代码段换成占位 token，返回 `{ output, saved }`。
 *
 * 为什么要保护：`HTML_TAG` / DOMPurify 都会把 `<key>`、`<id>`、`<select class="x">`
 * 当标签删掉，而插件 CHANGELOG 里到处是这种**惰性文本**（marked 渲染代码段时
 * 自己会转义 HTML，所以代码段里的 `<script>` 只是字面文本，不需要我们插手）。
 * 不保护 = 把插件的接口约定说明吃掉半句。
 */
function protectCode(text) {
  const saved = [];
  const stash = (match) => {
    saved.push(match);
    return `${TOKEN_PREFIX}${saved.length - 1}END`;
  };
  // 先围栏再行内：围栏里可能含反引号，顺序反了会被行内规则切碎
  let output = asString(text).replace(FENCE_CODE, stash);
  output = output.replace(INLINE_CODE, stash);
  return { output, saved };
}

/** 把占位 token 还原成原始代码段；token 不存在时原样返回。 */
function restoreCode(text, saved) {
  if (!Array.isArray(saved) || !saved.length) return asString(text);
  return asString(text).replace(TOKEN_RE, (_match, index) => {
    const original = saved[Number(index)];
    return typeof original === "string" ? original : "";
  });
}

/** 本地回退净化：先把危险块连内容删掉，再删所有标签，最后转义残留字符。 */
function stripTagsLocally(text) {
  let output = asString(text);
  for (const pattern of DANGEROUS_BLOCKS) {
    output = output.replace(pattern, "");
  }
  output = output.replace(HTML_TAG, "");
  return escapeHtml(output);
}

/** 用全局 DOMPurify 净化成纯文本；不可用或抛错时返回 null（交给回退路径）。 */
function purifyWithDomPurify(text) {
  const purifier = typeof globalThis !== "undefined" ? globalThis.DOMPurify : null;
  if (!purifier || typeof purifier.sanitize !== "function") return null;
  try {
    const cleaned = purifier.sanitize(asString(text), {
      ALLOWED_TAGS: [],
      ALLOWED_ATTR: [],
    });
    return cleaned === null || cleaned === undefined ? null : asString(cleaned);
  } catch (_error) {
    return null;
  }
}

/**
 * 把外部备注正文净化成可安全交给 `updateShadowContent()` 的 markdown 文本。
 *
 * 保留 markdown 语法（`##` / `-` / ``` 围栏 / `|` 表格），只去掉**代码段之外**
 * 的原始 HTML。流程：
 *
 *   protectCode → 净化（DOMPurify 或本地回退）→ 纵深防御 → restoreCode
 *
 * 保护必须发生在净化**之前**，两条净化路径都要作用在保护后的文本上：
 * 否则代码段里的 `<key>` 会被当标签删掉（DOMPurify 一样会删）。
 *
 * 结果保证：代码段外不含标签、重复调用结果一致、不抛异常。
 *
 * ⚠️ 返回值仍可能包含代码段里的 `<script>` 字面文本。**不要**直接交给
 * `updateShadowContent()`——`dom.js:738-743` 会嗅探裸 `<script` 并路由到
 * 无 sandbox 的同源 iframe。渲染前必须先经 `marked.parse()`（见
 * `renderNotesHtml()`），让代码段变成 `&lt;script&gt;` 惰性文本。
 */
export function sanitizeNotesMarkdown(raw) {
  let text = "";
  try {
    text = asString(raw);
    if (!text.trim()) return "";

    const { output: protectedText, saved } = protectCode(text);

    let cleaned = purifyWithDomPurify(protectedText);
    if (cleaned === null) cleaned = stripTagsLocally(protectedText);
    cleaned = asString(cleaned);

    // 纵深防御：DOMPurify 缺失、被替换或行为异常时，也绝不能把裸标签交出去。
    // 此时代码段还是 token，不含标签，所以这条只针对代码段外的残留。
    if (LEADING_ANGLE.test(cleaned) || HAS_TAG.test(cleaned)) {
      cleaned = stripTagsLocally(cleaned);
    }
    return restoreCode(cleaned, saved);
  } catch (_error) {
    try {
      const { output: protectedText, saved } = protectCode(text);
      return restoreCode(stripTagsLocally(protectedText), saved);
    } catch (_nested) {
      return "";
    }
  }
}

/**
 * 把净化后的 markdown 渲染成 HTML，供 `updateShadowContent()` 使用。
 *
 * **这一步是安全边界，不是格式化**：`updateShadowContent()` 会先嗅探
 * `rawContent.includes("<script")` / `"<html"` / `"<!DOCTYPE"`（`dom.js:738-743`），
 * 命中就把原文当 `htmlPayload` 交给 `renderIsolatedHtml()`，而那个 iframe
 * （`renderRuntime.js:158-163`）**没有 sandbox 属性**、blob URL 又与宿主同源，
 * 脚本会真的执行。先经 `marked.parse()` 后，代码段里的 `<script>` 变成
 * `&lt;script&gt;`，嗅探看不到裸标签，因此永远走 markdown 分支。
 *
 * 与 `templates/modals/markdown_preview.html:21` 的既有做法一致
 * （那里传的也是 `renderMarkdown(...)` 的结果）。
 *
 * `marked` 不可用时退回**纯转义文本**——绝不能把含 `<script` 的原文交出去。
 */
export function renderNotesHtml(markdown) {
  const source = asString(markdown);
  if (!source.trim()) return "";
  try {
    if (typeof globalThis !== "undefined" && globalThis.marked && typeof globalThis.marked.parse === "function") {
      const html = asString(globalThis.marked.parse(source, { breaks: true }));
      // 兜底：万一 marked 版本行为变化没转义干净，宁可整体转义也不放行
      if (/<script|<html|<!DOCTYPE/i.test(html)) return escapeHtml(source);
      return html;
    }
  } catch (_error) {
    /* 落到下面的纯转义 */
  }
  return escapeHtml(source);
}

/** 说明来源的中文文案；未知来源返回空串（模板据此隐藏徽标）。 */
export function notesSourceLabel(source) {
  const key = asString(source).trim();
  return NOTES_SOURCE_LABELS[key] || "";
}

/** 说明的来源路径：`update-check` 查过，`catalog` 没查过。 */
export const NOTES_ORIGINS = {
  UPDATE_CHECK: "update-check",
  CATALOG: "catalog",
};

/**
 * 把一条 update 记录整理成弹层要用的扁平结构。
 *
 * `installed` / `available` 来自 check_updates，`installed_version` / `version`
 * 来自 catalog 条目——两个入口共用同一个弹层，所以两组字段都要认。
 * 缺字段一律兜底成空串 / false，绝不抛异常。
 *
 * **`origin` 必须由调用方如实传入**（默认 `update-check`）：目录页那条路径
 * 根本不请求 `check_updates`，条目里也没有 `release_notes`。若把「这条路径
 * 没去取」当成「插件没写说明」，弹层就会凭空断言一个我们没验证过的事实。
 * 因此 `notesFetched` 只在真的查过时为 true，`source` / `truncated` 也只在
 * 查过时才可能有值——没查过就不该声称来源，更不该声称被截断。
 *
 * @param {object} update catalog 条目或 check_updates 记录
 * @param {{origin?: string}} [options] `origin`：`update-check` | `catalog`
 */
export function updateSummary(update, options = {}) {
  const item = update && typeof update === "object" ? update : {};
  const origin =
    (options && options.origin) === NOTES_ORIGINS.CATALOG
      ? NOTES_ORIGINS.CATALOG
      : NOTES_ORIGINS.UPDATE_CHECK;
  const notesFetched = origin === NOTES_ORIGINS.UPDATE_CHECK;

  const id = asString(item.id).trim();
  const name = asString(item.name).trim() || id;
  const from = asString(item.installed).trim() || asString(item.installed_version).trim();
  const to = asString(item.available).trim() || asString(item.version).trim();
  // 没查过说明：来源与截断状态都无从得知，一律按「未知」处理
  const source = notesFetched ? asString(item.release_notes_source).trim() : "";
  const notes = notesFetched ? sanitizeNotesMarkdown(item.release_notes) : "";
  return {
    id,
    name,
    from,
    to,
    notes,
    source,
    origin,
    notesFetched,
    sourceLabel: notesSourceLabel(source),
    truncated: notesFetched && item.release_notes_truncated === true,
    hasNotes: notes.trim().length > 0,
  };
}

/** 弹层正文的纯文本行（交给 `x-text`，不走 HTML）。 */
export function dialogIntroLines(summary) {
  const item = summary && typeof summary === "object" ? summary : {};
  const name = asString(item.name).trim() || asString(item.id).trim() || "该插件";
  const from = asString(item.from).trim();
  const to = asString(item.to).trim();

  let headline = `更新 ${name}`;
  if (from && to) headline = `把 ${name} 从 v${from} 更新到 v${to}`;
  else if (to) headline = `把 ${name} 更新到 v${to}`;
  else if (from) headline = `更新 ${name}（当前 v${from}）`;

  return [headline, "更新会覆盖安装，重启应用后生效"];
}
