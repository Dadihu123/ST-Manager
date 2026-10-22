/**
 * `settings.section` 插槽渲染器（v3 `frontend.contributions.slots[]`）。
 *
 * 契约：`mount(container, ctx) -> cleanup`
 * - 容器由宿主创建、定位、滚动与回收，已带 `data-plugin="hello-world"`；
 * - 插件只往容器里画内容，不得给容器或祖先设置 position / z-index / inset；
 * - 关闭容器、切页、停用插件、kill switch 时宿主调用返回的清理函数。
 *
 * ctx = { api, pluginId, slot, mode, target, selection }。
 */
export function mountSettingsSection(container, ctx) {
  const api = ctx.api;

  const root = document.createElement("div");
  root.className = "plugin-hello-world-settings";

  const title = document.createElement("h4");
  title.className = "plugin-hello-world-title";
  title.textContent = "Hello World 设置（插槽渲染）";

  const text = document.createElement("p");
  text.className = "plugin-hello-world-text";
  text.textContent = "这段内容由 frontend/views/settingsSection.js 渲染在宿主提供的 settings.section 插槽里。";

  const pingButton = api.ui.button({
    label: "读取当前问候语",
    variant: "secondary",
    icon: "bolt",
    onClick: async () => {
      const data = await api.api("/ping");
      text.textContent = data && data.success
        ? `当前问候语：${data.greeting || "（空）"}`
        : "读取失败";
    },
  });

  root.append(title, text, api.ui.toolbar([pingButton]));
  container.append(root);

  // 插槽渲染器自己订阅的监听也要在 cleanup 里解除。
  const offConfigChange = api.onConfigChange(() => {
    text.textContent = "配置已更新（插槽渲染器通过 api.onConfigChange 收到通知）。";
  });

  return () => {
    offConfigChange();
    root.remove();
  };
}
