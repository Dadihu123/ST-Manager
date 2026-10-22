/**
 * docs/plugin-api.d.ts
 * ST-Manager 插件契约 v3 的前端 TypeScript 类型。
 *
 * ⚠️ 本文件由 `python tools/gen_plugin_api_docs.py` 生成，请勿手工编辑。
 * 来源：`core/plugins/contract.py`（枚举 / 容量）+ `static/js/pluginHost.js`
 * 的 `buildApi()`（顶层成员）+ 设计文档 §4–§7。
 *
 * 用法：把本文件放进插件前端项目（或 `/// <reference path="..." />`），
 * `activate(api: PluginApiV3)` 即获得贡献 / 根节点 / 浮层 / 宿主状态补全。
 */

/* ================= 版本与枚举（来自 contract.py） ================= */

/** manifest 结构版本；宿主只支持 3。 */
export type ManifestVersion = 3;

/** 插件 API 契约版本；宿主只支持 3。 */
export type ApiVersion = 3;

/** 前端渲染模式（`frontend.render_mode`，默认 declarative）。 */
export type RenderMode = 'declarative' | 'custom';

/** 宿主工作模式（`HostState.mode`）。 */
export type HostMode = 'beautify' | 'cards' | 'chats' | 'presets' | 'quick_replies' | 'regex' | 'scripts' | 'worldinfo';

/** 菜单落点（`contributions.menus[].placement`，仅根节点）。 */
export type MenuPlacement = 'context.folder' | 'context.card' | 'context.footer' | 'batch.actions' | 'commandPalette' | 'dock' | 'settings.nav';

/** 命名插槽（`contributions.slots[].slot`）。 */
export type SlotName = 'settings.section' | 'header.actions' | 'card.detail.tabs' | 'page.cards.toolbar' | 'page.worldinfo.toolbar';

/** 空状态插槽（`empty.<mode>`）。 */
export type EmptySlotName = `empty.${HostMode}`;

/** 全部插槽名。 */
export type AnySlotName = SlotName | EmptySlotName;

/** 菜单节点类型（隐式 group 已由显式 submenu 取代）。 */
export type MenuNodeType = 'item' | 'submenu' | 'separator';

/** 菜单项 action 类型。 */
export type ActionType = 'surface' | 'command' | 'url';

/** `when.selection` 取值。 */
export type SelectionMode = 'any' | 'multi' | 'none' | 'single';

/** `when.indexState` 取值。 */
export type IndexState = 'idle' | 'running';

/** 浮层层级带（`api.overlays.register()` 的 layer）。 */
export type OverlayLayer = 'content' | 'ambient' | 'surface' | 'dock' | 'popover' | 'tooltip' | 'alert';

/** `api.surfaces.register()` 的 surface 类型。 */
export type SurfaceType = 'panel' | 'modal' | 'page' | 'sheet' | 'ambient';

/** surface 尺寸档位（仅 modal 生效）。 */
export type SurfaceSize = 'sm' | 'md' | 'lg' | 'xl';

/** 设备类型（`HostState.deviceType`）。 */
export type DeviceType = 'desktop' | 'tablet' | 'mobile';

/** 菜单 action 的触发来源（`CommandContext.trigger.kind`）。 */
export type TriggerKind = 'menu' | 'palette' | 'shortcut';

/** 落点上下文里的目标类型（`context.folder` / `context.card`）。 */
export type TargetType = 'folder' | 'card';

/** 已知能力位（未知能力位宿主保留并披露，不拦截）。 */
export type KnownCapability = 'cards.read' | 'cards.write' | 'chats.read' | 'chats.write' | 'cli.run' | 'hooks.subscribe' | 'jobs.run' | 'network.outbound' | 'presets.read' | 'presets.write' | 'secrets.read' | 'tags.read' | 'tags.write' | 'ui.custom' | 'ui.global_styles' | 'worldbook.read' | 'worldbook.write';

/** 能力位：已知值有补全，允许未知扩展值。 */
export type Capability = KnownCapability | (string & {});

/* ================= when / action ================= */

/** 声明式显示条件；全部条件 AND。 */
export interface WhenClause {
  /** 命中任一工作模式即成立。 */
  mode?: HostMode[];
  /** 当前选中集状态。 */
  selection?: SelectionMode;
  /** 这些配置键都存在且非空。 */
  config?: { requireKeys?: string[] };
  /** 主程序版本门槛（普通语义化版本）。 */
  hostVersion?: string;
  /** 宿主 feature flag 全部开启。 */
  feature?: string[];
  /** 索引作业状态。 */
  indexState?: IndexState;
}

/** 打开插件注册的 surface。 */
export interface SurfaceAction {
  type: 'surface';
  /** 运行期 `api.surfaces.register(surfaceId, spec)` 的 id。 */
  id: string;
}

/** 触发 commands[] 里的命令（安装期校验存在性）。 */
export interface CommandAction {
  type: 'command';
  id: string;
}

/** 浏览器新标签页打开 http(s) 链接。 */
export interface UrlAction {
  type: 'url';
  url: string;
}

export type MenuAction = SurfaceAction | CommandAction | UrlAction;

/* ================= 菜单树 ================= */

/** 菜单节点公共字段（根节点另需 placement）。 */
export interface MenuNodeBase {
  /** 节点 id，插件内唯一。 */
  id: string;
  type: MenuNodeType;
  label?: string;
  description?: string;
  /** 宿主图标名（如 wand）或插件内相对资源路径。 */
  icon?: string;
  /** 升序建议值，默认 100。 */
  order?: number;
  when?: WhenClause;
  /** 静态徽标；动态值用 api.contributions.update()。 */
  badge?: string | number;
  disabledHint?: string;
}

export interface MenuItem extends MenuNodeBase {
  type: 'item';
  action: MenuAction;
}

export interface MenuSubmenu extends MenuNodeBase {
  type: 'submenu';
  children: MenuNode[];
}

export interface MenuSeparator extends MenuNodeBase {
  type: 'separator';
}

export type MenuNode = MenuItem | MenuSubmenu | MenuSeparator;

/** 根节点：placement 必填；子节点不带 placement。整棵树最多 3 层。 */
export type MenuRootNode =
  | (MenuItem & { placement: MenuPlacement })
  | (MenuSubmenu & { placement: MenuPlacement })
  | (MenuSeparator & { placement: MenuPlacement });

/* ================= 插槽 / 命令 / contributions ================= */

/** 插槽渲染器：module 导出 export(container, ctx)，可返回清理函数。 */
export type SlotRenderer = (
  container: HTMLElement,
  ctx: SlotContext,
) => void | (() => void);

export interface SlotContribution {
  id: string;
  /** 命名插槽或 `empty.<mode>` 空状态插槽。 */
  slot: AnySlotName;
  title?: string;
  order?: number;
  when?: WhenClause;
  /** 渲染器模块路径（相对插件根目录）。 */
  module: string;
  export: string;
}

/** 命令处理器：module 导出 export(ctx)。 */
export type CommandHandler = (ctx: CommandContext) => void | Promise<void>;

export interface CommandContribution {
  id: string;
  title: string;
  description?: string;
  icon?: string;
  /** 形如 Ctrl+Shift+D；必须含 Ctrl/Alt/Meta 之一。 */
  shortcut?: string;
  when?: WhenClause;
  module: string;
  export: string;
}

/** `frontend.contributions`：宿主 UI 的三种静态声明原语。 */
export interface Contributions {
  menus?: MenuRootNode[];
  slots?: SlotContribution[];
  commands?: CommandContribution[];
}

/* ================= manifest（前端可见子集） ================= */

export interface BackendDeclaration {
  entry?: string;
  register?: string;
  jobs?: string[];
  hooks?: string[];
}

export interface FrontendDeclaration {
  entry?: string;
  styles?: string[];
  /** 需要 ui.global_styles 能力位。 */
  global_styles?: string[];
  render_mode?: RenderMode;
  contributions?: Contributions;
}

/** `/api/plugins/list` 里 item.manifest 的前端可见形状（v3）。 */
export interface PluginManifestV3 {
  manifest_version: ManifestVersion;
  api_version: ApiVersion;
  id: string;
  name: string;
  version: string;
  author?: string;
  description?: string;
  homepage?: string;
  license?: string;
  icon?: string;
  min_app_version?: string;
  backend?: BackendDeclaration;
  frontend?: FrontendDeclaration;
  capabilities?: Capability[];
  contributions?: Contributions;
  requires?: Record<string, string>;
  config_schema?: Record<string, unknown>;
  secret_schema?: Record<string, unknown>;
  i18n?: Record<string, unknown>;
}

/* ================= 根节点 createRoot ================= */

/** `api.createRoot()` 选项；不传等价于 `{ tag: 'div' }`。 */
export interface CreateRootOptions {
  /** 根节点标签名，默认 `div`。 */
  tag?: string;
  /** true = 挂 portal 层（body 级，自绘/浮层用）；默认内容层。 */
  portal?: boolean;
}

/** 创建插件根节点：`createRoot()` / `createRoot('section')` / `createRoot({ portal: true })`。
 *
 * 宿主创建并跟踪节点，插件只能往里挂内容；销毁时宿主强制回收。
 */
export interface PluginRootApi {
  (): HTMLElement;
  (tag: string): HTMLElement;
  (options: CreateRootOptions): HTMLElement;
}

/* ================= overlays（可选登记） ================= */

/** `api.overlays.register(spec)`：把自绘浮层登记给宿主协调（ESC/焦点/遮挡）。 */
export interface OverlaySpec {
  id: string;
  /** 浮层根元素（插件自绘，宿主只负责协调）。 */
  element: Element;
  /** 层级带，默认 surface。 */
  layer?: OverlayLayer;
  /** 是否参与 ESC / 焦点陷阱（默认 false）。 */
  modal?: boolean;
  /** 无障碍标签（aria-label）。 */
  label?: string;
  /** 宿主强制关闭（ESC / kill switch）时回调；插件应在此清理。 */
  onDismiss?: () => void;
}

/** `api.overlays.list()` 的元数据（不含 DOM 元素）。 */
export interface OverlayInfo {
  id: string;
  layer: OverlayLayer;
  modal: boolean;
  label: string;
}

export interface OverlaysApi {
  /** 登记浮层，返回注销函数。 */
  register(spec: OverlaySpec): () => void;
  unregister(id: string): boolean;
  list(): OverlayInfo[];
  /** 关闭全部已登记浮层（kill switch 用）。 */
  closeAll(): number;
}

/* ================= 运行期贡献树 API ================= */

/** `api.contributions.update()` 的字段白名单；结构（id/type/children）不可改。 */
export interface ContributionUpdatePatch {
  label?: string;
  description?: string;
  icon?: string;
  badge?: string | number | null;
  progress?: number | null;
  status?: string;
  enabled?: boolean;
  disabledHint?: string;
  busy?: boolean;
}

/** 运行期贡献节点快照（`api.contributions.get/list`）。 */
export interface ContributionNodeSnapshot {
  id: string;
  key: string;
  pluginId: string;
  kind: 'menu' | 'slot' | 'command';
  placement?: MenuPlacement;
  type?: MenuNodeType;
  label: string;
  description: string;
  icon: string;
  order: number;
  badge: string | number | null;
  disabledHint: string;
  action: MenuAction | null;
  when: WhenClause;
  children: ContributionNodeSnapshot[];
  status: string;
  busy: boolean;
  progress: number | null;
  enabled: boolean;
}

export interface ContributionsApi {
  /** 更新运行期字段（结构不可变）；返回是否命中。 */
  update(id: string, patch: ContributionUpdatePatch): boolean;
  remove(id: string): boolean;
  get(id: string): ContributionNodeSnapshot | null;
  list(): ContributionNodeSnapshot[];
  /** 以编程方式触发（等价用户点击）；ctx 缺省用当前上下文。 */
  trigger(id: string, ctx?: unknown): boolean;
}

/* ================= 落点上下文 / 渲染器 ================= */

/** 落点目标（右键/批量/命令面板传入的上下文对象）。 */
export interface ContributionTarget {
  type: TargetType;
  id: string;
  name?: string;
}

/** 宿主当前选中集（`api.host.selection()`）。 */
export interface HostSelection {
  mode: HostMode | '';
  ids: string[];
}

export interface SlotContext {
  api: PluginApiV3;
  pluginId: string;
  slot: AnySlotName;
  mode: HostMode;
  target: ContributionTarget | null;
  selection: HostSelection;
}

/** 命令触发上下文。 */
export interface CommandContext {
  api: PluginApiV3;
  pluginId: string;
  mode: HostMode;
  target: ContributionTarget | null;
  selection: HostSelection;
  trigger: {
    kind: TriggerKind;
    /** menu 触发时对应菜单节点 id。 */
    nodeId?: string;
  };
}

/* ================= host state / surfaces ================= */

/** `api.host.onState()` 的状态快照（只给界面字段，不含选中集）。 */
export interface HostState {
  mode: HostMode;
  deviceType: DeviceType;
  darkMode: boolean;
  /** 宿主全屏遮罩是否活跃（modal 打开等）。 */
  scrimActive: boolean;
  /** 是否有插件 surface 处于打开态。 */
  surfaceOpen: boolean;
  busy: boolean;
  reducedMotion: boolean;
  visible: boolean;
}

/** surface 打开上下文（`mount(container, ctx)` / `onOpen(ctx)`）。 */
export interface SurfaceOpenContext {
  pluginId: string;
  surfaceId: string;
  mode: HostMode;
  selection: HostSelection;
  /** 触发来源：菜单 action / 命令 / ambient 常驻层。 */
  source: 'menu' | 'command' | 'ambient';
}

/** `api.surfaces.register(surfaceId, spec)`。 */
export interface SurfaceSpec {
  type?: SurfaceType;
  size?: SurfaceSize;
  title?: string;
  description?: string;
  icon?: string;
  /** 唯一必需成员：把内容挂到宿主提供的容器里。 */
  mount(container: HTMLElement, ctx: SurfaceOpenContext): void | (() => void);
  unmount?(): void;
  onOpen?(ctx: SurfaceOpenContext): void;
  onClose?(): void;
}

export interface SurfacesApi {
  /** 注册 surface，返回全局 key（失败返回空串）。 */
  register(surfaceId: string, spec: SurfaceSpec): string;
  open(surfaceId: string, ctx?: Record<string, unknown>): boolean;
  close(surfaceId: string): boolean;
  isOpen(surfaceId: string): boolean;
}

/* ================= UI 原语 / 存储 / 作业 / 工具 ================= */

/** `api.ui`：宿主 UI 原语；参数形状见 docs/plugin-api.md。 */
export interface UiPrimitives {
  icon(name: string, options?: Record<string, unknown>): HTMLElement;
  button(options?: Record<string, unknown>): HTMLElement;
  badge(options?: Record<string, unknown>): HTMLElement;
  card(options?: Record<string, unknown>): HTMLElement;
  panel(options?: Record<string, unknown>): HTMLElement;
  section(options?: Record<string, unknown>): HTMLElement;
  field(options?: Record<string, unknown>): HTMLElement;
  form(options?: Record<string, unknown>): HTMLElement;
  toolbar(options?: Record<string, unknown>): HTMLElement;
  empty(options?: Record<string, unknown>): HTMLElement;
  error(options?: Record<string, unknown>): HTMLElement;
  loading(options?: Record<string, unknown>): HTMLElement;
  list(options?: Record<string, unknown>): HTMLElement;
  table(options?: Record<string, unknown>): HTMLElement;
  grid(options?: Record<string, unknown>): HTMLElement;
  split(options?: Record<string, unknown>): HTMLElement;
  confirm(options?: Record<string, unknown>): Promise<boolean>;
  prompt(options?: Record<string, unknown>): Promise<string | null>;
}

/** `api.progress.*`：复用主程序批处理进度条。 */
export interface PluginProgressApi {
  start(title: string, total: number): void;
  update(patch: Record<string, unknown>): void;
  cancelRequested(): boolean;
  finish(result?: Record<string, unknown>): void;
  dismiss(): void;
}

/** `api.storage.*`：插件键值存储（写入会落库）。 */
export interface PluginStorageApi {
  get(key: string): unknown;
  set(key: string, value: unknown): boolean | Promise<boolean>;
  remove(key: string): boolean | Promise<boolean>;
  keys(): string[];
}

/** `api.api(path, options)` 的请求选项（自动补前缀与 CSRF）。 */
export interface PluginFetchOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  [option: string]: unknown;
}

export interface WorldbookSource {
  source_type: string;
  file_path: string;
  card_id: string;
  category: string;
  name: string;
  entry_count: number;
}

export interface WorldbookSourcesOptions {
  category?: string;
  sourceType?: string;
  /** `true` = 走分页拉全量，返回 Promise。 */
  all?: boolean;
  pageSize?: number;
}

export interface WorldbookSourcesResult {
  items: WorldbookSource[];
  total: number;
  /** `true` 表示还有没取到的（插件必须告知用户）。 */
  truncated: boolean;
}

/** `api.worldbook.*`（**前端**同名命名空间；与后端 `api.worldbook` 不是同一对象）。 */
export interface PluginWorldbookApi {
  sources(options?: WorldbookSourcesOptions):
    WorldbookSource[] | Promise<WorldbookSourcesResult>;
}

/** 作业快照（字段由后端 JSON 决定，前端只透传）。 */
export interface PluginJob { [field: string]: unknown; }

/** `api.subscribeJob(runId, handlers)` 的回调表。 */
export interface JobSubscriptionHandlers {
  snapshot?(job: PluginJob): void;
  item?(item: unknown): void;
  log?(entry: unknown): void;
  done?(job: PluginJob): void;
  error?(error: unknown): void;
}

/** `api.jobs.*`：作业提交、生命周期与逐条审批。 */
export interface PluginJobsApi {
  get(runId: string): Promise<PluginJob | null>;
  list(options?: { limit?: number; offset?: number }): Promise<PluginJob[]>;
  submit(jobType: string, items: unknown[], payload?: Record<string, unknown>):
    Promise<string>;
  cancel(runId: string): Promise<boolean>;
  pause(runId: string): Promise<boolean>;
  resume(runId: string): Promise<boolean>;
  retry(runId: string, onlyFailed?: boolean): Promise<string>;
  review(runId: string, itemKey: string, status: string): Promise<boolean>;
  reviewBatch(
    runId: string,
    updates: Array<{ key: string; status: string }>,
  ): Promise<{ total: number; failed: number }>;
  open(runId: string, options?: { title?: string }): void;
}

/** `api.utils.*`：宿主工具（图标路径、SSE 解析、日期格式化）。 */
export interface PluginUtilsApi {
  toAbsoluteAssetUrl(relativePath: string): string;
  parseSSEFrames(buffer: string): unknown[];
  parseSSEPayload(frame: unknown): unknown;
  resolveIconUrl(name: string, options?: Record<string, unknown>): string;
  formatDate(value: number | string): string;
}

/** `api.host.*`：宿主内建能力（D8）。 */
export interface PluginHostApi {
  toast(message: string, duration?: number, icon?: string): void;
  refresh(target?: string): boolean;
  switchMode(mode: string): boolean;
  openDetail(target?: string, id?: string): boolean;
  openSettingsSection(section: string, anchor?: string): boolean;
  notify(message: string, level?: 'info' | 'warning' | 'error'): void;
  log(message: string, level?: 'info' | 'warning' | 'error'): void;
  onState(handler: (state: HostState) => void): () => void;
  /** `{mode, ids}`：读取当前选中集的**契约入口**。 */
  selection(): HostSelection;
}

/* ================= 插件前端 API ================= */

/** `activate(api)` 收到的前端 API（与 buildApi() 顶层键一一对应）。 */
export interface PluginApiV3 {
  readonly id: string;
  readonly manifest: PluginManifestV3;
  /** 插件私有状态对象（随启用/停用生命周期）。 */
  readonly state: Record<string, unknown>;
  /** 主程序 Alpine `global` store（Provisional 耦合；优先用 api.host）。 */
  readonly store: Record<string, unknown>;

  /** 调用插件后端：自动前缀 `/api/plugins/<id>`、CSRF，按 data.success 判定成败。 */
  api(path: string, options?: PluginFetchOptions): Promise<any>;
  /** 订阅事件：核心事件走 SSE，自定义事件走 window（强制 `<id>:` 前缀）。 */
  on(event: string, handler: (payload: any) => void): () => void;
  off(event: string, handler: (payload: any) => void): void;
  /** 派发自定义事件；核心事件只允许宿主发出（插件 emit 会被警告并忽略）。 */
  emit(event: string, detail?: unknown): void;
  onConfigChange(handler: (config: Record<string, unknown>) => void): () => void;
  toast(message: string, duration?: number, icon?: string): void;
  progress: PluginProgressApi;
  contributions: ContributionsApi;
  overlays: OverlaysApi;
  createRoot: PluginRootApi;
  surfaces: SurfacesApi;
  ui: UiPrimitives;
  storage: PluginStorageApi;
  worldbook: PluginWorldbookApi;
  jobs: PluginJobsApi;
  utils: PluginUtilsApi;
  estimateTokens(text: string): number;
  openDetail(
    target?: 'card' | 'preset' | 'chat' | 'worldinfo',
    id?: string,
  ): boolean;
  refresh(
    target?: 'cards' | 'worldinfo' | 'chats' | 'presets' | 'beautify',
  ): boolean;
  switchMode(mode: HostMode): boolean;
  openSettingsSection(section: string, anchor?: string): boolean;
  registerAlpineComponent(name: string, factory: (...args: any[]) => unknown): void;
  subscribeJob(runId: string, handlers?: JobSubscriptionHandlers): () => void;
  /** 全屏遮罩记账：宿主据此关闭页面壳 backdrop-filter（避免黑块）。 */
  setFullscreenScrim(open: boolean, owner?: string): boolean;
  host: PluginHostApi;
}
