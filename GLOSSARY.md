# ST-Manager

ST-Manager 是本地单用户的 SillyTavern 资源管理器，围绕角色卡、世界书、聊天、预设等资源提供浏览、编辑与批处理；插件系统允许第三方扩展它的界面、能力与自动化流程。

## Language

### 插件系统

**宿主**:
运行主程序本体的本地应用，负责数据、界面骨架、插件生命周期与资源边界。
_Avoid_: 主程序（插件契约语境下）, server, backend

**插件**:
通过 manifest 声明、由宿主加载的扩展单元，可以贡献界面、作业、路由与事件。
_Avoid_: extension, addon, 模块

**插件容器**:
由插件自行创建、定位与管理的界面容器（含浮层）；位置、尺寸、层级由插件负责。
_Avoid_: 自绘容器, floating window

**宿主容器**:
由宿主按 surface 契约创建并管理的容器（定位、尺寸、层级、焦点、卸载均由宿主负责），插件只在其中渲染内容。
_Avoid_: surface container（技术标识可保留）

**贡献通道**:
插件以数据声明界面结构（菜单、插槽、命令、状态项），由宿主统一渲染与定位的扩展方式。
_Avoid_: 声明式 UI, entries

**自绘模式**:
插件不经过宿主渲染、自行创建 DOM 与浮层的扩展方式。
_Avoid_: 自由渲染, custom UI

**插件根节点**:
宿主分配给插件的 DOM 挂载点；插件自绘的界面必须挂在其中，禁用、卸载或崩溃时由宿主整体移除。
_Avoid_: plugin-host-root（技术标识可保留）

**插槽渲染器**:
插件在宿主 UI 的命名插槽内自行渲染内容的扩展方式；容器边界、层级与回收由宿主保证。
_Avoid_: slot UI, custom slot

**推荐通道**:
宿主提供并优先引导插件使用的界面扩展方式（贡献通道与宿主容器）；相对自绘模式而言，选择推荐通道是可选而非强制。
_Avoid_: preferred API

**全局样式权限**:
允许插件向宿主全局注入 CSS 的显式权限，安装与启用时向用户披露。
_Avoid_: theme permission

**共存契约**:
宿主对多个插件自绘 UI 的最低协调规则：层级带、可选 overlay 登记、崩溃隔离与止损开关。
_Avoid_: overlay policy

**菜单树**:
插件以数据声明的菜单结构（项/子菜单/分组/分隔），由宿主渲染到命名落点。
_Avoid_: entries

**落点**:
宿主 UI 中允许挂载菜单树的命名位置（如 `context.folder`、`commandPalette`）。
_Avoid_: placement（技术标识可保留）

**插槽**:
宿主 UI 中提供给插件渲染器的命名嵌入点，容器边界由宿主保证。
_Avoid_: slot（技术标识可保留）

**命令**:
插件注册的具名动作，可被菜单项、命令面板或快捷键调用。
_Avoid_: action

**能力位**:
manifest 中声明、安装时向用户展示的能力标记（如 `ui.custom`、`cards.read`）；只作披露，不构成强制隔离。
_Avoid_: permission

**渲染模式**:
插件声明的界面扩展方式：`declarative`（使用推荐通道）或 `custom`（自绘，需把 DOM 挂在宿主分配的根节点下）。
_Avoid_: render type
