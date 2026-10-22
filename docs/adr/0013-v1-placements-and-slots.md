# v1 落点与插槽清单

2026-10-21 决定首发覆盖面——菜单落点：`context.folder`、`context.card`、`context.footer`、`batch.actions`、`commandPalette`、`dock`、`settings.nav`；插槽：`settings.section`、`header.actions`、`card.detail.tabs`、`page.cards.toolbar`、`page.worldinfo.toolbar`、`empty.*`。后续新增落点/插槽按 additive 变更处理，不需要升 `api_version`。

**Status**: accepted

**Consequences**:

- 插件侧无法通过声明获得首发清单之外的位置；需要新位置时走扩展点 RFC（hack：先用插槽渲染器把内容放进已有位置）。
- 宿主新增页面时必须同时声明其落点，否则插件无法进入该页面。
