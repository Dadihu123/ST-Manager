/**
 * static/js/uiPrimitives.js
 * 宿主 UI 原语（设计文档 D8 的 `api.ui.*`）。
 *
 * 存在的意义：插件此前要么复制粘贴宿主的表单/卡片/按钮样式，要么自己造一套，
 * 结果视觉不一致、主题切换失效、还要跟着宿主改。这里提供**唯一**的一套原语，
 * 插件只声明结构，渲染与样式归宿主。
 *
 * 硬约束：
 * - 只用 `.color-*` 语义类与既有 CSS 变量，不写死颜色
 *   （`tests/test_color_system_contracts.py` 禁止 Tailwind 调色板工具类）
 * - 表单控件与 `pluginManager.js` 的 `schemaEntries` / `isRequired` 共用同一套
 *   `config_schema` 子集：`type` / `title` / `description` / `default` /
 *   `minimum` / `maximum` / `enum` / `secret` / `required`
 * - 遵守 `prefers-reduced-motion`（动效样式在 ui-primitives.css 里统一处理）
 */

import { resolveIcon } from "./utils/icons.js";

/** 创建元素并一次性设置属性 / 类名 / 文本。 */
function el(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  if (options.html !== undefined) node.innerHTML = String(options.html);
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      if (value === undefined || value === null || value === false) continue;
      node.setAttribute(name, String(value));
    }
  }
  if (options.dataset) {
    for (const [name, value] of Object.entries(options.dataset)) {
      if (value === undefined || value === null) continue;
      node.dataset[name] = String(value);
    }
  }
  if (Array.isArray(options.children)) {
    for (const child of options.children) {
      if (child instanceof Node) node.appendChild(child);
      else if (child !== null && child !== undefined) node.appendChild(document.createTextNode(String(child)));
    }
  }
  return node;
}

/**
 * 宿主图标元素（D4）。
 *
 * 两种取值都能渲染（设计文档 2.2：`icon` 可以是宿主图标名，也可以是插件内资源路径）：
 * - **宿主图标名** → `<svg><use href="/static/icons/<sprite>.svg#icon-<name>"></use></svg>`，
 *   名字 → sprite 的映射由宿主维护（与 `templates/components/icon.html` 的宏一致）。
 * - **插件自带资源路径**（含 `/`）→ `<span>` + CSS `mask`，由 `background-color: currentColor`
 *   着色。**不能**塞进 `<use>`：宿主 sprite 是描边式（`fill: none; stroke: currentColor`），
 *   插件 SVG 通常是填充式（`fill: currentColor`），几何与着色方式都不同，混用会渲染成空图形。
 *   用 mask 而不是 `<img>`：`<img>` 里的 SVG 解析不到页面 CSS 变量，`currentColor` 永远是黑。
 *
 * 未知名字 / 非法资源路径返回占位元素而不是抛错——图标不该拖垮整个界面。
 *
 * @param {string} name 宿主图标名，或插件内资源路径（如 `assets/icon.svg`）。
 * @param {object} [options]
 * @param {string} [options.className]
 * @param {string} [options.pluginId] 资源路径必需（解析 `/api/plugins/<id>/assets/…`）。
 */
export function icon(name, options = {}) {
  const requested = String(name || "").trim();
  const className = ["ui-icon", options.className || ""].filter(Boolean).join(" ");
  const resolved = resolveIcon(requested, { pluginId: options.pluginId });

  if (resolved.kind === "asset") {
    const span = el("span", { className: `${className} ui-icon--asset` });
    span.setAttribute("aria-hidden", "true");
    span.style.setProperty("--ui-icon-mask", `url("${resolved.url}")`);
    span.dataset.icon = requested;
    span.dataset.iconAsset = resolved.url;
    return span;
  }

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  if (resolved.kind === "missing") {
    svg.dataset.iconMissing = resolved.name || "unknown";
    svg.classList.add("is-missing");
    return svg;
  }

  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", resolved.href);
  svg.appendChild(use);
  svg.dataset.icon = requested;
  return svg;
}

/** 按钮。`variant` ∈ primary | secondary | danger | ghost。 */
export function button(options = {}) {
  const variant = ["primary", "secondary", "danger", "ghost"].includes(String(options.variant || ""))
    ? String(options.variant)
    : "secondary";

  const node = el("button", {
    className: `ui-primitive-button ui-primitive-button--${variant}`,
    attrs: { type: options.type || "button" },
  });

  if (options.icon) {
    node.appendChild(icon(options.icon, {
      className: "ui-icon--sm",
      pluginId: options.pluginId || "",
    }));
  }
  if (options.label) node.appendChild(el("span", { text: options.label }));

  if (options.disabled) node.disabled = true;
  if (options.title) node.title = String(options.title);
  if (typeof options.onClick === "function") {
    node.addEventListener("click", (event) => options.onClick(event));
  }
  return node;
}

/** 面板容器：标题 + 副标题 + 右上角动作区。 */
export function panel(options = {}) {
  const node = el("section", { className: "ui-primitive-panel color-surface-container" });

  if (options.title || options.subtitle || options.actions) {
    const header = el("header", { className: "ui-primitive-panel__header" });
    const titles = el("div", { className: "ui-primitive-panel__titles" });

    if (options.title) {
      titles.appendChild(el("h3", { className: "ui-primitive-panel__title color-text-primary", text: options.title }));
    }
    if (options.subtitle) {
      titles.appendChild(
        el("p", { className: "ui-primitive-panel__subtitle color-text-muted", text: options.subtitle }),
      );
    }
    header.appendChild(titles);

    if (Array.isArray(options.actions) && options.actions.length) {
      const actions = el("div", { className: "ui-primitive-panel__actions" });
      for (const action of options.actions) {
        if (action instanceof Node) actions.appendChild(action);
      }
      header.appendChild(actions);
    }
    node.appendChild(header);
  }

  const body = el("div", { className: "ui-primitive-panel__body" });
  for (const child of options.children || []) {
    if (child instanceof Node) body.appendChild(child);
  }
  node.appendChild(body);
  return node;
}

/** 区块：标题 + 说明。 */
export function section(options = {}) {
  const node = el("section", { className: "ui-primitive-section" });
  if (options.title) {
    node.appendChild(el("h4", { className: "ui-primitive-section__title color-text-primary", text: options.title }));
  }
  if (options.description) {
    node.appendChild(
      el("p", { className: "ui-primitive-section__description color-text-muted", text: options.description }),
    );
  }
  const body = el("div", { className: "ui-primitive-section__body" });
  for (const child of options.children || []) {
    if (child instanceof Node) body.appendChild(child);
  }
  node.appendChild(body);
  return node;
}

/** 卡片：标题 + 元信息。 */
export function card(options = {}) {
  const node = el("article", { className: "ui-primitive-card color-surface-raised" });
  if (options.title) {
    node.appendChild(el("h4", { className: "ui-primitive-card__title color-text-primary", text: options.title }));
  }
  if (options.meta) {
    node.appendChild(el("p", { className: "ui-primitive-card__meta color-text-muted", text: options.meta }));
  }
  const body = el("div", { className: "ui-primitive-card__body" });
  for (const child of options.children || []) {
    if (child instanceof Node) body.appendChild(child);
  }
  node.appendChild(body);
  return node;
}

/** 徽标。`tone` ∈ neutral | info | success | warning | danger。 */
export function badge(options = {}) {
  const tone = ["neutral", "info", "success", "warning", "danger"].includes(String(options.tone || ""))
    ? String(options.tone)
    : "neutral";
  const node = el("span", {
    className: `ui-primitive-badge ui-primitive-badge--${tone}`,
    text: options.value === undefined || options.value === null ? "" : options.value,
  });
  return node;
}

/** 空态：图标 + 标题 + 说明 + 可选动作。 */
export function empty(options = {}) {
  const node = el("div", { className: "ui-primitive-empty" });
  if (options.icon) {
    node.appendChild(icon(options.icon, {
      className: "ui-primitive-empty__icon",
      pluginId: options.pluginId || "",
    }));
  }
  if (options.title) {
    node.appendChild(el("p", { className: "ui-primitive-empty__title color-text-secondary", text: options.title }));
  }
  if (options.description) {
    node.appendChild(el("p", { className: "ui-primitive-empty__description color-text-muted", text: options.description }));
  }
  if (options.action instanceof Node) {
    const actions = el("div", { className: "ui-primitive-empty__actions" });
    actions.appendChild(options.action);
    node.appendChild(actions);
  }
  return node;
}

/** 错误态：标题 + 消息 + 可选重试。 */
export function error(options = {}) {
  const node = el("div", { className: "ui-primitive-error", attrs: { role: "alert" } });
  node.appendChild(icon("alert-triangle", { className: "ui-primitive-error__icon color-text-danger" }));
  node.appendChild(
    el("p", {
      className: "ui-primitive-error__title color-text-danger",
      text: options.title || "出错了",
    }),
  );
  if (options.message) {
    node.appendChild(el("p", { className: "ui-primitive-error__message color-text-secondary", text: options.message }));
  }
  if (typeof options.retry === "function") {
    node.appendChild(button({ label: "重试", variant: "secondary", icon: "refresh", onClick: options.retry }));
  }
  return node;
}

/** 加载态。 */
export function loading(options = {}) {
  const node = el("div", { className: "ui-primitive-loading", attrs: { role: "status" } });
  node.appendChild(el("span", { className: "ui-primitive-loading__spinner", attrs: { "aria-hidden": "true" } }));
  node.appendChild(el("span", { className: "color-text-muted", text: options.label || "加载中…" }));
  return node;
}

/** 工具条：横向排列的按钮 / 分隔符。 */
export function toolbar(items = []) {
  const node = el("div", { className: "ui-primitive-toolbar", attrs: { role: "toolbar" } });
  for (const item of Array.isArray(items) ? items : []) {
    if (item instanceof Node) {
      node.appendChild(item);
    } else if (item === "-") {
      node.appendChild(el("span", { className: "ui-primitive-toolbar__separator", attrs: { "aria-hidden": "true" } }));
    }
  }
  return node;
}

/** 网格容器。 */
export function grid(options = {}) {
  const node = el("div", { className: "ui-primitive-grid" });
  const columns = Number(options.columns);
  if (Number.isFinite(columns) && columns > 0) {
    node.style.setProperty("--ui-grid-columns", String(Math.floor(columns)));
  }
  if (options.gap) node.style.setProperty("--ui-grid-gap", String(options.gap));
  for (const child of options.children || []) {
    if (child instanceof Node) node.appendChild(child);
  }
  return node;
}

/** 左右分栏。 */
export function split(options = {}) {
  const node = el("div", { className: "ui-primitive-split" });
  const ratio = Number(options.ratio);
  if (Number.isFinite(ratio) && ratio > 0 && ratio < 1) {
    node.style.setProperty("--ui-split-left", `${Math.round(ratio * 100)}%`);
  }
  const left = el("div", { className: "ui-primitive-split__left" });
  const right = el("div", { className: "ui-primitive-split__right" });
  if (options.left instanceof Node) left.appendChild(options.left);
  if (options.right instanceof Node) right.appendChild(options.right);
  node.appendChild(left);
  node.appendChild(right);
  return node;
}

/** 列表。`renderItem(item, index)` 返回 Node。 */
export function list(options = {}) {
  const items = Array.isArray(options.items) ? options.items : [];
  const node = el("div", { className: "ui-primitive-list", attrs: { role: "list" } });

  if (!items.length) {
    const emptyNode = options.empty;
    if (emptyNode instanceof Node) node.appendChild(emptyNode);
    else node.appendChild(empty({ title: String(options.empty || "暂无内容") }));
    return node;
  }

  items.forEach((item, index) => {
    const row = el("div", { className: "ui-primitive-list__item", attrs: { role: "listitem" } });
    const rendered = typeof options.renderItem === "function" ? options.renderItem(item, index) : null;
    if (rendered instanceof Node) row.appendChild(rendered);
    else row.textContent = String(rendered ?? item ?? "");
    node.appendChild(row);
  });
  return node;
}

/** 表格。`columns` = [{ key, label, render? }]。 */
export function table(options = {}) {
  const columns = Array.isArray(options.columns) ? options.columns : [];
  const rows = Array.isArray(options.rows) ? options.rows : [];

  const wrapper = el("div", { className: "ui-primitive-table-wrapper" });
  const node = el("table", { className: "ui-primitive-table" });

  const thead = el("thead");
  const headRow = el("tr");
  for (const column of columns) {
    headRow.appendChild(el("th", { text: column.label ?? column.key ?? "" }));
  }
  thead.appendChild(headRow);
  node.appendChild(thead);

  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const column of columns) {
      const td = el("td");
      const value = row ? row[column.key] : undefined;
      if (typeof column.render === "function") {
        const rendered = column.render(value, row);
        if (rendered instanceof Node) td.appendChild(rendered);
        else td.textContent = String(rendered ?? "");
      } else {
        td.textContent = value === undefined || value === null ? "" : String(value);
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  node.appendChild(tbody);

  wrapper.appendChild(node);
  return wrapper;
}

// ---------------------------------------------------------------- 表单

/**
 * 单个表单字段。
 *
 * 与 `pluginManager.js` 的 `schemaEntries` / `isRequired` 共用同一套 schema 子集，
 * 保证插件配置表单与宿主渲染的配置表单长得一样。
 */
export function field(schemaEntry, options = {}) {
  const key = String((schemaEntry && schemaEntry.key) || options.key || "");
  const spec = (schemaEntry && schemaEntry.spec) || options.spec || {};
  const required = Boolean(options.required);

  const wrapper = el("div", { className: "ui-primitive-field" });
  if (key) wrapper.dataset.fieldKey = key;

  const inputId = `ui-field-${key}-${Math.random().toString(36).slice(2, 8)}`;

  if (spec.title || spec.description) {
    const label = el("label", {
      className: "ui-primitive-field__label color-text-secondary",
      attrs: { for: inputId },
    });
    label.appendChild(document.createTextNode(String(spec.title || key)));
    if (required) {
      label.appendChild(el("span", { className: "ui-primitive-field__required color-text-danger", text: "*" }));
    }
    wrapper.appendChild(label);
  }

  const type = String(spec.type || "string");
  let control;

  if (type === "boolean") {
    control = el("input", { className: "ui-primitive-field__checkbox", attrs: { id: inputId, type: "checkbox" } });
    control.checked = Boolean(options.value ?? spec.default);
  } else if (type === "enum" || Array.isArray(spec.enum)) {
    control = el("select", { className: "ui-primitive-field__select color-surface-control", attrs: { id: inputId } });
    const choices = Array.isArray(spec.enum) ? spec.enum : [];
    for (const choice of choices) {
      const option = el("option", { text: String(choice), attrs: { value: String(choice) } });
      if (String(options.value ?? spec.default ?? "") === String(choice)) option.selected = true;
      control.appendChild(option);
    }
  } else if (type === "integer" || type === "number") {
    control = el("input", {
      className: "ui-primitive-field__input color-surface-control",
      attrs: {
        id: inputId,
        type: "number",
        min: spec.minimum !== undefined ? spec.minimum : null,
        max: spec.maximum !== undefined ? spec.maximum : null,
        step: type === "integer" ? "1" : "any",
      },
    });
    control.value = options.value ?? spec.default ?? "";
  } else {
    control = el("input", {
      className: "ui-primitive-field__input color-surface-control",
      attrs: {
        id: inputId,
        type: spec.secret ? "password" : "text",
        placeholder: spec.secret && options.hint ? options.hint : null,
      },
    });
    control.value = options.value ?? spec.default ?? "";
  }

  if (typeof options.onChange === "function") {
    const eventName = type === "boolean" || type === "enum" ? "change" : "input";
    control.addEventListener(eventName, () => {
      const value = type === "boolean" ? control.checked : control.value;
      options.onChange(value, key);
    });
  }

  wrapper.appendChild(control);

  if (spec.description) {
    wrapper.appendChild(
      el("p", { className: "ui-primitive-field__description color-text-muted", text: spec.description }),
    );
  }
  return wrapper;
}

/** 表单：由 `config_schema` 子集生成字段，`onSubmit(values)` 收结果。 */
export function form(schema, options = {}) {
  const properties = (schema && schema.properties) || {};
  const required = new Set(Array.isArray(schema && schema.required) ? schema.required : []);
  const values = Object.assign({}, options.values || {});

  const node = el("form", { className: "ui-primitive-form" });
  node.addEventListener("submit", (event) => event.preventDefault());

  const controls = new Map();
  for (const key of Object.keys(properties)) {
    const spec = properties[key] || {};
    if (values[key] === undefined && spec.default !== undefined) values[key] = spec.default;

    const control = field(
      { key, spec },
      {
        value: values[key],
        required: required.has(key),
        hint: options.hints ? options.hints[key] : "",
        onChange: (value) => {
          values[key] = value;
        },
      },
    );
    controls.set(key, control);
    node.appendChild(control);
  }

  if (typeof options.onSubmit === "function") {
    const actions = el("div", { className: "ui-primitive-form__actions" });
    actions.appendChild(
      button({
        label: options.submitLabel || "保存",
        variant: "primary",
        onClick: () => options.onSubmit({ ...values }),
      }),
    );
    if (typeof options.onCancel === "function") {
      actions.appendChild(button({ label: "取消", variant: "ghost", onClick: options.onCancel }));
    }
    node.appendChild(actions);
  }

  node.getValues = () => ({ ...values });
  return node;
}

// ---------------------------------------------------------------- 交互

/**
 * 确认对话框。返回 `Promise<boolean>`。
 *
 * 用宿主自己的 modal 容器渲染，插件不必自己搭浮层。
 */
export function confirm(options = {}) {
  return new Promise((resolve) => {
    const overlay = el("div", { className: "modal-overlay ui-primitive-overlay" });
    overlay.dataset.marqueeIgnore = "true";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const shell = el("div", { className: "ui-modal-shell ui-primitive-dialog color-surface-overlay" });
    const body = el("div", { className: "ui-primitive-dialog__body" });

    body.appendChild(
      el("h3", { className: "ui-primitive-dialog__title color-text-primary", text: options.title || "确认操作" }),
    );
    if (options.message) {
      body.appendChild(el("p", { className: "color-text-secondary", text: options.message }));
    }

    const actions = el("div", { className: "ui-primitive-dialog__actions" });
    const finish = (result) => {
      // ESC 监听必须在这里摘掉：点按钮结束的对话框不会走 onKeydown，
      // 旧写法把监听留在 document 上——每弹一次确认就多一个永不释放的处理器。
      document.removeEventListener("keydown", onKeydown, true);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      resolve(result);
    };

    actions.appendChild(button({ label: options.cancelLabel || "取消", variant: "ghost", onClick: () => finish(false) }));
    actions.appendChild(
      button({
        label: options.confirmLabel || "确定",
        variant: options.danger ? "danger" : "primary",
        onClick: () => finish(true),
      }),
    );

    body.appendChild(actions);
    shell.appendChild(body);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    // 键盘用户：把焦点送进对话框。插件表面的焦点陷阱装在 shell 上，鼠标能点到
    // 这两个按钮，Tab 却被锁在面板里转圈，永远到不了这里。
    // 危险操作聚焦「取消」，避免一个回车就把东西删了；其余聚焦确认钮。
    const focusTarget = actions.querySelector(
      options.danger ? ".ui-primitive-button--ghost" : ".ui-primitive-button--primary",
    );
    if (focusTarget && typeof focusTarget.focus === "function") focusTarget.focus();

    function onKeydown(event) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      // 捕获阶段吃掉 ESC：`pluginSurfaceHost.js` 在 document 上也有一个 ESC
      // 监听（关闭当前 surface）。不 stopPropagation 的话，按一次 ESC 会
      // **同时**关掉对话框和它下面的插件面板，像是「取消却把整个工作台弄没了」。
      event.stopPropagation();
      finish(false);
    }
    document.addEventListener("keydown", onKeydown, true);
  });
}

/**
 * 输入对话框。返回 `Promise<object|null>`。
 *
 * `fields` = [{ key, label, type?, value?, placeholder? }]
 */
export function prompt(options = {}) {
  return new Promise((resolve) => {
    const overlay = el("div", { className: "modal-overlay ui-primitive-overlay" });
    overlay.dataset.marqueeIgnore = "true";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");

    const shell = el("div", { className: "ui-modal-shell ui-primitive-dialog color-surface-overlay" });
    const body = el("div", { className: "ui-primitive-dialog__body" });

    body.appendChild(
      el("h3", { className: "ui-primitive-dialog__title color-text-primary", text: options.title || "请输入" }),
    );

    const values = {};
    const fields = Array.isArray(options.fields) ? options.fields : [];
    for (const item of fields) {
      const key = String(item.key || "");
      if (!key) continue;
      values[key] = item.value ?? "";
      body.appendChild(
        field(
          { key, spec: { title: item.label || key, type: item.type || "string", description: item.description } },
          {
            value: values[key],
            onChange: (value) => {
              values[key] = value;
            },
          },
        ),
      );
    }

    const finish = (result) => {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      document.removeEventListener("keydown", onKeydown, true);
      resolve(result);
    };

    const actions = el("div", { className: "ui-primitive-dialog__actions" });
    actions.appendChild(button({ label: "取消", variant: "ghost", onClick: () => finish(null) }));
    actions.appendChild(button({ label: "确定", variant: "primary", onClick: () => finish({ ...values }) }));
    body.appendChild(actions);

    shell.appendChild(body);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);

    const firstInput = overlay.querySelector("input, select, textarea");
    if (firstInput && typeof firstInput.focus === "function") firstInput.focus();

    function onKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        // 与 confirm 同理：别让一次 ESC 连带关掉弹它的插件 surface。
        event.stopPropagation();
        finish(null);
      }
    }
    document.addEventListener("keydown", onKeydown, true);
  });
}

// ---------------------------------------------------------------- 菜单 / 浮层

/**
 * 菜单结构：`{ element, close(), focusFirst() }`。
 *
 * 与插件贡献菜单（`ContributionRegistry.menuTree()` 返回的树）**同构**：
 * `items` = `[{type:'item'|'submenu'|'separator', id, label, icon, description,
 * badge, disabled, disabledHint, children}]`。渲染器负责把手势映射成
 * `onSelect(item)`，本原语只保证键盘 / 焦点 / 关闭行为与宿主右键菜单一致。
 *
 * @param {object} [options]
 * @param {Array} [options.items]
 * @param {string} [options.label] `role="menu"` 的无障碍名称
 * @param {string} [options.pluginId]
 * @param {boolean} [options.closeOnSelect=true]
 * @param {Function} [options.onSelect] `(item, event) => void`
 */
export function menu(options = {}) {
  const closeOnSelect = options.closeOnSelect !== false;
  const node = el("div", {
    className: "ui-primitive-menu color-surface-overlay",
    attrs: { role: "menu", tabindex: "-1" },
  });
  if (options.label) node.setAttribute("aria-label", String(options.label));

  const api = { element: node, closed: false };

  function close() {
    if (api.closed) return;
    api.closed = true;
    node.dispatchEvent(new CustomEvent("ui:menu-close", { bubbles: true }));
  }

  function focusables() {
    return Array.from(node.querySelectorAll('[role="menuitem"]:not([aria-disabled="true"])'));
  }

  function appendItems(container, specs) {
    for (const spec of specs || []) {
      if (!spec) continue;
      if (spec.type === "separator") {
        container.appendChild(
          el("div", { className: "ui-primitive-menu__separator", attrs: { role: "separator" } }),
        );
        continue;
      }

      const hasSubmenu = Array.isArray(spec.children) && spec.children.length > 0;
      const item = el("button", {
        className: "ui-primitive-menu__item",
        attrs: { type: "button", role: hasSubmenu ? "menuitem" : "menuitem" },
      });
      if (spec.id) item.dataset.nodeId = String(spec.id);

      if (spec.icon) {
        item.appendChild(
          icon(spec.icon, {
            className: "ui-icon--sm",
            pluginId: spec.pluginId || options.pluginId || "",
          }),
        );
      }

      const copy = el("span", { className: "ui-primitive-menu__copy" });
      copy.appendChild(el("span", { className: "ui-primitive-menu__label", text: spec.label || "" }));
      if (spec.description) {
        copy.appendChild(
          el("span", { className: "ui-primitive-menu__description", text: spec.description }),
        );
      }
      item.appendChild(copy);

      if (spec.badge !== undefined && spec.badge !== null && spec.badge !== "") {
        item.appendChild(el("span", { className: "ui-primitive-menu__badge", text: String(spec.badge) }));
      }
      if (hasSubmenu) {
        item.setAttribute("aria-haspopup", "menu");
        item.setAttribute("aria-expanded", "false");
        item.classList.add("is-submenu");
        item.appendChild(icon("chevron-right", { className: "ui-icon--xs" }));
      }

      const disabled = Boolean(spec.disabled);
      if (disabled) {
        item.setAttribute("aria-disabled", "true");
        item.classList.add("is-disabled");
        if (spec.disabledHint) item.title = String(spec.disabledHint);
      }

      if (hasSubmenu) {
        const submenu = el("div", {
          className: "ui-primitive-menu__submenu",
          attrs: { role: "menu" },
        });
        submenu.hidden = true;
        appendItems(submenu, spec.children);
        const row = el("div", { className: "ui-primitive-menu__row" });
        row.appendChild(item);
        row.appendChild(submenu);
        container.appendChild(row);

        item.addEventListener("click", (event) => {
          event.stopPropagation();
          if (disabled) return;
          const open = submenu.hidden;
          closeOpenSubmenus(container, submenu);
          if (open) {
            submenu.hidden = false;
            item.setAttribute("aria-expanded", "true");
            const first = submenu.querySelector('[role="menuitem"]:not([aria-disabled="true"])');
            if (first && first.focus) first.focus();
          }
        });
      } else {
        item.addEventListener("click", (event) => {
          if (disabled) return;
          if (typeof options.onSelect === "function") options.onSelect(spec, event);
          if (closeOnSelect) close();
        });
        container.appendChild(item);
      }
    }
  }

  function closeOpenSubmenus(container, keep) {
    for (const submenu of Array.from(container.querySelectorAll(".ui-primitive-menu__submenu"))) {
      if (submenu === keep) continue;
      submenu.hidden = true;
      const trigger = submenu.parentNode && submenu.parentNode.querySelector('[aria-haspopup="menu"]');
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    }
  }

  appendItems(node, Array.isArray(options.items) ? options.items : []);

  node.addEventListener("keydown", (event) => {
    const items = focusables();
    if (!items.length) return;
    const current = document.activeElement;
    let index = items.indexOf(current);

    if (event.key === "ArrowDown") {
      event.preventDefault();
      index = index < 0 ? 0 : (index + 1) % items.length;
      if (items[index].focus) items[index].focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      index = index <= 0 ? items.length - 1 : index - 1;
      if (items[index].focus) items[index].focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      if (items[0].focus) items[0].focus();
    } else if (event.key === "End") {
      event.preventDefault();
      if (items[items.length - 1].focus) items[items.length - 1].focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  });

  api.close = close;
  api.focusFirst = () => {
    const items = focusables();
    if (items[0] && items[0].focus) items[0].focus();
  };
  return api;
}

/**
 * 浮层：把一个已构建好的节点定位到锚点旁，处理外部点击 / ESC / 焦点恢复。
 *
 * 定位复用宿主 flyout 规范（`positionFlyoutElement`），因此插件浮层与宿主
 * 下拉菜单的翻转 / 贴边行为一致。
 *
 * @param {object} [options]
 * @param {HTMLElement} [options.anchor] 锚点元素
 * @param {HTMLElement|Node} [options.content] 浮层内容
 * @param {Array<Node>} [options.children]
 * @param {"bottom-start"|"right-start"} [options.placement] 首选方向
 * @returns {{element: HTMLElement, close: Function, destroy: Function}}
 */
export function popover(options = {}) {
  const wrapper = el("div", {
    className: "ui-primitive-popover color-surface-overlay",
    attrs: { role: "dialog", tabindex: "-1" },
  });
  if (options.className) wrapper.classList.add(String(options.className));

  if (options.content instanceof Node) wrapper.appendChild(options.content);
  for (const child of options.children || []) {
    if (child instanceof Node) wrapper.appendChild(child);
  }

  document.body.appendChild(wrapper);

  const anchor = options.anchor instanceof Element ? options.anchor : null;
  const api = { element: wrapper, closed: false };

  const position = () => {
    if (!anchor) return;
    try {
      const rect = anchor.getBoundingClientRect();
      const size = { width: wrapper.offsetWidth, height: wrapper.offsetHeight };
      const viewport = { width: window.innerWidth, height: window.innerHeight };
      const preferBelow = options.placement !== "right-start";
      const gap = 6;
      let top = preferBelow ? rect.bottom + gap : rect.top;
      let left = preferBelow ? rect.left : rect.right + gap;
      if (left + size.width > viewport.width - 8) left = Math.max(8, rect.right - size.width);
      if (top + size.height > viewport.height - 8) top = Math.max(8, rect.top - size.height - gap);
      wrapper.style.position = "fixed";
      wrapper.style.top = `${Math.round(top)}px`;
      wrapper.style.left = `${Math.round(left)}px`;
      wrapper.style.zIndex = "var(--z-plugin-popover)";
    } catch (error) {
      console.warn("[uiPrimitives] popover 定位失败:", error);
    }
  };

  position();
  if (!wrapper.style.position) {
    wrapper.style.position = "fixed";
    wrapper.style.zIndex = "var(--z-plugin-popover)";
  }

  const onPointerDown = (event) => {
    if (wrapper.contains(event.target)) return;
    if (anchor && anchor.contains(event.target)) return;
    api.close();
  };
  const onKeydown = (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    // 与宿主一致：一次 ESC 只关最上层，别连带关掉插件 surface。
    event.stopPropagation();
    api.close();
  };
  const onResize = () => position();

  function close() {
    if (api.closed) return;
    api.closed = true;
    document.removeEventListener("pointerdown", onPointerDown, true);
    document.removeEventListener("keydown", onKeydown, true);
    window.removeEventListener("resize", onResize);
    if (wrapper.parentNode) wrapper.parentNode.removeChild(wrapper);
    if (anchor && anchor.focus) anchor.focus();
    wrapper.dispatchEvent(new CustomEvent("ui:popover-close", { bubbles: true }));
  }

  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("keydown", onKeydown, true);
  window.addEventListener("resize", onResize);

  api.close = close;
  api.destroy = close;
  api.reposition = position;
  return api;
}

/**
 * 标签栏：`{ element, setActive(key), active }`。
 *
 * @param {object} [options]
 * @param {Array} [options.items] `[{key,label,icon,badge,disabled}]`
 * @param {string} [options.active] 初始 key
 * @param {Function} [options.onChange] `(key) => void`
 */
export function tabs(options = {}) {
  const items = Array.isArray(options.items) ? options.items : [];
  const wrapper = el("div", {
    className: "ui-primitive-tabs",
    attrs: { role: "tablist" },
  });
  const api = { element: wrapper, active: String(options.active || (items[0] && items[0].key) || "") };

  const buttons = new Map();
  for (const item of items) {
    const key = String(item.key || "");
    if (!key) continue;
    const button = el("button", {
      className: "ui-primitive-tabs__tab",
      attrs: { type: "button", role: "tab" },
    });
    button.dataset.tabKey = key;
    if (item.icon) button.appendChild(icon(item.icon, { className: "ui-icon--sm" }));
    button.appendChild(el("span", { text: item.label || key }));
    if (item.badge !== undefined && item.badge !== null && item.badge !== "") {
      button.appendChild(el("span", { className: "ui-primitive-tabs__badge", text: String(item.badge) }));
    }
    if (item.disabled) {
      button.disabled = true;
      button.setAttribute("aria-disabled", "true");
    }
    button.addEventListener("click", () => {
      if (button.disabled) return;
      api.setActive(key);
    });
    buttons.set(key, button);
    wrapper.appendChild(button);
  }

  function sync() {
    for (const [key, button] of buttons) {
      const selected = key === api.active;
      button.classList.toggle("is-active", selected);
      button.setAttribute("aria-selected", selected ? "true" : "false");
    }
  }

  api.setActive = (key) => {
    const next = String(key || "");
    if (!buttons.has(next) || next === api.active) return;
    api.active = next;
    sync();
    if (typeof options.onChange === "function") options.onChange(next);
  };

  sync();
  return api;
}

/**
 * 布局容器：`direction` ∈ row | column，`gap` / `wrap` / `align` / `justify`。
 * 插件用它在宿主内容区排布自己的卡片，避免各写一套内联样式。
 */
export function layout(options = {}) {
  const direction = options.direction === "column" ? "column" : "row";
  const node = el("div", { className: `ui-primitive-layout ui-primitive-layout--${direction}` });
  if (options.wrap) node.classList.add("ui-primitive-layout--wrap");
  if (options.gap !== undefined) node.style.gap = typeof options.gap === "number" ? `${options.gap}px` : String(options.gap);
  if (options.align) node.style.alignItems = String(options.align);
  if (options.justify) node.style.justifyContent = String(options.justify);
  for (const child of options.children || []) {
    if (child instanceof Node) node.appendChild(child);
  }
  return node;
}

/**
 * 供 `api.ui.*` 一次性挂载。
 *
 * `pluginId` 由 `pluginHost.js:buildApi()` 传入，用于把**本插件**的相对资源路径
 * 解析成 `/api/plugins/<id>/assets/…`。插件调用 `api.ui.icon('assets/logo.svg')`
 * 时不需要自己拼 URL，也不该能引用别的插件的资源——这里把 id 钉死在闭包里，
 * 调用方传什么 `pluginId` 都会被覆盖。
 *
 * @param {object} [options]
 * @param {string} [options.pluginId] 拥有该 api 门面的插件 id。
 */
export function buildUiPrimitives(options = {}) {
  const ownerId = String(options.pluginId || "");

  /** 绑定了 owner 的图标原语：`api.ui.icon(name, { className })`。 */
  function boundIcon(name, iconOptions = {}) {
    return icon(name, {
      className: iconOptions.className || "",
      pluginId: ownerId || iconOptions.pluginId || "",
    });
  }

  /**
   * 内嵌图标的原语也要带上 owner：`button({icon})` / `empty({icon})` 的取值同样是
   * 「宿主图标名或插件资源路径」两种可能，插件不该自己拼 URL。
   * 这里把 ownerId 注入 `pluginId`，由各工厂转发给 `icon()`。
   */
  const withOwner = (factory) => (spec = {}) => factory({ ...spec, pluginId: ownerId });

  return {
    icon: boundIcon,
    panel,
    section,
    card,
    field,
    form,
    button: withOwner(button),
    toolbar,
    empty: withOwner(empty),
    error,
    loading,
    badge,
    list,
    table,
    grid,
    split,
    // v3 新增：菜单树 / 浮层 / 标签栏 / 布局容器（与贡献树同构）。
    menu: withOwner(menu),
    popover,
    tabs,
    layout,
    confirm,
    prompt,
  };
}

export default buildUiPrimitives;
