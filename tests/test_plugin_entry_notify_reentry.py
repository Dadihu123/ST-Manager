"""`contributions:changed` 广播的重入保护测试（S3 / 原 entries:notify-reentry 的 v3 版本）。

背景：插件常在自己的 `contributions:changed` 监听里调用 `api.contributions.update()`
（例如「处理中」→「完成」）。若每次 update 都同步再广播，就会栈溢出。注册表的约定：

- 同值写入不广播（`Object.is` 判等，打断最常见的自触发）；
- 广播期间发生的 update 记入 pending，当前一轮结束后最多再补一轮；
- 连续轮次以 `MAX_NOTIFY_ROUNDS` 封顶，超过后放弃并警告，而不是无限递归。
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REGISTRY_PATH = 'static/js/contributionRegistry.js'


def read_source(relative_path):
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
    reason='Node.js is required for contribution registry contract checks',
)

SHIM = r"""
const dispatched = [];
globalThis.__dispatched = dispatched;
globalThis.window = {
  listeners: new Map(),
  addEventListener(name, fn) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(fn);
  },
  removeEventListener(name, fn) { this.listeners.get(name)?.delete(fn); },
  dispatchEvent(event) {
    dispatched.push(event);
    for (const fn of [...(this.listeners.get(event.type) || [])]) fn(event);
  },
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init) { this.type = type; this.detail = init && init.detail; }
};
globalThis.window.CustomEvent = globalThis.CustomEvent;
globalThis.__store = {
  currentMode: 'cards',
  deviceType: 'desktop',
  viewState: { selectedIds: [] },
  indexStatus: { state: 'idle' },
};
globalThis.window.Alpine = {
  store: () => globalThis.__store,
  effect: () => () => {},
  reactive: (value) => value,
};

globalThis.__makePlugins = () => [
  {
    id: 'demo',
    enabled: true,
    manifest: {
      contributions: {
        menus: [
          { id: 'node-a', placement: 'dock', type: 'item', label: 'A',
            action: { type: 'url', url: 'https://example.com/a' } },
          { id: 'node-b', placement: 'dock', type: 'item', label: 'B',
            action: { type: 'url', url: 'https://example.com/b' } },
        ],
      },
    },
  },
];
"""


def run_script(body: str) -> subprocess.CompletedProcess:
    return run_node(SHIM + textwrap.dedent(body))


def run_json(body: str) -> dict:
    result = run_script(body)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = [line for line in (result.stdout or '').strip().splitlines() if line.strip()]
    assert lines, result.stderr or result.stdout
    return json.loads(lines[-1])


# ------------------------------------------------------------------ 静态契约


def test_registry_declares_reentry_guard():
    source = read_source(REGISTRY_PATH)

    assert 'MAX_NOTIFY_ROUNDS' in source
    assert 'const MAX_NOTIFY_ROUNDS = 5' in source
    assert '_notifying' in source
    assert '_notifyPending' in source
    assert 'new CustomEvent("contributions:changed"' in source


# ------------------------------------------------------------------ 行为


@requires_node
def test_noop_update_does_not_broadcast():
    payload = run_json(
        """
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        ContributionRegistry.setPlugins(globalThis.__makePlugins());
        globalThis.__dispatched.length = 0;

        const node = ContributionRegistry.get('demo', 'node-b');
        const label = node.label;
        ContributionRegistry.update('demo', 'node-b', { label });

        process.stdout.write(JSON.stringify({
          events: globalThis.__dispatched.filter(
            (event) => event.type === 'contributions:changed'
          ).length,
        }));
        """
    )
    assert payload['events'] == 0


@requires_node
def test_update_from_listener_does_not_infinitely_recurse():
    payload = run_json(
        """
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        ContributionRegistry.setPlugins(globalThis.__makePlugins());
        globalThis.__dispatched.length = 0;

        let events = 0;
        let depth = 0;
        let maxDepth = 0;
        let pendingUpdates = 0;

        window.addEventListener('contributions:changed', () => {
          events += 1;
          depth += 1;
          maxDepth = Math.max(maxDepth, depth);
          // 典型的插件用法：收到变更后同步改自己的节点（同值 → 不广播）
          const node = ContributionRegistry.get('demo', 'node-a');
          if (node && node.label !== 'A-updated') {
            pendingUpdates += 1;
            ContributionRegistry.update('demo', 'node-a', { label: 'A-updated' });
          }
          depth -= 1;
        });

        ContributionRegistry.update('demo', 'node-b', { badge: 1 });
        ContributionRegistry.update('demo', 'node-b', { badge: 2 });

        process.stdout.write(JSON.stringify({
          events, maxDepth, pendingUpdates,
          label: ContributionRegistry.get('demo', 'node-a').label,
          badge: ContributionRegistry.get('demo', 'node-b').badge,
        }));
        """
    )
    # 两次显式 update 各广播一次；监听内的 label 更新是真实变化，但被记为 pending
    # 在**当前一轮之后**补发一轮（所以共 3 次），而不是在监听里套娃。
    assert payload['events'] == 3
    assert payload['maxDepth'] == 1, '监听回调里同步 update 不得套娃递归'
    assert payload['pendingUpdates'] == 1
    assert payload['label'] == 'A-updated'
    assert payload['badge'] == 2


@requires_node
def test_always_changing_listener_is_capped_by_max_rounds():
    payload = run_json(
        """
        import { ContributionRegistry, MAX_NOTIFY_ROUNDS } from './static/js/contributionRegistry.js';

        ContributionRegistry.setPlugins(globalThis.__makePlugins());
        globalThis.__dispatched.length = 0;

        let events = 0;
        window.addEventListener('contributions:changed', () => {
          events += 1;
          // 每次监听都写入一个必然变化的值：触发 pending → 下一轮，直到轮次封顶
          ContributionRegistry.update('demo', 'node-b', { progress: events / 100 });
        });

        ContributionRegistry.update('demo', 'node-b', { progress: 0.01 });

        process.stdout.write(JSON.stringify({
          events,
          maxRounds: MAX_NOTIFY_ROUNDS,
          // 封顶后仍能继续接受外部 update（状态没被锁死）
          after: ContributionRegistry.update('demo', 'node-b', { progress: 0.99 }),
        }));
        """
    )
    assert payload['maxRounds'] == 5
    # 初始 1 轮 + 最多 5 轮补发，且不能无限增长
    assert 1 <= payload['events'] <= 6
    assert payload['after'] is True


@requires_node
def test_removed_node_ignores_late_updates():
    payload = run_json(
        """
        import { ContributionRegistry } from './static/js/contributionRegistry.js';

        ContributionRegistry.setPlugins(globalThis.__makePlugins());
        const removed = ContributionRegistry.remove('demo', 'node-a');
        const updateAfterRemove = ContributionRegistry.update('demo', 'node-a', { label: 'X' });
        process.stdout.write(JSON.stringify({ removed, updateAfterRemove }));
        """
    )
    assert payload['removed'] is True
    assert payload['updateAfterRemove'] is False
