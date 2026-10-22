/**
 * Hello World 示例插件前端入口 —— 插件契约 v3 活体夹具。
 *
 * 界面结构（菜单树 / 插槽 / 命令）全部来自 `manifest.frontend.contributions`，
 * 本文件只做三件事：
 *
 * 1. 用 `api.surfaces.register()` 注册宿主容器（定位、尺寸、焦点、ESC 全归宿主）；
 * 2. 用 `api.contributions.update()` 更新贡献项的**运行期状态**（徽标/状态/进度/忙碌）；
 * 3. 用 `api.ui` / `api.host` / `api.storage` / `api.jobs` 做业务演示。
 *
 * v3 已删除 `manifest.frontend.entries[]` 与旧的 `api.entries` 命名空间：结构必须静态声明
 * （ADR-0015「静态结构 + 动态内容」），运行期只能 update / remove / trigger。
 * 旧插件迁移见 `docs/plugin-migration-v2-to-v3.md`。
 *
 * 契约：导出 `activate(api)`，可选导出 `deactivate(api)`；
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
    mount(container) {
      container.appendChild(
        api.ui.panel({
          title: "modal 类型",
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

  // ---- 贡献项运行期状态（v3）：静态声明 + update() 动态内容 ----
  //
  // `PluginHost.loadAll()` 先调用 `activate()`，之后才把 manifest.contributions
  // 装进注册表；因此激活期间的 update() 可能因查不到节点而返回 false。
  // 这里记住期望值，并在 `contributions:changed` 时重放（幂等）。
  const runtime = { status: "ok", badge: null };
  const applyRuntime = () => {
    api.contributions.update("main-panel", { status: runtime.status });
    api.contributions.update("hello-palette", { badge: runtime.badge });
  };
  applyRuntime();
  disposers.push(api.on("contributions:changed", applyRuntime));

  // ---- 配置通知（D10）：宿主保存配置后立即拿到新值 ----
  disposers.push(
    api.onConfigChange((config) => {
      api.host.log(`配置已更新: ${JSON.stringify(config)}`, "info");
      runtime.badge = config.greeting ? "✓" : null;
      applyRuntime();
    }),
  );

  // ---- 存储（D8）：ui_data._plugins_v1.<id>.storage ----
  const launches = Number(api.storage.get("launches") || 0) + 1;
  await api.storage.set("launches", launches);

  // 订阅插件自定义事件（必须以 "<plugin_id>:" 开头；核心事件只能宿主发出）
  api.emit("hello-world:activated", { id: api.id, launches });

  return () => {
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
      // 演示坞栏运行期状态：busy / progress（0–1）/ status 由宿主渲染
      api.contributions.update("modal-demo", { busy: true, progress: 0.5, status: "作业进行中" });
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
        api.contributions.update("modal-demo", { busy: false, progress: null, status: "" });
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

  // 演示 `api.contributions.trigger()`：以编程方式执行菜单节点的 action。
  // 节点被 `when` 过滤时返回 false（本示例的 summarize 要求配置里有 greeting）。
  const triggerButton = api.ui.button({
    label: "以编程方式触发命令",
    variant: "secondary",
    icon: "play",
    onClick: () => {
      const ok = api.contributions.trigger("summarize", { source: "panel" });
      api.host.toast(ok ? "已触发 summarize 命令" : "当前上下文不满足命令条件");
    },
  });

  return api.ui.panel({
    title: `Hello World（来源：${ctx.source || "直接打开"}）`,
    subtitle: `插件 ${api.id} · API v${api.manifest.api_version}`,
    actions: [confirmButton],
    children: [
      title,
      greeting,
      api.ui.toolbar([pingButton, jobButton, triggerButton]),
      api.ui.section({
        title: "贡献通道演示（v3）",
        description:
          "manifest 用 contributions 声明了 dock / context.card / batch.actions（含二级菜单与分隔线）/ commandPalette / settings.nav 五个菜单落点、一个 settings.section 插槽与三条命令；宿主按声明渲染，插件不再运行期注册入口。",
      }),
      output,
    ],
  });
}

export function deactivate(api) {
  api.host.log("hello-world 前端已卸载", "info");
}
