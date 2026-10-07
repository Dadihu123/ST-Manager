/**
 * Hello World 示例插件前端入口。
 *
 * 契约：导出 `activate(api)`，可选导出 `deactivate(api)`。
 * 面板容器由 `api.createRoot()` 生成，自动带 data-plugin 标记（F12）。
 */

export async function activate(api) {
  const root = api.createRoot("div");
  root.classList.add("plugin-hello-world-panel");

  const title = document.createElement("h4");
  title.className = "plugin-hello-world-title";
  title.textContent = "Hello World 插件";

  const greeting = document.createElement("p");
  greeting.className = "plugin-hello-world-text";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "plugin-hello-world-button";
  button.textContent = "ping 后端";
  button.dataset.marqueeIgnore = "true";

  const output = document.createElement("pre");
  output.className = "plugin-hello-world-output";

  button.addEventListener("click", async () => {
    const data = await api.api("/ping");
    if (!data.success) {
      api.toast(data.msg || "请求失败");
      return;
    }
    greeting.textContent = data.greeting || "";
    api.toast(`pong · ${data.plugin}`);
    output.textContent = JSON.stringify(data, null, 2);
  });

  root.append(title, greeting, button, output);

  // 订阅插件自定义事件（必须以 "<plugin_id>:" 开头）
  api.emit("hello-world:activated", { id: api.id });

  return () => {
    root.remove();
  };
}

export function deactivate(api) {
  api.log?.("info", "hello-world 前端已卸载");
}
