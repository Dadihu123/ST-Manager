# 插件 DOM 必须挂在宿主分配的根节点下

自绘模式放开后，宿主仍需保证「禁用 / 卸载 / 崩溃后屏幕可恢复」。2026-10-21 决定：插件所有 DOM 必须挂在宿主分配的根节点之下（`api.createRoot()`；需要突破层叠上下文或 `backdrop-filter` 包含块时使用 `createRoot({ portal: true })` 得到的 body 级 portal root），禁用、卸载、崩溃时由宿主整体移除。移动端适配由插件自行负责，宿主只提供 `deviceType` 与断点/响应式建议。

**Status**: accepted

**Consequences**:

- 自绘不等于「任意往 `document.body` 塞节点」；portal root 由宿主统一分配，顺带解决 z-index 与包含块问题。
- 移动端体验成为插件责任；推荐通道（宿主渲染）则是默认获得移动端适配的方式。
