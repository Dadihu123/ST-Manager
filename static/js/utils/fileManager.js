/** 系统目录操作只适用于本机桌面客户端；与响应式布局宽度无关。 */
export function canUseSystemFileManager({
  serverSupports = globalThis.document?.querySelector('meta[name="can-open-system-file-manager"]')?.content === 'true',
  hostname = globalThis.window?.location?.hostname || '',
  userAgent = globalThis.navigator?.userAgent || '',
  maxTouchPoints = globalThis.navigator?.maxTouchPoints || 0,
  nativePlatform = globalThis.window?.stmHost?.platform?.() || '',
} = {}) {
  if (!serverSupports) return false;
  if (/android|ios/i.test(nativePlatform)) return false;
  if (/Android|iPhone|iPad|iPod|Mobile/i.test(userAgent)) return false;
  // iPadOS 的桌面 UA 仍然声明 Macintosh。
  if (/Macintosh/i.test(userAgent) && maxTouchPoints > 1) return false;
  const host = hostname.toLowerCase();
  return host === 'localhost' || host === '[::1]' || host === '::1' ||
    /^127(?:\.\d{1,3}){3}$/.test(host);
}
