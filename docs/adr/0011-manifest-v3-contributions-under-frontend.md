# manifest v3：贡献声明收进 frontend，permissions 改名 capabilities

2026-10-21 决定：新 manifest 删除 `entries`；前端声明收进 `frontend`——`entry`（模块入口）、`styles`、`contributions`（`menus` / `slots` / `commands`）、`render_mode`（`declarative` | `custom`，默认 `declarative`）。顶层 `permissions` 改名为 `capabilities`，只承担披露语义（含 `ui.custom`、`ui.global_styles` 等能力位）。

**Status**: accepted

**Consequences**:

- 旧 `entries` 及 `frontend.panels` 等字段的解析在 v3 中删除。
- manifest 的「声明结构」与「能力披露」从此分开，`capabilities` 不再暗示强制隔离。
