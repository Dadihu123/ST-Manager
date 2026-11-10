"""插件更新确认弹层：备注净化纯函数 + 前端静态契约。

背景：插件「更新」原先是一个零内容的 `window.confirm`。改成弹层后多了一条
**外部不可信内容进入渲染**的通道（GitHub Release body / 插件仓库 CHANGELOG），
而渲染走的是 `static/js/utils/dom.js:updateShadowContent()`——它内部有
`looksLikeTrustedHtml` 直插分支（内容以 `<tag` 开头就原样 `innerHTML`），
还有 `htmlFragmentRegex` 对 `<div|style|details|section|…` 走隔离 HTML 直通。
所以必须在交给它之前净化，且净化后不得以 `<` 开头。

这份测试锁两件事：
1. `sanitizeNotesMarkdown()` 真的能打掉标签，同时**不破坏 markdown 语法**；
2. 模板 / 组件 / CSS 的接线不会悄悄退回 `window.confirm` 或裸 `innerHTML`。

Node 不在时跳过行为用例（与 `tests/test_plugin_host_state.py` 同一处理方式）。
"""

import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

MANAGER_JS = 'static/js/components/pluginManager.js'
MANAGER_TMPL = 'templates/modals/plugin_manager.html'
MANAGER_CSS = 'static/css/modules/modal-plugin-manager.css'
NOTES_JS = 'static/js/utils/pluginReleaseNotes.js'


def read_source(relative_path: str) -> str:
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def run_node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['node', '--input-type=module', '-e', textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


requires_node = pytest.mark.skipif(
    shutil.which('node') is None,
    reason='Node.js is required for the release-notes sanitizer checks',
)

# 假 DOMPurify：真实运行期由 `/static/lib/purify.min.js` 提供全局对象。
# 这里只需要复现「剥掉全部标签、保留文本」这一条契约，用来验证分支被走到。
FAKE_PURIFY = """
globalThis.DOMPurify = {
  sanitize(text, config) {
    if (!config || config.ALLOWED_TAGS?.length !== 0) throw new Error('contract drift');
    return String(text)
      .replace(/<script\\b[^>]*>[\\s\\S]*?<\\/script\\s*>/gi, '')
      .replace(/<[^>]*>/g, '');
  },
};
"""


def _node_assert(body: str) -> subprocess.CompletedProcess:
    return run_node(
        "import assert from 'node:assert/strict';\n"
        "import {\n"
        "  sanitizeNotesMarkdown,\n"
        "  notesSourceLabel,\n"
        "  updateSummary,\n"
        "  dialogIntroLines,\n"
        "  renderNotesHtml,\n"
        f"}} from './{NOTES_JS}';\n" + textwrap.dedent(body)
    )


def _assert_ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, f'node 断言失败:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}'


# ------------------------------------------------------------------ 净化：危险内容


@requires_node
def test_sanitize_removes_inline_event_handlers():
    """`<img onerror>` 必须在净化后彻底消失，不能只换个标签还在。"""
    _assert_ok(
        _node_assert(
            """
            const cleaned = sanitizeNotesMarkdown('更新说明\\n<img src=x onerror=alert(1)>\\n完');
            assert.ok(!cleaned.includes('onerror'), cleaned);
            assert.ok(!cleaned.includes('alert(1)'), cleaned);
            assert.ok(cleaned.includes('更新说明'), cleaned);
            """
        )
    )


@requires_node
def test_sanitize_removes_script_blocks_with_their_content():
    """`<script>` 连内容一起丢，不留下裸的 `alert(1)` 文本。"""
    _assert_ok(
        _node_assert(
            """
            const cleaned = sanitizeNotesMarkdown('## 修复\\n<script>alert(1)</script>\\n- 条目');
            assert.ok(!cleaned.includes('<script'), cleaned);
            assert.ok(!cleaned.includes('alert(1)'), cleaned);
            assert.ok(cleaned.includes('## 修复'), cleaned);
            assert.ok(cleaned.includes('- 条目'), cleaned);
            """
        )
    )


@requires_node
def test_sanitize_never_returns_content_starting_with_angle_bracket():
    """以 `<div` 开头的内容会命中 `updateShadowContent` 的直插分支——必须堵死。"""
    _assert_ok(
        _node_assert(
            """
            const cases = [
              '<div class="x">正文</div>',
              '<style>body{display:none}</style><details>正文</details>',
              '   <section>正文</section>',
              '<img src=x onerror=alert(1)>',
              '<svg onload=alert(1)>',
            ];
            for (const raw of cases) {
              const cleaned = sanitizeNotesMarkdown(raw);
              assert.ok(!/^\\s*</.test(cleaned), `仍以 < 开头: ${JSON.stringify(cleaned)}`);
              assert.ok(!/<[a-zA-Z]/.test(cleaned), `仍含标签: ${JSON.stringify(cleaned)}`);
            }
            """
        )
    )


@requires_node
def test_sanitize_works_without_dompurify_and_never_throws():
    """DOMPurify 缺失（脚本没加载 / 被插件删掉）时回退路径同样安全。"""
    _assert_ok(
        _node_assert(
            """
            delete globalThis.DOMPurify;
            const cleaned = sanitizeNotesMarkdown('## 标题\\n<img src=x onerror=alert(1)>\\n- 列表');
            assert.ok(!cleaned.includes('onerror'), cleaned);
            assert.ok(!cleaned.includes('<img'), cleaned);
            assert.ok(cleaned.includes('## 标题'), cleaned);
            assert.ok(cleaned.includes('- 列表'), cleaned);

            // 任何奇怪输入都不许抛
            for (const weird of [null, undefined, 0, false, {}, [], Symbol('x')]) {
              assert.doesNotThrow(() => sanitizeNotesMarkdown(weird));
            }
            """
        )
    )


@requires_node
def test_sanitize_uses_dompurify_when_available():
    """有 DOMPurify 时必须走它（真实运行期的首选路径），且保留 markdown。"""
    _assert_ok(
        _node_assert(
            FAKE_PURIFY
            + """
            const cleaned = sanitizeNotesMarkdown('## 标题\\n<img src=x onerror=alert(1)>\\n- 列表');
            assert.ok(!cleaned.includes('<img'), cleaned);
            assert.ok(!cleaned.includes('onerror'), cleaned);
            assert.ok(cleaned.includes('## 标题'), cleaned);
            assert.ok(cleaned.includes('- 列表'), cleaned);
            """
        )
    )


@requires_node
def test_sanitize_recovers_when_dompurify_throws():
    """DOMPurify 抛错也不能让弹层挂掉——回退到本地转义。"""
    _assert_ok(
        _node_assert(
            """
            globalThis.DOMPurify = { sanitize() { throw new Error('boom'); } };
            const cleaned = sanitizeNotesMarkdown('<b>粗体</b><script>alert(1)</script>');
            assert.ok(!cleaned.includes('<'), cleaned);
            assert.ok(cleaned.includes('粗体'), cleaned);
            """
        )
    )


# ------------------------------------------------------------------ 净化：不破坏 markdown


@requires_node
def test_sanitize_preserves_markdown_syntax():
    """`##` / `-` / 代码围栏 / 表格都不能被净化吃掉（否则说明变一坨）。"""
    _assert_ok(
        _node_assert(
            """
            const raw = [
              '## 0.4.1',
              '',
              '- 修复：图片渲染',
              '- 新增：上下文菜单',
              '',
              '```js',
              "console.log('hi')",
              '```',
              '',
              '| 项 | 说明 |',
              '| --- | --- |',
              '| a | b |',
            ].join('\\n');
            const cleaned = sanitizeNotesMarkdown(raw);
            for (const marker of ['## 0.4.1', '- 修复：图片渲染', '```js', 'console.log', '| 项 | 说明 |']) {
              assert.ok(cleaned.includes(marker), `丢失 markdown 片段 ${marker}: ${JSON.stringify(cleaned)}`);
            }
            assert.ok(cleaned.includes('\\n'), '换行被吃掉');
            """
        )
    )


@requires_node
def test_sanitize_is_idempotent():
    """模板里 `x-effect` 会反复求值：二次净化不得继续改变内容。"""
    _assert_ok(
        _node_assert(
            """
            const raws = [
              '## 标题\\n- 列表\\n<img src=x onerror=alert(1)>',
              '<div>a &amp; b</div>',
              '纯文本 & 一点点 <b>强调</b>',
            ];
            for (const raw of raws) {
              const once = sanitizeNotesMarkdown(raw);
              const twice = sanitizeNotesMarkdown(once);
              assert.equal(twice, once, `不幂等: ${JSON.stringify({ once, twice })}`);
            }
            """
        )
    )


# ------------------------------------------------------------------ 净化后交给 marked

# 用仓库自带 `static/lib/marked.min.js` 在 vm 沙箱里跑，确保测的是**真实渲染器**，
# 而不是我们对 marked 行为的假设。净化后的文本最终就是进这里。
MARKED_SANDBOX = """
import fs from 'node:fs';
import vm from 'node:vm';

const markedSource = fs.readFileSync('static/lib/marked.min.js', 'utf8');
const sandbox = { module: { exports: {} }, exports: {} };
vm.createContext(sandbox);
vm.runInContext(markedSource, sandbox, { filename: 'marked.min.js' });
const marked = sandbox.marked || sandbox.module.exports.marked || sandbox.module.exports;
assert.equal(typeof marked.parse, 'function', 'static/lib/marked.min.js 未能加载');
// renderNotesHtml() 读的是 globalThis.marked（真实运行期由 layout.html 的
// <script src="/static/lib/marked.min.js"> 提供全局对象）
globalThis.marked = marked;

const render = (raw) => marked.parse(sanitizeNotesMarkdown(raw), { breaks: true });

// dom.js:860 的真实判定（净化结果绝不能再命中它）
const looksLikeTrustedHtml = (text) => /^\\s*<(?:[a-z][\\w:-]*|!doctype|!--)/i.test(text);
// dom.js:706 的 forceHtmlMode 形状
const htmlFragment = (text) =>
  /^\\s*<(?:div|style|details|section|article|main|link|table|script|iframe|svg|html|body|head|canvas)/i.test(text);

// dom.js:717-749 的 HTML 载荷嗅探：命中就把原文塞进无 sandbox 的同源 iframe。
// 复刻它，是为了断言「交给 updateShadowContent 的字符串永远不会命中」。
function domPayloadRoute(rawContent) {
  const codeBlockRegex = /```(?:html|xml|text|js|css|json)?\\s*([\\s\\S]*?)```/gi;
  let payload = '';
  let match;
  let found = false;
  while ((match = codeBlockRegex.exec(rawContent)) !== null) {
    const block = match[1];
    if (
      block.includes('<!DOCTYPE') ||
      block.includes('<html') ||
      block.includes('<script') ||
      block.includes('export default') ||
      (block.includes('<div') && block.includes('<style'))
    ) {
      payload = block;
      found = true;
      break;
    }
  }
  if (
    !found &&
    (rawContent.includes('<!DOCTYPE') ||
      rawContent.includes('<html') ||
      rawContent.includes('<script'))
  ) {
    payload = rawContent;
  }
  return payload;
}
"""

# 行内代码 / 围栏代码里的比较运算符：必须单层转义，浏览器看到的是 `a < b`。
# 这组形状来自真实内容——插件 CHANGELOG 里就有 `worldbook.sources()` 之类的
# 代码片段，`a < b`、`x <= y`、`<placeholder>` 这类写法都会出现。


@requires_node
def test_marked_render_has_no_double_escaped_entities():
    """回归：`<` 全量转义 → marked 在代码块里再转义一次 → 用户看到字面 `&lt;`。

    `sanitizeNotesMarkdown()` 的输出还要过 `marked.parse()`，所以转义必须
    只针对**真正可能开启标签的 `<`**（后面紧跟 `/` `!` `?` 或字母）。
    `a < b` 这种 `<` 后是空格的写法在 HTML 里本来就是字面文本。
    """
    _assert_ok(
        _node_assert(
            MARKED_SANDBOX
            + """
            for (const [label, raw] of [
              ['行内 <', '修复 `a < b` 的比较'],
              ['围栏 <', '```js\\nif (a < b) {}\\n```'],
              ['行内 >', '修复 `a > b` 的比较'],
              ['围栏 >', '```js\\nif (a > b) {}\\n```'],
            ]) {
              const html = render(raw);
              assert.ok(!/&amp;(lt|gt|amp);/.test(html), `${label} 出现二次转义: ${html}`);
            }

            // 行内代码：单层转义，浏览器显示 a < b
            const inline = render('修复 `a < b` 的比较');
            assert.ok(inline.includes('a &lt; b'), inline);
            assert.ok(!inline.includes('&amp;lt;'), inline);
            assert.ok(inline.includes('<code>'), inline);

            // 围栏代码块：同上
            const fenced = render('```js\\nif (a < b) {}\\n```');
            assert.ok(fenced.includes('if (a &lt; b)'), fenced);
            assert.ok(!fenced.includes('&amp;lt;'), fenced);
            assert.ok(fenced.includes('<pre><code'), fenced);
            """
        )
    )


@requires_node
def test_marked_render_never_emits_executable_markup():
    """参数化安全用例：既没有二次转义，也不出现可执行标签 / 事件属性。"""
    _assert_ok(
        _node_assert(
            MARKED_SANDBOX
            + """
            const cases = [
              ['行内 <', '修复 `a < b` 的比较'],
              ['行内 >', '修复 `a > b` 的比较'],
              ['围栏 <', '```js\\nif (a < b) {}\\n```'],
              ['围栏 >', '```js\\nif (a > b) {}\\n```'],
              ['裸比较', 'x <= y 与 x >= y'],
              ['占位符', '把 `<placeholder>` 换成实际值'],
              ['HTML 标签', '<b>粗体</b> 文本'],
              ['裸尖括号开头', '< b 开头'],
              ['混入 script', 'x <script> y'],
              ['以 div 开头', '<div class="x">正文</div>'],
              ['事件属性', '<img src=x onerror=alert(1)>'],
              ['数字小于', '100<200 数字比较'],
              ['无空格小于', 'a<b 无空格'],
            ];
            for (const [label, raw] of cases) {
              const cleaned = sanitizeNotesMarkdown(raw);
              const html = render(raw);
              assert.ok(!/&amp;(lt|gt|amp);/.test(html), `${label} 二次转义: ${html}`);
              assert.ok(!/<script|onerror=|onload=|onclick=|ontoggle=/i.test(html), `${label} 出现可执行标记: ${html}`);
              // 净化结果绝不能命中 dom.js 的两条直插判定
              assert.ok(!looksLikeTrustedHtml(cleaned), `${label} 命中 looksLikeTrustedHtml: ${JSON.stringify(cleaned)}`);
              assert.ok(!htmlFragment(cleaned), `${label} 命中 htmlFragmentRegex: ${JSON.stringify(cleaned)}`);
            }
            """
        )
    )


@requires_node
def test_angle_bracket_text_stays_readable_after_render():
    """字面尖括号文本必须可读：`<3`、`< b` 不能被转成 `&amp;lt;`。

    注意断言同时落在**净化输出**上：marked 在普通段落里会保留既有实体，
    所以只看渲染 HTML 时这条用例可能假绿——真正的病根在 `escapeHtml`。
    """
    _assert_ok(
        _node_assert(
            MARKED_SANDBOX
            + """
            for (const [raw, expected] of [
              ['<3 爱心', '&lt;3 爱心'],
              ['< b 开头', '&lt; b 开头'],
              ['100<200', '100&lt;200'],
            ]) {
              const cleaned = sanitizeNotesMarkdown(raw);
              // 病根断言：字面文本不该被转义成实体
              assert.ok(!cleaned.includes('&lt;'), `净化后不应含 &lt;: ${JSON.stringify(cleaned)}`);
              const html = render(raw);
              assert.ok(!html.includes('&amp;lt;'), `${raw} 二次转义: ${html}`);
              assert.ok(html.includes(expected), `${raw} 期望含 ${expected}，实际 ${html}`);
            }
            """
        )
    )


# ------------------------------------------------------------------ 代码段保全

# 插件 CHANGELOG 里到处是这种行内代码：`<key>` / `<id>` / `<card_id>` 是**占位符
# 约定**，不是 HTML。净化器若把它们当标签删掉，接口说明就读不通了。
PRESERVED_INLINE_CODE = [
    '`resource::<key>::<文件名>`',
    '`global::<相对路径>`',
    '`embedded::<card_id>`',
    '`/jobs/<id>/apply`',
    '`<select class="x">`',
]


@requires_node
def test_inline_code_placeholders_survive_sanitization():
    """回归：`<key>` / `<id>` 这类占位符曾被当标签整段删掉。

    marked 渲染代码段时会自己转义 HTML，所以代码段里的 `<script>` 只是惰性文本，
    净化器不该插手。保护范围就是围栏 + 行内代码。
    """
    _assert_ok(
        _node_assert(
            """
            const cases = [
              '`resource::<key>::<文件名>`',
              '`global::<相对路径>`',
              '`embedded::<card_id>`',
              '`/jobs/<id>/apply`',
              '`<select class="x">`',
            ];
            for (const raw of cases) {
              const cleaned = sanitizeNotesMarkdown(raw);
              assert.equal(cleaned, raw, `行内代码被改动: ${JSON.stringify({ raw, cleaned })}`);
            }
            """
        )
    )


@requires_node
def test_real_changelog_excerpt_is_preserved():
    """真实 0.4.0→0.4.1 说明片段：占位符与接口路径必须完整保留。"""
    _assert_ok(
        _node_assert(
            """
            const raw = [
              '- **根因是 id 对不上**：宿主选中集里存的是世界书列表项 id',
              '  （`global::<相对路径>` / `resource::<key>::<文件名>` / `embedded::<card_id>`）。',
              '- `DELETE /jobs/<run_id>`（复用已实现但零调用的 `forget_run`）。',
            ].join('\\n');

            const cleaned = sanitizeNotesMarkdown(raw);
            assert.equal(cleaned, raw, `真实片段被改动:\\n${cleaned}`);

            for (const fragment of [
              'resource::<key>::<文件名>',
              '/jobs/<run_id>',
              'global::<相对路径>',
              'embedded::<card_id>',
              'forget_run',
            ]) {
              assert.ok(cleaned.includes(fragment), `丢失片段 ${fragment}`);
            }
            """
        )
    )


@requires_node
def test_code_fence_content_survives_sanitization():
    """围栏代码块同样要保全（含演示 HTML 的说明）。"""
    _assert_ok(
        _node_assert(
            """
            const cases = [
              '```js\\nif (a < b) {}\\n```',
              '```\\n<script>alert(1)</script>\\n```',
              '```html\\n<div class="x">y</div>\\n```',
              '~~~\\n<b>tilde fence</b>\\n~~~',
            ];
            for (const raw of cases) {
              const cleaned = sanitizeNotesMarkdown(raw);
              assert.equal(cleaned, raw, `围栏被改动: ${JSON.stringify({ raw, cleaned })}`);
            }
            """
        )
    )


@requires_node
def test_mixed_inline_code_and_prose_html():
    """混排：行内代码原样，代码外的标签仍被剥掉。"""
    _assert_ok(
        _node_assert(
            MARKED_SANDBOX
            + """
            const raw = '`<b>code</b>` 与 <b>html</b> 混排';
            const cleaned = sanitizeNotesMarkdown(raw);
            // 行内代码原样保留
            assert.ok(cleaned.includes('`<b>code</b>`'), cleaned);
            // 代码外的 <b> 被剥（只剩内容）
            assert.ok(cleaned.includes('与 html 混排'), cleaned);
            assert.ok(!/与 <b>html<\\/b>/.test(cleaned), cleaned);

            const html = renderNotesHtml(cleaned);
            assert.ok(html.includes('<code>&lt;b&gt;code&lt;/b&gt;</code>'), html);
            assert.ok(!/<b>html<\\/b>/.test(html), html);
            """
        )
    )


# ------------------------------------------------------------------ 安全：渲染路由

# 这些输入在「sanitize 输出」里仍带裸 `<script`（代码段是惰性文本，故意保留），
# 所以**绝不能**直接喂 updateShadowContent；必须先经 renderNotesHtml。
DANGEROUS_ROUTE_INPUTS = [
    '```\\n<script>alert(1)</script>\\n```',
    '`<script>alert(1)</script>`',
    '```\\n<div>x</div><style>y</style>\\n```',
    '```\\n<!DOCTYPE html><html><body>x</body></html>\\n```',
    '~~~\\n<script>alert(1)</script>\\n~~~',
]


@requires_node
def test_rendered_html_never_routes_to_isolated_iframe():
    """安全回归：交给 `updateShadowContent()` 的字符串不得命中 dom.js 的载荷嗅探。

    `dom.js:738-743` 嗅到裸 `<script` / `<html` / `<!DOCTYPE` 就把原文当 HTML
    载荷交给 `renderIsolatedHtml()`，而那个 iframe（`renderRuntime.js:158-163`）
    没有 `sandbox`、blob URL 与宿主同源 —— 脚本会真的执行。
    `renderNotesHtml()` 先经 marked，代码段变成 `&lt;script&gt;`，嗅探看不到裸标签。
    """
    _assert_ok(
        _node_assert(
            MARKED_SANDBOX
            + """
            const cases = [
              ['围栏 script', '```\\n<script>alert(1)</script>\\n```'],
              ['行内 script', '`<script>alert(1)</script>`'],
              ['围栏 div+style', '```\\n<div>x</div><style>y</style>\\n```'],
              ['围栏 doctype', '```\\n<!DOCTYPE html><html><body>x</body></html>\\n```'],
              ['波浪围栏 script', '~~~\\n<script>alert(1)</script>\\n~~~'],
            ];

            for (const [label, raw] of cases) {
              const sanitized = sanitizeNotesMarkdown(raw);
              const html = renderNotesHtml(sanitized);

              // 前提：sanitize 输出确实会命中嗅探（这是代码段保全的代价）。
              // 不能只查 `<script` 子串——`<div>`+`<style>` 走的是代码块分支。
              assert.notEqual(domPayloadRoute(sanitized), '', `${label} 前提不成立: ${sanitized}`);

              // 断言：渲染后的字符串永远不命中嗅探
              assert.ok(!html.includes('<script'), `${label} 渲染后仍含 <script: ${html}`);
              assert.ok(!html.includes('<html'), `${label} 渲染后仍含 <html: ${html}`);
              assert.ok(!html.includes('<!DOCTYPE'), `${label} 渲染后仍含 <!DOCTYPE: ${html}`);
              assert.equal(domPayloadRoute(html), '', `${label} 仍会路由到 iframe: ${html}`);
              assert.ok(!htmlFragment(html), `${label} 命中 htmlFragmentRegex: ${html}`);

              // 代码内容对用户仍然完整可见（转义成惰性文本）
              assert.ok(/&lt;script&gt;|&lt;div&gt;|&lt;!DOCTYPE/.test(html), `${label} 代码内容丢失: ${html}`);
            }
            """
        )
    )


@requires_node
def test_sanitize_output_alone_is_unsafe_to_feed_directly():
    """把「为什么必须先 marked」钉成断言，防止将来有人把模板改回直喂。"""
    _assert_ok(
        _node_assert(
            MARKED_SANDBOX
            + """
            const raw = '```\\n<script>alert(1)</script>\\n```';
            const sanitized = sanitizeNotesMarkdown(raw);

            // sanitize 输出（代码段保全的直接结果）会命中嗅探 —— 危险
            assert.notEqual(domPayloadRoute(sanitized), '', '前提不成立：sanitize 输出应命中嗅探');

            // 经 renderNotesHtml 后不再命中 —— 安全
            assert.equal(domPayloadRoute(renderNotesHtml(sanitized)), '', '渲染后仍危险');
            """
        )
    )


@requires_node
def test_render_falls_back_to_escaping_without_marked():
    """`marked` 不可用时必须退回纯转义，绝不能把含 `<script` 的原文交出去。"""
    _assert_ok(
        _node_assert(
            """
            const original = globalThis.marked;
            try {
              delete globalThis.marked;
              const raw = '```\\n<script>alert(1)</script>\\n```';
              const sanitized = sanitizeNotesMarkdown(raw);
              const html = renderNotesHtml(sanitized);

              assert.ok(!html.includes('<script'), `回退路径仍含 <script: ${html}`);
              assert.ok(!html.includes('<html'), html);
              assert.ok(!html.includes('<!DOCTYPE'), html);
              assert.ok(html.includes('alert(1)'), `内容不该被整体丢弃: ${html}`);
            } finally {
              globalThis.marked = original;
            }
            """
        )
    )


# ------------------------------------------------------------------ 其它纯函数


@requires_node
def test_notes_source_label_covers_three_states():
    _assert_ok(
        _node_assert(
            """
            assert.equal(notesSourceLabel('release'), '来自 GitHub Release');
            assert.equal(notesSourceLabel('changelog'), '来自插件 CHANGELOG');
            assert.equal(notesSourceLabel(''), '');
            assert.equal(notesSourceLabel('other'), '');
            for (const weird of [null, undefined, 0, {}, []]) {
              assert.equal(notesSourceLabel(weird), '');
            }
            """
        )
    )


@requires_node
def test_update_summary_tolerates_missing_fields():
    """缺字段 / 非对象输入都必须给出结构完整的兜底结果，不能抛。"""
    _assert_ok(
        _node_assert(
            """
            for (const weird of [undefined, null, {}, { id: 'x' }, 0, 'str', []]) {
              const summary = updateSummary(weird);
              assert.doesNotThrow(() => JSON.stringify(summary));
              for (const key of ['name', 'id', 'from', 'to', 'notes', 'sourceLabel']) {
                assert.equal(typeof summary[key], 'string', `${key} 不是字符串`);
              }
              for (const key of ['truncated', 'hasNotes', 'notesFetched']) {
                assert.equal(typeof summary[key], 'boolean', `${key} 不是布尔`);
              }
            }

            const full = updateSummary({
              id: 'stm-demo',
              name: '示例插件',
              installed: '0.3.0',
              available: '0.4.1',
              release_notes: '## 修复\\n- 崩溃',
              release_notes_source: 'release',
              release_notes_truncated: true,
            });
            assert.equal(full.from, '0.3.0');
            assert.equal(full.to, '0.4.1');
            assert.equal(full.sourceLabel, '来自 GitHub Release');
            assert.equal(full.truncated, true);
            assert.equal(full.hasNotes, true);
            assert.ok(full.notes.includes('## 修复'), full.notes);

            // catalog 条目只有 installed_version / version，也要认
            const catalogSide = updateSummary({
              id: 'stm-demo',
              installed_version: '0.3.0',
              version: '0.4.0',
            });
            assert.equal(catalogSide.from, '0.3.0');
            assert.equal(catalogSide.to, '0.4.0');
            assert.equal(catalogSide.hasNotes, false);
            assert.equal(catalogSide.truncated, false);
            """
        )
    )


@requires_node
def test_summary_distinguishes_not_fetched_from_really_empty():
    """核心诚实性契约：「没去取说明」不能被说成「插件没写说明」。

    目录入口（catalog）不请求 check_updates，条目里根本没有 `release_notes`；
    check_updates 入口（installed）是真的查过。两者都 `hasNotes === false`，
    但 `notesFetched` 必须不同，模板据此给两句不同的文案。
    """
    _assert_ok(
        _node_assert(
            """
            // ① 目录入口：只有 catalog 形状的字段，没查过
            const catalog = updateSummary(
              { id: 'stm-demo', installed_version: '0.3.0', version: '0.4.0' },
              { origin: 'catalog' },
            );
            assert.equal(catalog.hasNotes, false);
            assert.equal(catalog.notesFetched, false, 'catalog 入口不该声称查过说明');
            assert.equal(catalog.notes, '');
            assert.equal(catalog.source, '');
            assert.equal(catalog.sourceLabel, '');
            assert.equal(catalog.truncated, false);

            // ② 检查更新入口：查过，但发布方确实没写
            const checked = updateSummary(
              {
                id: 'stm-demo',
                name: '示例插件',
                installed: '0.3.0',
                available: '0.4.0',
                release_notes: '',
                release_notes_source: '',
                release_notes_truncated: false,
              },
              { origin: 'update-check' },
            );
            assert.equal(checked.hasNotes, false);
            assert.equal(checked.notesFetched, true, 'update-check 入口必须标记为已查');
            assert.equal(checked.sourceLabel, '');

            // 两种「无说明」在结构上必须可区分（模板文案分支依赖它）
            assert.notEqual(catalog.notesFetched, checked.notesFetched);

            // ③ 防御：目录条目即使意外带上了 notes 字段，catalog 入口也不认
            //    （否则会显示一份来源不明、也没标记截断的正文）
            const dirtyCatalog = updateSummary(
              {
                id: 'stm-demo',
                installed_version: '0.3.0',
                version: '0.4.0',
                release_notes: '## 不该显示',
                release_notes_source: 'release',
                release_notes_truncated: true,
              },
              { origin: 'catalog' },
            );
            assert.equal(dirtyCatalog.notesFetched, false);
            assert.equal(dirtyCatalog.hasNotes, false);
            assert.equal(dirtyCatalog.sourceLabel, '');
            assert.equal(dirtyCatalog.truncated, false);
            """
        )
    )


@requires_node
def test_component_marks_catalog_mode_as_not_fetched():
    """组件接线：`openUpdateConfirm(entry, 'catalog')` 必须落到「没去取」分支。"""
    _assert_ok(
        run_node(
            """
            import assert from 'node:assert/strict';
            import pluginManager from './static/js/components/pluginManager.js';

            const vm = pluginManager();

            vm.openUpdateConfirm(
              { id: 'stm-demo', name: '示例插件', installed_version: '0.3.0', version: '0.4.0' },
              'catalog',
            );
            assert.equal(vm.updateConfirm.mode, 'catalog');
            assert.equal(vm.updateConfirm.notesFetched, false);
            assert.equal(vm.updateConfirm.hasNotes, false);
            assert.equal(vm.updateConfirm.sourceLabel, '');
            vm.cancelUpdateConfirm();

            vm.openUpdateConfirm(
              {
                id: 'stm-demo',
                name: '示例插件',
                installed: '0.3.0',
                available: '0.4.0',
                release_notes: '',
              },
              'installed',
            );
            assert.equal(vm.updateConfirm.mode, 'installed');
            assert.equal(vm.updateConfirm.notesFetched, true);
            assert.equal(vm.updateConfirm.hasNotes, false);
            vm.cancelUpdateConfirm();

            console.log('ORIGIN WIRING OK');
            """
        )
    )


@requires_node
def test_dialog_intro_lines_are_plain_text():
    _assert_ok(
        _node_assert(
            """
            const lines = dialogIntroLines(updateSummary({
              id: 'stm-demo',
              name: '示例插件',
              installed: '0.3.0',
              available: '0.4.1',
            }));
            assert.ok(Array.isArray(lines) && lines.length >= 1);
            for (const line of lines) assert.equal(typeof line, 'string');
            assert.ok(lines[0].includes('示例插件'), lines[0]);
            assert.ok(lines[0].includes('0.3.0') && lines[0].includes('0.4.1'), lines[0]);
            assert.ok(lines.some((line) => line.includes('重启应用')), JSON.stringify(lines));
            // 纯文本：不含任何 HTML 标签
            for (const line of lines) assert.ok(!/<[a-zA-Z/!]/.test(line), line);

            assert.doesNotThrow(() => dialogIntroLines(undefined));
            assert.doesNotThrow(() => dialogIntroLines(null));
            """
        )
    )


# ------------------------------------------------------------------ 组件状态机


@requires_node
def test_component_dialog_state_machine():
    """直接实例化组件对象跑一遍弹层状态机（不依赖 DOM / 后端）。"""
    script = """
        import assert from 'node:assert/strict';
        import pluginManager from './static/js/components/pluginManager.js';

        const vm = pluginManager();
        assert.equal(vm.updateConfirm, null);
        assert.equal(typeof vm.updateShadowContent, 'function', 'updateShadowContent 未挂载');

        // 已安装页签入口（带 release_notes）
        vm.openUpdateConfirm({
          id: 'stm-demo',
          name: '示例插件',
          installed: '0.3.0',
          available: '0.4.1',
          release_notes: '## 0.4.1\\n- 修复崩溃\\n<img src=x onerror=alert(1)>',
          release_notes_source: 'changelog',
          release_notes_truncated: true,
        }, 'installed');

        assert.equal(vm.updateConfirm.mode, 'installed');
        assert.equal(vm.updateConfirm.sourceLabel, '来自插件 CHANGELOG');
        assert.equal(vm.updateConfirm.truncated, true);
        assert.equal(vm.updateConfirm.hasNotes, true);
        assert.ok(vm.updateConfirm.introLines[0].includes('0.3.0'), vm.updateConfirm.introLines[0]);

        const notes = vm.updateConfirmNotes();
        assert.ok(!/onerror|alert\\(1\\)|<img/i.test(notes), notes);
        assert.ok(notes.includes('## 0.4.1') && notes.includes('- 修复崩溃'), notes);

        assert.equal(vm.updateConfirmBusy(), false);
        vm.busyAction = 'update:stm-demo';
        assert.equal(vm.updateConfirmBusy(), true);
        vm.busyAction = '';

        vm.cancelUpdateConfirm();
        assert.equal(vm.updateConfirm, null);
        assert.equal(vm.updateConfirmNotes(), '');
        // 弹层关闭后不能因 null.id 抛错（模板 binding 会继续求值）
        assert.equal(vm.updateConfirmBusy(), false);

        // 目录入口：没有 notes 字段 → 无说明分支
        vm.openUpdateConfirm({
          id: 'stm-demo',
          name: '示例插件',
          installed_version: '0.2.0',
          version: '0.3.0',
        }, 'catalog');
        assert.equal(vm.updateConfirm.mode, 'catalog');
        assert.equal(vm.updateConfirm.hasNotes, false);
        assert.equal(vm.updateConfirm.sourceLabel, '');
        assert.equal(vm.updateConfirm.from, '0.2.0');
        assert.equal(vm.updateConfirm.to, '0.3.0');
        vm.cancelUpdateConfirm();

        // 缺 id 不打开（与既有守卫一致）
        assert.equal(vm.openUpdateConfirm({ name: '无名' }, 'installed'), undefined);
        assert.equal(vm.updateConfirm, null);

        console.log('COMPONENT SMOKE OK');
        """
    result = run_node(script)
    _assert_ok(result)
    assert 'COMPONENT SMOKE OK' in result.stdout, result.stdout


# ------------------------------------------------------------------ 静态契约

def _method_body(source: str, signature: str) -> str:
    """取一个对象方法的方法体（花括号配平），找不到直接失败。"""
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f'方法体没有闭合: {signature}')


def test_apply_update_no_longer_calls_window_confirm():
    source = read_source(MANAGER_JS)
    body = _method_body(source, 'async applyUpdate(update) {')

    assert 'window.confirm' not in body, 'applyUpdate 仍在用零内容的 window.confirm'
    assert 'openUpdateConfirm(' in body, 'applyUpdate 必须改为打开更新确认弹层'
    # 既有前置拦截保留
    assert 'requiresAppUpdate(update)' in body
    assert 'busyAction' in body


def test_update_catalog_item_no_longer_calls_window_confirm():
    source = read_source(MANAGER_JS)
    body = _method_body(source, 'async updateCatalogItem(entry) {')

    assert 'window.confirm' not in body, 'updateCatalogItem 仍在用 window.confirm'
    assert 'openUpdateConfirm(' in body
    assert 'requiresAppUpdate(entry)' in body


def test_confirm_flow_methods_exist_and_reuse_update_endpoint():
    source = read_source(MANAGER_JS)
    body = _method_body(source, 'async confirmUpdateConfirm() {')

    assert 'updatePluginFromCatalog(' in body
    assert 'cancelUpdateConfirm()' in body
    # 两个入口各自沿用原有的刷新行为
    assert 'this.loadPlugins()' in body
    assert 'this.loadCatalog(true)' in body
    # 取消只清状态，不发请求
    cancel = _method_body(source, 'cancelUpdateConfirm() {')
    assert 'updatePluginFromCatalog' not in cancel
    assert 'updateConfirm = null' in cancel


def test_manager_exposes_sanitized_notes_through_a_helper():
    source = read_source(MANAGER_JS)

    assert 'updateConfirmNotes()' in source
    assert 'sanitizeNotesMarkdown' in source
    assert 'pluginReleaseNotes.js' in source
    # 渲染入口必须是「先 marked 再交给 shadow 渲染」
    assert 'updateConfirmHtml()' in source
    assert 'renderNotesHtml' in source
    # 后端三个字段的消费点在纯函数模块里（updateSummary 负责兜底）
    assert 'updateSummary(' in source
    assert 'release_notes' in read_source(NOTES_JS)
    assert 'release_notes_source' in read_source(NOTES_JS)
    assert 'release_notes_truncated' in read_source(NOTES_JS)
    # 两个入口共用同一个弹层，各自带自己的 mode
    assert 'openUpdateConfirm(update, "installed")' in source
    assert 'openUpdateConfirm(entry, "catalog")' in source


def test_render_notes_html_is_the_only_render_path():
    """`renderNotesHtml()` 必须真的经 marked，且带 marked 缺失时的安全回退。"""
    module = read_source(NOTES_JS)

    assert 'export function renderNotesHtml(' in module
    assert 'marked.parse(' in module
    # marked 缺失 / 抛错 / 输出异常时退回转义
    assert 'escapeHtml(source)' in module
    # 自证：模块注释里写清了这条是安全边界（防止后人「简化」掉）
    assert 'dom.js:738-743' in module
    assert 'sandbox' in module


def test_manager_does_not_inject_notes_with_inner_html():
    """净化后的备注只走 `updateShadowContent`，不新增 `innerHTML` 直插。"""
    source = read_source(MANAGER_JS)
    template = read_source(MANAGER_TMPL)

    for snippet in ('x-html="updateConfirm', 'innerHTML = this.updateConfirm', 'innerHTML = updateConfirm'):
        assert snippet not in source, snippet
        assert snippet not in template, snippet
    assert 'updateShadowContent' in source
    # 组件上必须真的挂了 render 函数（模板里 x-effect 才调得到）
    assert re.search(r'^\s+updateShadowContent,\s*$', source, re.MULTILINE), '组件未挂载 updateShadowContent'


def test_template_renders_update_confirm_dialog():
    template = read_source(MANAGER_TMPL)

    assert 'x-teleport="body"' in template
    assert 'updateConfirm' in template
    assert 'cancelUpdateConfirm()' in template
    assert 'confirmUpdateConfirm()' in template
    assert 'openUpdateConfirm' in read_source(MANAGER_JS)
    # 层级别必须高于设置弹窗（--z-modal-std 1100）
    assert 'z-modal-popover' in template
    # 语义化确认框
    assert 'role="alertdialog"' in template
    assert 'aria-modal' in template
    assert 'aria-labelledby' in template
    assert 'aria-describedby' in template
    # 渲染区走 shadow 渲染并带滚动约束
    assert 'updateShadowContent($el' in template
    assert 'scroll: true' in template
    # 必须传渲染后的 HTML，不能直喂 sanitized markdown（否则裸 <script 会
    # 命中 dom.js 的载荷嗅探 → 无 sandbox 同源 iframe → XSS）
    assert 'updateConfirmHtml()' in template
    assert 'updateShadowContent($el, updateConfirm ? updateConfirmHtml() : null' in template
    assert 'updateShadowContent($el, updateConfirm ? updateConfirmNotes() : null' not in template
    # 来源徽标 / 无说明兜底 / 截断提示都在
    assert 'updateConfirm.sourceLabel' in template
    assert 'updateConfirm.hasNotes' in template
    assert 'updateConfirm.truncated' in template
    # 按钮联动 busyAction（写成方法：弹层关闭后内联式会取 null.id 抛错）
    assert 'updateConfirmBusy()' in template
    assert 'updateConfirmBusy()' in read_source(MANAGER_JS)


def test_template_uses_only_existing_sprite_icons():
    """新增图标必须来自 `static/icons/ui.svg`（与 test_plugin_frontend_assets 同源）。"""
    sprite = read_source('static/icons/ui.svg')
    available = set(re.findall(r'id="icon-([a-z0-9-]+)"', sprite))
    used = re.findall(r"\{\{\s*icon\(\s*'([a-z0-9-]+)'", read_source(MANAGER_TMPL))
    missing = sorted({name for name in used if name not in available})
    assert missing == [], f'模板引用了不存在的图标: {missing}'


# ------------------------------------------------------------ 无说明文案的诚实性


def test_empty_notes_copy_does_not_claim_unverified_facts():
    """回归：目录入口没取说明，文案不能断言「Release 与 CHANGELOG 都为空」。

    `/api/plugins/catalog` 的条目里没有 `release_notes`，这条路径也没调
    `check_updates`。把「我们没查」写成「插件没写」，用户会以为作者偷懒。
    """
    template = read_source(MANAGER_TMPL)

    # 越界断言：曾经出现过的那句话，以及它的各种等价说法
    for forbidden in (
        'Release 正文与 CHANGELOG 都为空',
        'CHANGELOG 都为空',
        '没有提供更新说明（',
    ):
        assert forbidden not in template, f'兜底文案又在断言没验证过的事实: {forbidden}'


def test_empty_notes_copy_has_two_mode_specific_branches():
    """两种「无说明」必须给两句不同的文案，并按 `notesFetched` 分支渲染。"""
    template = read_source(MANAGER_TMPL)

    # 查过但确实为空
    assert '这个插件的发布方没有提供更新说明。' in template
    # 没去查：如实说明路径限制，并指出去哪儿能看到
    assert '从目录页更新时不获取更新说明' in template
    assert '「已安装」页签' in template and '检查更新' in template

    # 两条 x-show 分支都挂在同一个兜底容器类上，且条件互补
    branches = re.findall(
        r'x-show="([^"]*!updateConfirm\.hasNotes[^"]*)"',
        template,
    )
    assert len(branches) == 2, f'期望两条互补的无说明分支，实际 {branches}'
    joined = ' '.join(branches)
    assert 'notesFetched' in joined, '无说明分支没有区分「查过」与「没查过」'
    assert any('!updateConfirm.notesFetched' in branch for branch in branches)
    assert any(
        '!updateConfirm.notesFetched' not in branch and 'updateConfirm.notesFetched' in branch
        for branch in branches
    )


def test_catalog_mode_hides_source_badge_and_truncation_hint():
    """catalog 模式没有来源也没有截断信息：两者都不能出现。"""
    template = read_source(MANAGER_TMPL)

    # 徽标与截断提示都绑定在 summary 字段上（catalog 模式下恒为空 / false）
    badge = re.search(r'class="plugin-update-source-badge"[\s\S]{0,200}?x-show="([^"]+)"', template)
    assert badge is not None, '找不到来源徽标'
    assert 'sourceLabel' in badge.group(1)

    truncated = re.search(r'class="plugin-update-truncated" x-show="([^"]+)"', template)
    assert truncated is not None, '找不到截断提示'
    assert 'truncated' in truncated.group(1)

    # 后端结构保证：catalog 模式下这两个字段恒为空 / false（见 updateSummary）
    notes_module = read_source(NOTES_JS)
    assert 'notesFetched' in notes_module
    assert 'const notes = notesFetched ?' in notes_module
    assert 'const source = notesFetched ?' in notes_module
    assert 'truncated: notesFetched &&' in notes_module


def test_new_css_classes_are_actually_rendered():
    """写了样式没人用 = 死代码；这一层防止 CSS 与模板脱节。"""
    css = read_source(MANAGER_CSS)
    template = read_source(MANAGER_TMPL)

    defined = set(re.findall(r'\.(plugin-update-[a-z0-9-]+)', css))
    assert defined, 'CSS 里没有更新弹层样式'
    unused = sorted(name for name in defined if name not in template)
    assert unused == [], f'CSS 新增类未在模板中出现: {unused}'


def test_update_dialog_styles_use_semantic_tokens_only():
    css = read_source(MANAGER_CSS)
    # 只允许项目里已定义的语义 token（test_plugin_frontend_assets 会做全站交叉校验，
    # 这里额外挡掉 Tailwind 调色板与硬编码背景色）
    assert 'plugin-update-dialog' in css
    for pattern in (r'\bbg-(red|blue|green|gray|zinc|slate)-\d', r'\btext-(red|blue|green)-\d'):
        assert not re.search(pattern, css), pattern
