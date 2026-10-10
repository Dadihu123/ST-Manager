"""`entries:changed` 重入安全（回归：栈溢出）。

背景：插件按宿主文档推荐的模式写运行期状态——订阅 `entries:changed`，在回调里
`api.entries.setStatus(...)` 重放期望状态（因为宿主 `loadAll()` 先 activate、
后 setPlugins，activate 期间写入会静默失败）。

若写入器无条件广播，就形成

    setStatus → notifyChange → 监听器 → setStatus → …

的无限递归，栈溢出并让整个前端 JS 崩掉。用户实测报错栈：

    notifyChange (entryRegistry:761)
    ← setStatus (entryRegistry:571)
    ← setStatus (pluginHost:459)
    ← apply (plugin.js:36)
    ← wrapped (pluginHost:321)
    ← notifyChange (entryRegistry:761)

这里既做源码契约断言，也在 node 可用时**真实执行**注册表验证重入行为。
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REGISTRY_JS = os.path.join(PROJECT_ROOT, 'static', 'js', 'entryRegistry.js')


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


# ------------------------------------------------------------------ 源码契约


def test_runtime_state_writers_detect_no_op_writes():
    """运行期写入器必须做变更检测：同值不广播。

    这是打断递归的根本手段——重放写的通常就是同一个值，那本来就是空操作。
    """
    source = read_source('static/js/entryRegistry.js')

    start = source.index('  setBadge(pluginId, entryId, value) {')
    end = source.index('  // ------------------------------------------------------------ 查询')
    block = source[start:end]

    for method in ('setBadge', 'setProgress', 'setStatus', 'setBusy'):
        assert f'{method}(pluginId, entryId' in block, f'{method} 应在运行期状态区'

    # 每个写入器都要有「相同就 return」的早退
    assert block.count('return true;') >= 4, '四个写入器都应有同值早退'
    assert 'if (entry.status === next) return true;' in block
    assert 'if (entry.busy === next) return true;' in block
    assert 'if (Object.is(entry.badge, next)) return true;' in block


def test_notify_change_has_reentry_guard():
    """`notifyChange` 必须有重入合并与轮数上限，不能直接递归派发。"""
    source = read_source('static/js/entryRegistry.js')

    assert 'MAX_NOTIFY_ROUNDS' in source
    assert 'this._notifying' in source
    assert 'this._notifyPending' in source

    start = source.index('  notifyChange() {')
    body = source[start:start + 1600]
    # 重入时只登记待补发，不再递归派发
    assert 'if (this._notifying) {' in body
    assert 'this._notifyPending = true;' in body
    assert 'return;' in body


def test_plugin_host_event_wrapper_matches_documented_shape():
    """宿主 `api.on` 把 DOM 事件拆成 detail 后交给插件（插件据此重放）。"""
    source = read_source('static/js/pluginHost.js')

    assert 'const wrapped = (domEvent) => handler(domEvent.detail);' in source


# ------------------------------------------------------------------ 真实执行

NODE = shutil.which('node')
requires_node = pytest.mark.skipif(NODE is None, reason='node 不可用')


def _run_registry(script_body: str):
    """在 node 里以最小 window 桩执行 entryRegistry，返回其打印的 JSON。"""
    script = f"""
const g = globalThis;
g.window = {{
  listeners: new Map(),
  addEventListener(name, fn) {{
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(fn);
  }},
  removeEventListener(name, fn) {{ this.listeners.get(name)?.delete(fn); }},
  dispatchEvent(event) {{
    for (const fn of [...(this.listeners.get(event.type) || [])]) fn(event);
  }},
  CustomEvent: class CustomEvent {{
    constructor(type, init) {{ this.type = type; this.detail = init?.detail; }}
  }},
}};
g.CustomEvent = g.window.CustomEvent;

const {{ default: EntryRegistry }} = await import('file:///{REGISTRY_JS.replace(os.sep, "/")}');
{script_body}
"""
    result = subprocess.run(
        [NODE, '--input-type=module', '-e', script],
        capture_output=True, text=True, encoding='utf-8', timeout=90,
    )
    if result.returncode != 0:
        pytest.fail(f'node 执行失败（可能是栈溢出）:\n{result.stderr[:1500]}')
    return json.loads(result.stdout)


@requires_node
def test_replay_does_not_recurse_infinitely():
    """回归：插件在 `entries:changed` 回调里重放状态，不得无限递归。"""
    out = _run_registry("""
const pluginId = 'stm-ai-assistant';
let applyCount = 0;
let status = '';

const api = {
  on(event, handler) {
    const wrapped = (e) => handler(e.detail);
    window.addEventListener(event, wrapped);
    return () => window.removeEventListener(event, wrapped);
  },
  entries: {
    setStatus: (id, s) => EntryRegistry.setStatus(pluginId, id, s),
  },
};

const apply = () => { applyCount += 1; if (status) api.entries.setStatus('workbench', status); };

status = 'ok';
apply();                                   // activate 期间：注册表空，静默失败
api.on('entries:changed', apply);          // 订阅重放

EntryRegistry.setPlugins([
  { id: pluginId, enabled: true, manifest: {
      entries: [{ id: 'workbench', kind: 'dock', label: 'AI 助手' }] } },
]);

process.stdout.write(JSON.stringify({
  applyCount,
  status: EntryRegistry.get(pluginId + ':workbench')?.status || null,
}));
""")

    assert out['status'] == 'ok', '重放必须让状态落地（功能不能被修坏）'
    assert out['applyCount'] < 10, f'重放次数应有限，实际 {out["applyCount"]}'


@requires_node
def test_same_value_writes_do_not_broadcast():
    """同值写入不广播；真实变更仍广播。"""
    out = _run_registry("""
const pluginId = 'p1';
EntryRegistry.setPlugins([
  { id: pluginId, enabled: true, manifest: {
      entries: [
        { id: 'dock', kind: 'dock', label: 'D' },
        { id: 'cmd', kind: 'command', label: 'C' },
      ] } },
]);

let events = 0;
window.addEventListener('entries:changed', () => { events += 1; });

const marks = {};
EntryRegistry.setStatus(pluginId, 'dock', 'error');
marks.afterFirstStatus = events;
EntryRegistry.setStatus(pluginId, 'dock', 'error');       // 同值
marks.afterSameStatus = events;
EntryRegistry.setBadge(pluginId, 'cmd', 3);
marks.afterBadge = events;
EntryRegistry.setBadge(pluginId, 'cmd', 3);               // 同值
marks.afterSameBadge = events;
EntryRegistry.setBusy(pluginId, 'dock', true);
marks.afterBusy = events;
EntryRegistry.setBusy(pluginId, 'dock', true);            // 同值
marks.afterSameBusy = events;
EntryRegistry.setProgress(pluginId, 'dock', { done: 1, total: 4 });
marks.afterProgress = events;
EntryRegistry.setProgress(pluginId, 'dock', { done: 1, total: 4 });  // 同值
marks.afterSameProgress = events;

process.stdout.write(JSON.stringify(marks));
""")

    assert out['afterFirstStatus'] == 1, 'status 变化应广播一次'
    assert out['afterSameStatus'] == 1, '同值 status 不应再广播'
    assert out['afterBadge'] == 2, 'badge 变化应广播'
    assert out['afterSameBadge'] == 2, '同值 badge 不应再广播'
    assert out['afterBusy'] == 3, 'busy 变化应广播'
    assert out['afterSameBusy'] == 3, '同值 busy 不应再广播'
    assert out['afterProgress'] == 4, 'progress 变化应广播'
    assert out['afterSameProgress'] == 4, '同值 progress 不应再广播'


@requires_node
def test_pathological_listener_is_capped_not_crashed():
    """病态插件（每轮回调都改不同值）应被轮数上限截断，而不是栈溢出。"""
    out = _run_registry("""
const pluginId = 'p1';
EntryRegistry.setPlugins([
  { id: pluginId, enabled: true, manifest: {
      entries: [{ id: 'dock', kind: 'dock', label: 'D' }] } },
]);

let rounds = 0;
window.addEventListener('entries:changed', () => {
  rounds += 1;
  EntryRegistry.setStatus(pluginId, 'dock', rounds % 2 === 0 ? 'warn' : 'error');
});

EntryRegistry.setStatus(pluginId, 'dock', 'ok');   // 触发递归链

process.stdout.write(JSON.stringify({ rounds, survived: true }));
""")

    assert out['survived'] is True
    assert out['rounds'] <= 12, f'轮数应被上限截断，实际 {out["rounds"]}'


@requires_node
def test_listener_exception_does_not_break_registry():
    """监听器抛错不应让注册表卡在「正在广播」状态（否则后续通知全丢）。"""
    out = _run_registry("""
const pluginId = 'p1';
EntryRegistry.setPlugins([
  { id: pluginId, enabled: true, manifest: {
      entries: [{ id: 'dock', kind: 'dock', label: 'D' }] } },
]);

const boom = () => { throw new Error('listener blew up'); };
window.addEventListener('entries:changed', boom);

// 宿主 dispatchEvent 里监听器抛错会向上冒泡——这里模拟「抛错后仍能用」
let threw = false;
try {
  EntryRegistry.setStatus(pluginId, 'dock', 'error');
} catch (error) {
  threw = true;
}

window.removeEventListener('entries:changed', boom);

let events = 0;
window.addEventListener('entries:changed', () => { events += 1; });
EntryRegistry.setStatus(pluginId, 'dock', 'warn');

process.stdout.write(JSON.stringify({
  threw,
  recoveredEvents: events,
  notifyingFlag: EntryRegistry._notifying,
}));
""")

    assert out['notifyingFlag'] is False, '抛错后 _notifying 必须复位'
    assert out['recoveredEvents'] >= 1, '抛错后注册表必须仍能广播'
