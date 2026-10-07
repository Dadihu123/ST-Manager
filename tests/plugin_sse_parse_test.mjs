/**
 * tests/plugin_sse_parse_test.mjs
 * SSE 帧解析协议校验（设计文档 13.4）。
 *
 * 运行：node tests/plugin_sse_parse_test.mjs
 */

import assert from 'node:assert/strict';

import { parseSSEFrames, parseSSEPayload } from '../static/js/utils/sse.js';

// 1. 单帧：id / event / data
{
  const frames = parseSSEFrames('id: 7\nevent: item\ndata: {"a":1}\n\n');
  assert.equal(frames.length, 1);
  assert.deepEqual(frames[0], { id: '7', event: 'item', data: '{"a":1}' });
}

// 2. 多帧连续解析，id 与 event 不串帧
{
  const text = 'id: 0\nevent: snapshot\ndata: {"run":"x"}\n\nid: 1\nevent: item\ndata: {"k":"a"}\n\n';
  const frames = parseSSEFrames(text);
  assert.equal(frames.length, 2);
  assert.deepEqual(frames.map((frame) => frame.event), ['snapshot', 'item']);
  assert.deepEqual(frames.map((frame) => frame.id), ['0', '1']);
  assert.equal(frames[1].data, '{"k":"a"}');
}

// 3. 多行 data 以 \n 连接
{
  const frames = parseSSEFrames('event: log\ndata: line-1\ndata: line-2\ndata: line-3\n\n');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].data, 'line-1\nline-2\nline-3');
}

// 4. 注释行（心跳）被忽略，不影响帧内容
{
  const frames = parseSSEFrames(': heartbeat\n\nid: 5\nevent: done\ndata: {}\n\n');
  assert.equal(frames.length, 1);
  assert.deepEqual(frames[0], { id: '5', event: 'done', data: '{}' });
}

// 5. 字段值中的冒号不被截断
{
  const frames = parseSSEFrames('data: {"url":"http://x/y"}\n\n');
  assert.equal(frames[0].data, '{"url":"http://x/y"}');
}

// 6. CRLF 与 CR 换行兼容
{
  const crlf = parseSSEFrames('id: 1\r\nevent: item\r\ndata: {}\r\n\r\n');
  const cr = parseSSEFrames('id: 1\revent: item\rdata: {}\r\r');
  assert.equal(crlf.length, 1);
  assert.equal(cr.length, 1);
  assert.equal(crlf[0].event, cr[0].event);
}

// 7. 缺省 event 名为 message
{
  const frames = parseSSEFrames('data: hello\n\n');
  assert.equal(frames[0].event, 'message');
  assert.equal(frames[0].id, null);
}

// 8. flush=false 时不输出结尾未闭合帧
{
  const text = 'id: 1\nevent: item\ndata: {}\n\nid: 2\nevent: item\ndata: {';
  assert.equal(parseSSEFrames(text).length, 2);
  assert.equal(parseSSEFrames(text, { flush: false }).length, 1);
}

// 9. 空输入与纯注释输入产出 0 帧
{
  assert.deepEqual(parseSSEFrames(''), []);
  assert.deepEqual(parseSSEFrames(': heartbeat\n\n'), []);
}

// 10. retry 等未知字段被忽略
{
  const frames = parseSSEFrames('retry: 3000\nid: 9\ndata: x\n\n');
  assert.deepEqual(frames, [{ id: '9', event: 'message', data: 'x' }]);
}

// 11. JSON 负载解析（含中文，非 ASCII 不转义）
{
  const frames = parseSSEFrames('event: item\ndata: {"name":"角色","tags":["a","b"]}\n\n');
  const payload = parseSSEPayload(frames[0]);
  assert.deepEqual(payload, { name: '角色', tags: ['a', 'b'] });

  assert.equal(parseSSEPayload({ data: 'not json' }), null);
  assert.equal(parseSSEPayload(null), null);
}

// 12. 与后端真实帧样例保持一致（core/plugins/jobs.py 的 _sse_frame）
{
  const text =
    'id: 0\n' +
    'event: snapshot\n' +
    'data: {"run_id":"abc","status":"running","total":2,"completed":0}\n' +
    '\n' +
    ': heartbeat\n' +
    '\n' +
    'id: 1\n' +
    'event: item\n' +
    'data: {"item_key":"a","status":"done","result":{"echo":"a"}}\n' +
    '\n' +
    'id: 2\n' +
    'event: done\n' +
    'data: {"status":"completed","completed":2,"failed":0}\n' +
    '\n';

  const frames = parseSSEFrames(text);
  assert.equal(frames.length, 3);
  assert.equal(parseSSEPayload(frames[0]).run_id, 'abc');
  assert.equal(parseSSEPayload(frames[1]).item_key, 'a');
  assert.equal(parseSSEPayload(frames[2]).status, 'completed');
}

console.log('✅ plugin_sse_parse_test: all assertions passed');
