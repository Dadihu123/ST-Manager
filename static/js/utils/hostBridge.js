/* 宿主外壳桥：把「系统返回」统一成一个入口。
 *
 * 三个来源：
 * - Android：`OnBackInvokedCallback`（Android 13+）或 `onBackPressed` 调用
 *   `window.__stmHostBack()`，返回值 true 表示 WebView 已消费；
 * - iOS：`allowsBackForwardNavigationGestures = true` 后由 WKWebView 触发 popstate，
 *   因此 iOS 无需额外注入，只要 viewStack 压过哨兵项即可；
 * - 桌面浏览器：Alt+← / 鼠标侧键 触发 popstate，行为与 iOS 相同。
 *
 * 非移动端（桌面浏览器）下本模块不会改变任何现有行为：仅额外提供 Alt+← 的便利，
 * 而 Escape 完全不动。
 */

import {
  closeTop,
  describe as describeStack,
  handleBack,
  install as installStack,
} from './viewStack.js';

/** 外壳是否已注入返回钩子（Android 壳会设置 window.__stmHostBridge）。 */
export function hasNativeHost() {
  return !!window.stmHost || (typeof window.__stmHostBridge === 'object' && window.__stmHostBridge !== null);
}

/**
 * 安装返回桥。幂等。
 *
 * @param {{getMode: () => string, getHomeMode?: () => string, setMode: (m: string) => void}} workspace
 */
export function installHostBridge(workspace) {
  // 1) 浏览器/ iOS 侧滑：走 popstate
  installStack({ nativeBack: hasNativeHost() });

  // 2) Android 壳：主动调用该函数询问「要不要自己处理」
  //    返回 true 表示 WebView 已消费这次返回，native 不应再结束 Activity/退出应用。
  window.__stmHostBack = function stmHostBack() {
    return handleBack(workspace);
  };

  // 3) 诊断通道：真机上排查「返回键为什么不生效」时直接读它。
  //    返回 { registered: [{key, active, error}], depth, installed, hasActiveLayer }，
  //    能一眼区分「层没注册」「isActive 恒 false」「DOM 观察没装上」三种情况。
  window.__stmViewStack = function stmViewStack() {
    try {
      return describeStack();
    } catch (err) {
      return { error: String((err && err.message) || err) };
    }
  };

  // 4) 供壳层查询当前是否有可关闭的层（用于决定是否显示返回箭头等）
  window.__stmHostGetStackDepth = function stmHostGetStackDepth() {
    try {
      return typeof window.__stmViewStack === 'function'
        ? window.__stmViewStack().depth
        : 0;
    } catch (err) {
      return 0;
    }
  };

  return function uninstallHostBridge() {
    try {
      delete window.__stmHostBack;
      delete window.__stmHostGetStackDepth;
      delete window.__stmViewStack;
    } catch (err) {
      // 某些环境 delete 失败不影响功能。
    }
  };
}

/** 供组件/诊断使用：主动请求关闭最上层。 */
export function requestCloseTop() {
  return closeTop();
}
