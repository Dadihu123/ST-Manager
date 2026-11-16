// Android 消息通道仅用于顶层应用；业务 iframe 不安装宿主 facade。
//
// 这里只暴露壳层**真正实现得了**的能力。注意没有 `openFolder`：
// 应用私有目录（/data/user/0/...）不能交给外部文件管理器直接浏览。
// 系统目录按钮按能力隐藏；应用内浏览、导入与导出复用现有文件接口。
export function installNativeHost() {
  if (window.top !== window || typeof window.stmNative?.postMessage !== 'function') return false;
  const send = (action, payload = {}) => window.stmNative.postMessage(JSON.stringify({action, ...payload}));
  window.stmHost = Object.freeze({
    platform: () => 'android',
    backupDocument: (job, kind) => send('backup-document', {job, kind}),
    requestStorageAccess: (id, pathsJson) => send('storage', {id, pathsJson}),
    saveBase64FileAsync: (id, base64, fileName, mimeType) =>
      send('download', {id, base64, fileName, mimeType}),
  });
  return true;
}
