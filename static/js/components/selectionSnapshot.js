/**
 * static/js/components/selectionSnapshot.js
 * 当前选中集快照（宿主内部用）。
 *
 * 命令面板等宿主内部消费方需要「当前视图 + 选中 id 列表」来构造
 * `ctx.target`（`kind: 'selection'`）。插件**不要**用这个模块，改用
 * `api.host.selection()`——那条接口是契约，这里读的 `store.viewState`
 * 只是 Provisional 耦合。
 *
 * 单独抽成模块而不是内联在调用方：读取形状（`viewState.selectedIds` +
 * `currentMode`）只应该有一份实现，否则宿主改字段名时会漏掉某一处。
 */

/**
 * 读取主程序当前的选中集。
 *
 * @returns {{mode: string, ids: string[]}} `mode` 为当前视图（`cards` /
 *   `worldinfo` / `presets` / …），`ids` 已转成字符串并去掉空值。
 */
export function readSelectionSnapshot() {
  const store = window.Alpine && typeof window.Alpine.store === "function"
    ? window.Alpine.store("global")
    : null;
  const viewState = (store && store.viewState) || {};
  const ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
  return {
    mode: String((store && store.currentMode) || ""),
    ids: ids.map((item) => String(item || "")).filter(Boolean),
  };
}

export default readSelectionSnapshot;
