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

import { resolveIconUrl } from "./utils/icons.js";

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
 * 返回 `<svg><use href="/static/icons/<sprite>.svg#icon-<name>"></use></svg>`，
 * 名字 → sprite 的映射由宿主维护（与 `templates/components/icon.html` 的宏一致）。
 * 未知名字返回占位元素而不是抛错——图标不该拖垮整个界面。
 */
export function icon(name, options = {}) {
  const requested = String(name || "").trim();
  const className = ["ui-icon", options.className || ""].filter(Boolean).join(" ");

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  const href = resolveIconUrl(requested);
  if (!href) {
    svg.dataset.iconMissing = requested || "unknown";
    svg.classList.add("is-missing");
    return svg;
  }

  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", href);
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

  if (options.icon) node.appendChild(icon(options.icon, { className: "ui-icon--sm" }));
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
  if (options.icon) node.appendChild(icon(options.icon, { className: "ui-primitive-empty__icon" }));
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

    const onKeydown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        document.removeEventListener("keydown", onKeydown, true);
        finish(false);
      }
    };
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
        finish(null);
      }
    }
    document.addEventListener("keydown", onKeydown, true);
  });
}

/** 供 `api.ui.*` 一次性挂载。 */
export function buildUiPrimitives() {
  return {
    icon,
    panel,
    section,
    card,
    field,
    form,
    button,
    toolbar,
    empty,
    error,
    loading,
    badge,
    list,
    table,
    grid,
    split,
    confirm,
    prompt,
  };
}

export default buildUiPrimitives;
