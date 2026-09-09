# 预设编辑器 SVG 图标缺口

本次预设全屏编辑器与回滚工作台重构已逐项核对新增和调整的图标入口。

- 缺失 SVG：无
- 使用中性占位符：无
- 图标来源：项目现有 `static/icons/ui.svg` 与 `static/icons/detail.svg`

新增入口均使用现有 SVG symbol，并为纯图标按钮补充了 `title` 与 `aria-label`。
