/**
 * static/js/utils/sse.js
 * SSE 帧解析工具（Provisional）。
 *
 * 浏览器原生 `EventSource` 已内置协议解析，常规订阅不需要它；此工具用于：
 * 1. 插件自行用 `fetch` + `ReadableStream` 消费 SSE；
 * 2. Node 侧对帧格式做协议校验（见 `tests/plugin_sse_parse_test.mjs`）。
 *
 * 协议要点：`字段: 值`；以 `:` 开头是注释（心跳）；空行结束一帧；
 * 多行 `data:` 用 `\n` 连接；`retry` 等未知字段忽略。
 */

/**
 * 把一段 SSE 文本解析为帧数组。
 *
 * @param {string} text SSE 原始文本（可含多帧，也可只有半帧）。
 * @param {{flush?: boolean}} [options] flush=false 时不输出结尾未闭合的帧。
 * @returns {Array<{id: string|null, event: string, data: string}>}
 */
export function parseSSEFrames(text, options = {}) {
  const { flush = true } = options;
  const frames = [];

  let current = { id: null, event: "message", data: [] };
  let pending = false;

  const flushFrame = () => {
    if (!pending) return;
    frames.push({ id: current.id, event: current.event, data: current.data.join("\n") });
    current = { id: null, event: "message", data: [] };
    pending = false;
  };

  const lines = String(text ?? "").split(/\r\n|\r|\n/);
  for (const line of lines) {
    if (line === "") {
      flushFrame();
      continue;
    }
    if (line.startsWith(":")) {
      continue;
    }

    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "id") {
      current.id = value;
      pending = true;
    } else if (field === "event") {
      current.event = value || "message";
      pending = true;
    } else if (field === "data") {
      current.data.push(value);
      pending = true;
    }
    // retry 及其他字段：忽略
  }

  if (flush) flushFrame();
  return frames;
}

/**
 * 解析帧内的 JSON 负载；非法 JSON 返回 null。
 *
 * @param {{data?: string}|null} frame
 */
export function parseSSEPayload(frame) {
  const raw = frame && typeof frame.data === "string" ? frame.data : "";
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch (error) {
    return null;
  }
}

export default { parseSSEFrames, parseSSEPayload };
