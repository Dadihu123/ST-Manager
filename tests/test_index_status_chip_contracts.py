"""后台索引升级的前端契约：进度文案 / 百分比 / 完成后自动刷新。

背景：索引重建从启动路径移到后台后，「正在初始化资源库」遮罩会很快消失，
用户只能从 header 的索引状态条得知进度。这里锁定三件事：
1. 构建中必须给出可读的阶段文案（不是笼统的「索引构建中」）；
2. 有 progress_total 时必须能算百分比和「已处理 / 总数」；
3. building → ready 的跃迁要刷新列表并提示完成。
"""

import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_header_script():
    node_script = textwrap.dedent(
        '''
        import { readFileSync } from 'node:fs';
        import vm from 'node:vm';

        const source = readFileSync('static/js/components/header.js', 'utf8');
        // header.js 是 ES module，但只导出默认工厂函数；这里截取函数体后用 vm
        // 执行，避免为了测试引入打包器。
        const start = source.indexOf('export default function header()');
        const body = source.slice(start).replace('export default function header()', 'function header()');
        const sandbox = {
          console,
          window: { addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, setTimeout() {}, clearTimeout() {} },
          CustomEvent: class {},
        };
        vm.createContext(sandbox);
        vm.runInContext(`${body}\\nthis.__header = header;`, sandbox);
        const factory = sandbox.__header;
        const instance = factory();

        const store = { global: { indexStatus: {}, settingsForm: {} } };
        Object.defineProperty(instance, '$store', { value: store, configurable: true });

        function labelFor(status) {
          store.global.indexStatus = status;
          return {
            label: instance.indexStatusLabel,
            percent: instance.indexStatusPercent,
            count: instance.indexStatusCountText,
          };
        }

        console.log(JSON.stringify({
          backfill: labelFor({
            state: 'building', scope: 'worldinfo', upgrade_active: true,
            worldinfo: { phase: 'backfill_embedded_worldinfo_metadata', progress_done: 25, progress_total: 200 },
          }),
          build: labelFor({
            state: 'building', scope: 'worldinfo',
            worldinfo: { phase: 'build_entities', progress_done: 150, progress_total: 200 },
          }),
          unknownTotal: labelFor({
            state: 'building', scope: 'cards',
            cards: { phase: 'prepare_generation', progress_done: 0, progress_total: 0 },
          }),
          // 升级线程刚起、scope 行仍是上一次的 ready：不能显示「已就绪」。
          staleReady: labelFor({
            state: 'building', scope: 'worldinfo', upgrade_active: true,
            worldinfo: { phase: 'ready', progress_done: 0, progress_total: 0 },
          }),
          idle: labelFor({ state: 'ready', scope: 'cards', cards: { phase: 'ready' } }),
          error: labelFor({ state: 'error', scope: 'cards', message: 'boom' }),
        }));
        '''
    )

    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    import json

    return json.loads(result.stdout.strip().splitlines()[-1])


def test_index_status_chip_reports_phase_percent_and_count():
    payload = _run_header_script()

    assert payload['backfill']['label'] == '正在扫描内嵌世界书'
    assert payload['backfill']['percent'] == 13
    assert payload['backfill']['count'] == '25 / 200'

    assert payload['build']['label'] == '正在重建世界书索引'
    assert payload['build']['percent'] == 75
    assert payload['build']['count'] == '150 / 200'

    # 总数未知时不能编造百分比，只显示阶段。
    assert payload['unknownTotal']['label'] == '准备重建角色卡索引'
    assert payload['unknownTotal']['percent'] is None
    assert payload['unknownTotal']['count'] == ''

    # 升级线程刚起时 scope 行还是上一次的 ready，整体已是 building：
    # 文案必须跟着整体状态走，不能显示「已就绪」。
    assert payload['staleReady']['label'] == '准备重建世界书索引'

    assert payload['idle']['label'] == ''
    assert payload['error']['label'] == '索引异常'


def test_index_upgrade_completion_refreshes_lists_once():
    """building → ready 时必须刷新列表；构建中的多次轮询不能重复触发。"""
    node_script = textwrap.dedent(
        '''
        import { readFileSync } from 'node:fs';
        import vm from 'node:vm';

        const source = readFileSync('static/js/components/header.js', 'utf8');
        const start = source.indexOf('export default function header()');
        const body = source.slice(start).replace('export default function header()', 'function header()');

        const events = [];
        const toasts = [];
        const sandbox = {
          console,
          window: {
            addEventListener() {}, removeEventListener() {},
            dispatchEvent(event) { events.push(event.type); },
            setTimeout() {}, clearTimeout() {},
          },
          CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } },
        };
        vm.createContext(sandbox);
        vm.runInContext(`${body}\\nthis.__header = header;`, sandbox);
        const instance = sandbox.__header();
        const store = { global: { indexStatus: {}, settingsForm: {}, showToast: (...args) => toasts.push(args[0]) } };
        Object.defineProperty(instance, '$store', { value: store, configurable: true });

        // 构建中：多次轮询不应触发刷新。
        instance.handleIndexStatusTransition({ state: 'building', upgrade_active: true }, { state: 'building', upgrade_active: true });
        // 完成：触发一次。
        instance.handleIndexStatusTransition({ state: 'building', upgrade_active: true }, { state: 'ready', upgrade_active: false });
        // 已完成后再轮询：不再重复触发。
        instance.handleIndexStatusTransition({ state: 'ready' }, { state: 'ready' });
        // 普通增量构建（非升级）完成也要刷新列表，但不弹「升级完成」。
        instance.handleIndexStatusTransition({ state: 'building' }, { state: 'ready' });

        console.log(JSON.stringify({ events, toasts }));
        '''
    )

    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    import json

    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload['events'].count('refresh-wi-list') == 2
    assert payload['events'].count('refresh-card-list') == 2
    assert payload['toasts'] == ['索引升级完成，列表已刷新']
