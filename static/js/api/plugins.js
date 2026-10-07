/**
 * static/js/api/plugins.js
 * 插件系统管理 API 封装（管理 UI 专用，插件自身调用走后端门面）。
 */

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request(url, options = {}) {
  const response = await fetch(url, options);
  try {
    return await response.json();
  } catch (error) {
    return { success: false, msg: `请求失败 (HTTP ${response.status})` };
  }
}

export function getPluginList() {
  return request("/api/plugins/list");
}

export function getPluginCatalog(refresh = false) {
  return request(`/api/plugins/catalog${refresh ? "?refresh=1" : ""}`);
}

export function installPluginFromCatalog(id, extra = {}) {
  return request("/api/plugins/catalog/install", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ id, ...extra }),
  });
}

export function checkPluginUpdates(force = false) {
  return request("/api/plugins/catalog/check_updates", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ force: Boolean(force) }),
  });
}

export function uploadPluginArchive(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/plugins/install_upload", { method: "POST", body: form });
}

export function uninstallPlugin(id, keepData = false) {
  return request("/api/plugins/uninstall", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ id, keep_data: Boolean(keepData) }),
  });
}

export function enablePlugin(id) {
  return request(`/api/plugins/${encodeURIComponent(id)}/enable`, { method: "POST" });
}

export function disablePlugin(id) {
  return request(`/api/plugins/${encodeURIComponent(id)}/disable`, { method: "POST" });
}

export function getPluginConfig(id) {
  return request(`/api/plugins/${encodeURIComponent(id)}/config`);
}

export function savePluginConfig(id, config) {
  return request(`/api/plugins/${encodeURIComponent(id)}/config`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ config }),
  });
}

export function getPluginSecrets(id) {
  return request(`/api/plugins/${encodeURIComponent(id)}/secrets`);
}

export function savePluginSecrets(id, secrets) {
  return request(`/api/plugins/${encodeURIComponent(id)}/secrets`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ secrets }),
  });
}

export function deletePluginSecret(id, key) {
  return request(
    `/api/plugins/${encodeURIComponent(id)}/secrets/${encodeURIComponent(key)}`,
    { method: "DELETE" },
  );
}
