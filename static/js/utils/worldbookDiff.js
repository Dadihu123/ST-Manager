// Load the licensed CodeMirror bundle only when a worldbook comparison is opened.
let runtime;
export async function loadWorldbookDiff() {
  runtime ||= import("../../lib/codemirror-worldbook-diff.js");
  try { await runtime; }
  catch (error) { runtime = null; throw error; }
  return mountWorldbookDiff;
}

export function readableWorldbook(text) {
  const book = JSON.parse(text);
  const entries = Object.entries(book.entries || {});
  return entries.map(([id, entry]) => {
    const keys = Array.isArray(entry.key) ? entry.key : entry.keys || [];
    return [
      `条目 ${id} · ${entry.comment || entry.name || "未命名"}`,
      `关键词：${Array.isArray(keys) ? keys.join("、") : keys}`,
      `状态：${entry.disable === true || entry.enabled === false ? "关闭" : "开启"} · ${entry.constant ? "持续触发" : "关键词触发"}`,
      String(entry.content || ""),
      "",
    ].join("\n");
  }).join("\n");
}

function mountWorldbookDiff(container, current, incoming) {
  const V = window.worldbookDiffVendor;
  container.replaceChildren();
  const toolbar = document.createElement("div");
  toolbar.className = "wb-diff-toolbar";
  const counter = document.createElement("span");
  counter.setAttribute("role", "status");
  let index = -1;
  const button = (label, click) => {
    const node = document.createElement("button");
    node.type = "button";
    node.textContent = label;
    node.className = "btn-secondary";
    node.addEventListener("click", click);
    toolbar.append(node);
    return node;
  };
  const previous = button("↑ 上一处", () => navigate(-1));
  const next = button("↓ 下一处", () => navigate(1));
  toolbar.append(counter);
  let expanded = false;
  const expand = button("展开未改动", () => {
    expanded = !expanded;
    merge.reconfigure({ collapseUnchanged: expanded ? undefined : { margin: 2, minSize: 6 } });
    expand.textContent = expanded ? "折叠未改动" : "展开未改动";
  });
  button("查找", () => V.openSearchPanel(merge.b));
  container.append(toolbar);
  const labels = document.createElement("div");
  labels.className = "wb-diff-labels";
  for (const label of ["当前内容 · 只读", "导入内容 · 只读"]) {
    const node = document.createElement("strong");
    node.textContent = label;
    labels.append(node);
  }
  container.append(labels);
  const host = document.createElement("div");
  host.className = "wb-diff-host";
  container.append(host);
  const theme = V.EditorView.theme({
    "&": { fontSize: "13px", color: "var(--content-primary)", backgroundColor: "var(--surface-container)" },
    ".cm-gutters": { backgroundColor: "var(--surface-container-raised)", color: "var(--content-muted)", borderRight: "1px solid var(--border-default)" },
    ".cm-content": { padding: "8px 0" },
    ".cm-line": { padding: "0 8px", lineHeight: "1.7" },
    ".cm-panels": { backgroundColor: "var(--surface-container-raised)", color: "inherit" },
    ".cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground": { backgroundColor: "#60a5fa66" },
  });
  const extensions = (label) => [
    theme, V.EditorView.lineWrapping, V.lineNumbers(), V.drawSelection(),
    V.EditorState.readOnly.of(true), V.EditorView.editable.of(false),
    V.EditorView.contentAttributes.of({ "aria-label": label }),
    V.search({ top: true }), V.keymap.of([...V.searchKeymap, ...V.defaultKeymap]),
    V.EditorState.phrases.of({ "Find": "查找", "next": "下一处", "previous": "上一处", "close": "关闭", "$ unchanged lines": "$ 行未改动" }),
    // Keep navigation inside the merge scroller rather than moving the modal footer.
    V.EditorView.scrollHandler.of((view, range) => {
      const scroller = view.dom.closest(".cm-mergeView");
      const rect = view.coordsAtPos(range.head);
      if (scroller && rect) {
        const bounds = scroller.getBoundingClientRect();
        scroller.scrollTop += (rect.top + rect.bottom - bounds.top - bounds.bottom) / 2;
      }
      return true;
    }),
  ];
  const merge = new V.MergeView({
    parent: host,
    a: { doc: current, extensions: extensions("当前世界书，只读") },
    b: { doc: incoming, extensions: extensions("导入世界书，只读") },
    highlightChanges: true, gutter: true,
    collapseUnchanged: { margin: 2, minSize: 6 },
    diffConfig: { scanLimit: 10000, timeout: 150 },
  });
  function updateCounter() {
    const count = merge.chunks.length;
    counter.textContent = count ? `${index < 0 ? "" : `${index + 1} / `}${count} 处差异` : "没有差异";
    previous.disabled = next.disabled = !count;
    counter.title = merge.chunks.some((chunk) => !chunk.precise) ? "较大差异按整段显示；正文完整保留" : "";
  }
  function navigate(direction) {
    if (!merge.chunks.length) return;
    index = index < 0 ? (direction > 0 ? 0 : merge.chunks.length - 1) : (index + direction + merge.chunks.length) % merge.chunks.length;
    const chunk = merge.chunks[index];
    merge.a.dispatch({ selection: { anchor: Math.min(chunk.fromA, merge.a.state.doc.length) } });
    merge.b.dispatch({ selection: { anchor: Math.min(chunk.fromB, merge.b.state.doc.length) }, effects: V.EditorView.scrollIntoView(Math.min(chunk.fromB, merge.b.state.doc.length), { y: "center" }) });
    updateCounter();
  }
  updateCounter();
  return { destroy() { merge.destroy(); container.replaceChildren(); } };
}
