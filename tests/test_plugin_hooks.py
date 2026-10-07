"""Hook 总线测试（设计文档 5.3 / 13.1）。"""

import logging
import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import hooks
from core.plugins.api import PluginAPI
from core.plugins.manifest import KNOWN_HOOKS, PluginManifest
from tests.plugins_test_support import write_plugin


@pytest.fixture(autouse=True)
def _clean_hooks():
    hooks.reset()
    yield
    hooks.reset()


class _CaptureHandler(logging.Handler):
    """显式捕获核心 hooks logger 的记录。

    不用 pytest 的 caplog：跨文件批量执行时它的级别状态会被其他测试影响，
    显式 handler 能稳定验证「异常隔离」与「耗时告警」。
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def hook_logs():
    logger = logging.getLogger('core.plugins.hooks')
    handler = _CaptureHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def test_emit_dispatches_payload_to_all_handlers():
    seen = []
    hooks.register('card.updated', lambda payload: seen.append(('a', payload['card_id'])), plugin_id='p1')
    hooks.register('card.updated', lambda payload: seen.append(('b', payload['card_id'])), plugin_id='p2')

    hooks.emit('card.updated', {'card_id': 'card.json'})

    assert seen == [('a', 'card.json'), ('b', 'card.json')]


def test_emit_without_handlers_is_noop():
    hooks.emit('card.deleted', {'card_ids': []})
    assert hooks.subscriber_count('card.deleted') == 0


def test_handler_exception_is_swallowed_and_logged(hook_logs):
    calls = []

    def boom(payload):
        raise RuntimeError('handler failed')

    hooks.register('card.updated', boom, plugin_id='broken-plugin')
    hooks.register('card.updated', lambda payload: calls.append('ok'), plugin_id='ok-plugin')

    hooks.emit('card.updated', {'card_id': 'x'})

    assert calls == ['ok']
    assert any(record.levelno == logging.ERROR for record in hook_logs)
    assert any('broken-plugin' in record.getMessage() for record in hook_logs)


def test_slow_handler_logs_warning(monkeypatch):
    """耗时告警：直接观察 logger.warning 的调用。

    不依赖 logging 全局级别（全量测试中其他用例可能改动 root/disable 状态），
    因此这里替换 `hooks.logger.warning` 来验证「确实记了一条 warning」。
    """
    monkeypatch.setattr(hooks, 'SLOW_HANDLER_THRESHOLD', 0.0)

    warnings = []
    monkeypatch.setattr(hooks.logger, 'warning', lambda *args, **kwargs: warnings.append(args))

    def slow(payload):
        time.sleep(0.01)

    hooks.register('scan.completed', slow, plugin_id='slow-plugin')
    hooks.emit('scan.completed', {'scanned': 0})

    assert warnings
    assert 'slow-plugin' in warnings[0]


def test_register_rejects_custom_event_without_plugin_prefix():
    with pytest.raises(ValueError):
        hooks.register('some-other:thing', lambda payload: None, plugin_id='demo')


def test_register_accepts_plugin_prefixed_custom_event():
    hooks.register('demo:thing', lambda payload: None, plugin_id='demo')
    assert hooks.subscriber_count('demo:thing') == 1


def test_register_rejects_empty_event_and_non_callable():
    with pytest.raises(ValueError):
        hooks.register('', lambda payload: None)
    with pytest.raises(ValueError):
        hooks.register('card.updated', 'not-callable')


def test_unregister_plugin_removes_all_subscriptions():
    hooks.register('card.updated', lambda payload: None, plugin_id='demo')
    hooks.register('demo:custom', lambda payload: None, plugin_id='demo')
    hooks.register('card.deleted', lambda payload: None, plugin_id='other')

    removed = hooks.unregister_plugin('demo')

    assert removed == 2
    assert hooks.subscriber_count('card.updated') == 0
    assert hooks.subscriber_count('card.deleted') == 1


def test_unregister_single_handler():
    def handler(payload):
        return None

    hooks.register('card.updated', handler, plugin_id='demo')

    assert hooks.unregister('card.updated', handler) is True
    assert hooks.unregister('card.updated', handler) is False
    assert hooks.subscriber_count('card.updated') == 0


def test_core_events_match_manifest_whitelist():
    assert hooks.CORE_EVENTS == KNOWN_HOOKS


def test_plugin_api_emit_requires_prefix_for_custom_events(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    manifest = PluginManifest.load(plugin_dir)
    api = PluginAPI(manifest)

    received = []
    api.on('demo-plugin:hello', lambda payload: received.append(payload))
    api.emit('demo-plugin:hello', {'value': 1})

    assert received == [{'value': 1}]

    with pytest.raises(ValueError):
        api.emit('other-plugin:hello', {})


def test_plugin_api_emit_allows_core_events(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    api = PluginAPI(PluginManifest.load(plugin_dir))

    received = []
    api.on('card.updated', lambda payload: received.append(payload))
    api.emit('card.updated', {'card_id': 'a'})

    assert received == [{'card_id': 'a'}]
