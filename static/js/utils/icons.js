/**
 * static/js/utils/icons.js
 * 宿主图标名解析（设计文档 D4 的前端侧）。
 *
 * 契约：插件在 `entries[].icon` 与 `api.ui.icon()` 里写**宿主图标名**
 * （如 `wand`、`bolt`），宿主负责解析成正确的 sprite 与 `<use>` 引用。
 *
 * 命名空间区分（硬规则）：
 * - 宿主图标名**不含** `/` 与 `.`（如 `wand`）
 * - 插件自带资源路径**必含** `/`（如 `assets/logo.svg`）——这类值不在这里解析
 *
 * 名字 → sprite 的映射由 `tools/gen_plugin_ui_icons.py` 从 `static/icons/*.svg`
 * 生成（见 `./iconMap.js`），与后端 `core/plugins/icons.py` 同源。
 */

import { HOST_ICON_COUNT, ICON_ALIASES, ICON_SPRITE_MAP } from "./iconMap.js";

const STATIC_ICON_BASE = "/static/icons";

/** 判断取值是否是宿主图标名（而非插件自带资源路径）。 */
export function isHostIconName(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  return !text.includes("/") && !text.includes("\\") && !text.includes(".");
}

/** 解析别名（`plus` → `plus-square`、`grid` → `layout`）。 */
export function canonicalIconName(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return ICON_ALIASES[text] || text;
}

/** 返回图标所属精灵文件名；未知名字返回空串。 */
export function spriteForIcon(value) {
  const name = canonicalIconName(value);
  if (!name) return "";
  return ICON_SPRITE_MAP[name] || "";
}

/**
 * 解析出 `<use href>` 的值；未知名字返回空串。
 *
 * 插件自带资源路径（含 `/`）走 `/api/plugins/<id>/assets/...`，由
 * `pluginHost.js` 的 `toAbsoluteAssetUrl` 处理，不在这里解析。
 */
export function resolveIconUrl(value) {
  const sprite = spriteForIcon(value);
  if (!sprite) return "";
  return `${STATIC_ICON_BASE}/${sprite}#icon-${canonicalIconName(value)}`;
}

/** 图标名是否存在。 */
export function hasHostIcon(value) {
  return Boolean(spriteForIcon(value));
}

/** 全部宿主图标名（按字母序），供插件作者与设置页查询。 */
export function listHostIconNames() {
  return Object.keys(ICON_SPRITE_MAP).sort();
}

export { HOST_ICON_COUNT, ICON_ALIASES, ICON_SPRITE_MAP };
