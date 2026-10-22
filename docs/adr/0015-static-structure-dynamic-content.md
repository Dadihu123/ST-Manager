# 贡献声明为静态结构 + 动态内容

2026-10-21 决定：菜单树、插槽绑定、命令元数据在 manifest 静态声明；渲染器与命令处理器以 `{module, export}` 引用，宿主在插件激活时加载并绑定；运行时 API 只允许更新（`api.contributions.update(id, { label, badge, enabled, children })`）与移除（`remove(id)`），**不允许**运行时新增落点或贡献类型。

**Status**: accepted

**Considered Options**:

- 全运行时注册：菜单在插件加载失败时完全不可见，安装期也无法静态校验，否决。
- 全静态：无法支持数据驱动的动态子菜单、动态角标与置灰，否决。

**Consequences**:

- 安装期可校验落点、模块存在性、导出存在性与命令 id 唯一性——这是 `stm-plugin-check` 能离线工作的前提。
- 动态内容一律走 update；宿主必须保证更新是幂等的，且不重建宿主 UI 节点。
