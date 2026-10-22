# 权限与 tier 仅作披露，自绘作为能力位

后端插件是宿主进程内的任意 Python、没有沙箱，强制执行权限没有实际隔离意义；但删除披露会降低透明度。2026-10-21 决定：`permissions` 与 catalog `tier` 保留为安装/目录层面的披露，不强制执行；`tier` 不再用于限制贡献类型。自绘与全局样式改为显式能力位（`ui.custom` / `ui.global_styles`），在 manifest 声明并在安装时展示——这是透明披露，不是审批。

**Status**: accepted

**Consequences**:

- 契约文案不得再暗示 permissions 提供安全隔离。
- 能力位是 additive 的：新增能力位不需要改已有插件。
