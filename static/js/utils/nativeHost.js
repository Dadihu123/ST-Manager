// Android 消息通道仅用于顶层应用；业务 iframe 不安装宿主 facade。
export function installNativeHost() {
  if (window.top !== window || typeof window.stmNative?.postMessage !== 'function') return false;
  const send = (action, payload = {}) => window.stmNative.postMessage(JSON.stringify({action, ...payload}));
  window.stmHost = Object.freeze({
    platform: () => 'android',
    requestStorageAccess: (id, pathsJson) => send('storage', {id, pathsJson}),
    saveBase64FileAsync: (id, base64, fileName, mimeType) =>
      send('download', {id, base64, fileName, mimeType}),
    openFolder: path => send('openFolder', {path}),
  });
  return true;
}
