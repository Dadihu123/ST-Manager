# 自绘 API：共享 portal root + 可选 overlay 注册 + kill switch

2026-10-21 决定：`api.createRoot()` 返回宿主分配的插件根节点下的元素；`api.createRoot({ portal: true })` 返回每个插件共享的 body 级 portal root 下的元素。`api.overlays.register({ id, element, layer, modal, onDismiss })` / `unregister(id)` 为**可选**登记：已登记且 `modal: true` 的浮层由宿主处理 ESC、焦点与遮挡通知，未登记的不干预。宿主提供 kill switch：强制关闭所有已登记浮层、卸载插件自绘 UI，并广播 `overlays:force-closed` 供插件清理。

**Status**: accepted

**Consequences**:

- 与 ADR-0006 / ADR-0007 对齐：宿主不接管浮层定位与层级，只做最小协调与止损。
- kill switch 不整插件卸载，避免丢失插件状态；未登记浮层只能靠卸载插件回收。
