/**
 * Hello World 示例插件前端入口 —— 契约活体夹具。
 *
 * 这个文件是 `docs/plugin-api.md` 的**可运行对照**：它刻意用到 D8 的全部命名
 * 空间（`entries` / `surfaces` / `ui` / `storage` / `host` / `onConfigChange`），
 * 以及 `mount(container, ctx)` 的容器契约。
 *
 * 重点观察：这里**没有**任何 `position: fixed`、`z-index`、焦点陷阱或 ESC 处理
 * —— 那些全部由宿主承担。插件只往宿主给的 container 里画东西。
 *
 * 契约：导出 `activate(api)`，可选导出 `deactivate(api)`。
 * `activate` 的返回值若是函数，宿主会在停用时调用（D9.1）。
 */

export async function activate(api) {
  const disposers = [];

  // ---- 宿主表面（D8）：容器、层级、焦点、ESC 全归宿主 ----
  api.surfaces.register("main", {
    title: "Hello World 演示面板",
    type: "panel",
    mount(container, ctx) {
      container.appendChild(buildPanel(api, ctx));
      return () => {
        // mount 返回的函数在关闭时被调用（宿主保证）
        container.textContent = "";
      };
    },
  });

  api.surfaces.register("modal-demo", {
    title: "模态表面演示",
    type: "modal",
    mount(container, ctx) {
      container.appendChild(
        api.ui.panel({
          title: "modal 类型",
          subtitle: `来源：${ctx.source || "未知"}`,
          children: [
            api.ui.section({
              title: "容器由宿主提供",
              description:
                "定位、尺寸、滚动、role=dialog、aria-modal、焦点陷阱与 ESC 关闭都由宿主处理，插件不重复实现。",
            }),
          ],
        }),
      );
    },
  });

  // ---- 命令面板入口（D8）：动态注册一个 command ----
  api.entries.register({
    id: "runtime-hello",
    kind: "command",
    label: "Hello 运行期命令",
    description: "由 api.entries.register() 在运行期注册",
    icon: "bolt",
  });
  disposers.push(() => api.entries.remove("runtime-hello"));

  // ---- 配置通知（D10）：宿主保存配置后立即拿到新值 ----
  disposers.push(
    api.onConfigChange((config) => {
      api.host.log(`配置已更新: ${JSON.stringify(config)}`, "info");
      api.entries.setBadge("summarize", config.greeting ? "✓" : null);
    }),
  );

  // ---- 存储（D8）：ui_data._plugins_v1.<id>.storage ----
  const launches = Number(api.storage.get("launches") || 0) + 1;
  await api.storage.set("launches", launches);

  // ---- 入口运行期状态（D8）----
  api.entries.setStatus("main-panel", "ok");
  api.entries.setProgress("modal-demo", { done: 1, total: 1 });

  // 保留旧写法仍可用（别名委托到新实现）
  const legacyRoot = api.createRoot("div");
  legacyRoot.classList.add("plugin-hello-world-panel");
  legacyRoot.append(buildLegacyPanel(api));

  // 订阅插件自定义事件（必须以 "<plugin_id>:" 开头）
  api.emit("hello-world:activated", { id: api.id, launches });

  return () => {
    legacyRoot.remove();
    for (const dispose of disposers.reverse()) {
      try {
        dispose();
      } catch (error) {
        api.host.log(`清理失败: ${error}`, "warning");
      }
    }
  };
}

/** 用宿主 UI 原语搭建演示面板。 */
function buildPanel(api, ctx) {
  const title = document.createElement("h4");
  title.className = "plugin-hello-world-title";
  title.textContent = `Hello World 插件（v${api.manifest.version}）`;

  const greeting = document.createElement("p");
  greeting.className = "plugin-hello-world-text";
  greeting.textContent = `启动次数：${api.storage.get("launches") || 1}`;

  const output = document.createElement("pre");
  output.className = "plugin-hello-world-output";

  const pingButton = api.ui.button({
    label: "ping 后端",
    variant: "primary",
    icon: "bolt",
    onClick: async () => {
      const data = await api.api("/ping");
      if (!data.success) {
        api.host.notify(data.msg || "请求失败", "error");
        return;
      }
      greeting.textContent = data.greeting || "";
      api.host.toast(`pong · ${data.plugin}`);
      output.textContent = JSON.stringify(data, null, 2);
    },
  });

  const jobButton = api.ui.button({
    label: "跑 1000 项批量作业",
    variant: "secondary",
    icon: "play",
    onClick: async () => {
      const items = Array.from({ length: 1000 }, (_, index) => ({
        key: `item-${index + 1}`,
        // 每 50 项制造一个失败，便于演示「只重跑失败项」
        fail: index % 50 === 0,
      }));

      jobButton.disabled = true;
      try {
        const runId = await api.jobs.submit("demo.count", items, { source: "hello-world" });
        if (!runId) {
          api.host.notify("作业提交失败", "error");
          return;
        }
        api.host.toast(`作业已创建: ${runId.slice(0, 8)}`);
        api.jobs.open(runId, { title: "Hello World 批量作业" });
      } finally {
        jobButton.disabled = false;
      }
    },
  });

  const confirmButton = api.ui.button({
    label: "宿主确认框",
    variant: "ghost",
    onClick: async () => {
      const ok = await api.ui.confirm({
        title: "演示确认框",
        message: "这个对话框完全由宿主渲染，插件没有自己的浮层。",
      });
      api.host.toast(ok ? "已确认" : "已取消");
    },
  });

  return api.ui.panel({
    title: `Hello World（来源：${ctx.source || "直接打开"}）`,
    subtitle: `插件 ${api.id} · API v${api.manifest.api_version}`,
    actions: [confirmButton],
    children: [
      title,
      greeting,
      api.ui.toolbar([pingButton, jobButton]),
      api.ui.section({
        title: "入口契约演示",
        description:
          "本插件声明了 dock / nav / settings / context / command / status 六种入口。nav 与 status 仅官方、认证插件可用，社区插件会被宿主忽略并记警告（D5）。",
      }),
      output,
    ],
  });
}

/** 旧写法演示：`api.createRoot()` + 裸动词仍然可用（别名）。 */
function buildLegacyPanel(api) {
  const fragment = document.createDocumentFragment();

  const button = document.createElement("button");
  button.type = "button";
  button.className = "plugin-hello-world-button";
  button.textContent = "刷新角色卡列表（旧 API）";
  button.dataset.marqueeIgnore = "true";
  button.addEventListener("click", () => {
    api.refresh("cards");
    api.toast("已请求刷新");
  });

  fragment.appendChild(button);
  return fragment;
}

export function deactivate(api) {
  api.host.log("hello-world 前端已卸载", "info");
}
