/**
 * Hello World 的命令处理器（v3 `contributions.commands[].module` / `export`）。
 *
 * 命令 = 具名动作 + 处理器。它可以被：
 * - 菜单项引用（`action: {"type": "command", "id": "summarize"}`）；
 * - 命令面板列出（只列 `when` 求值通过的命令）；
 * - 全局快捷键触发（按下时求值，不满足则忽略）。
 *
 * 处理器形如 `(ctx) => void`，ctx = { api, pluginId, mode, target, selection, trigger }；
 * 异常由宿主捕获（日志 + toast），不会扩散到其它插件。
 */

/** 命令面板「Hello 概览」（Ctrl+Shift+H）：读一次后端再打开演示面板。 */
export async function summarize(ctx) {
  const api = ctx.api;
  const data = await api.api("/ping");
  if (data && data.success) {
    api.host.toast(`Hello · ${data.greeting || "pong"}`);
  } else {
    api.host.notify("后端没有响应", "error");
  }
  api.surfaces.open("main", { source: "command" });
}

/** 批量菜单项「Hello 批量 ping」：演示命令如何拿到当前选择上下文。 */
export function batchPing(ctx) {
  const selection = ctx.selection || {};
  const count = Number(selection.count ?? selection.length ?? 0) || 0;
  ctx.api.host.toast(`Hello 批量 ping：${count || "选中"} 项`);
}

/** 「请求宿主刷新角色卡列表」：演示保留的宿主动作（`api.host.refresh`）。 */
export function refreshList(ctx) {
  ctx.api.host.refresh("cards");
  ctx.api.host.toast("已请求刷新角色卡列表");
}
