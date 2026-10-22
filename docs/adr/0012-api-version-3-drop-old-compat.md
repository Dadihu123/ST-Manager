# api_version 升 3，删除旧版本兼容

2026-10-21 决定：`PLUGIN_API_VERSION` 升为 3，宿主只支持 `(3,)`；v1/v2 的 `entries` 解析与版本兼容代码全部删除；三个内部插件按 `stm-pet → hello-world → stm-ai-assistant` 的顺序同步重写，不留兼容层、不保留别名。

**Status**: accepted

**Consequences**:

- 不再出现「声称支持旧版本但没有行为分支」的假兼容。
- 发布后契约变更走 Stability / deprecation 流程，破坏性变更才升 `api_version`。
