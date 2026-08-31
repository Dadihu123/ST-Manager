async function parseJson(res) {
  try {
    return await res.json();
  } catch (error) {
    const status = Number(res?.status || 0);
    if (status) {
      throw new Error(`请求失败（HTTP ${status}，服务器未返回有效 JSON）`);
    }
    throw new Error("服务器返回的响应不是有效 JSON");
  }
}

export async function listBeautifyPackages() {
  const res = await fetch("/api/beautify/list");
  return parseJson(res);
}

export async function getBeautifyPackage(packageId) {
  const res = await fetch(`/api/beautify/${encodeURIComponent(packageId)}`);
  return parseJson(res);
}

export async function getBeautifySettings() {
  const res = await fetch("/api/beautify/settings");
  return parseJson(res);
}

export async function updateBeautifySettings(payload) {
  const res = await fetch("/api/beautify/update-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(res);
}

export async function importBeautifyTheme(file, options = {}) {
  const formData = new FormData();
  formData.append("file", file);
  if (options.package_id) formData.append("package_id", options.package_id);
  if (options.platform) formData.append("platform", options.platform);

  const res = await fetch("/api/beautify/import-theme", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function importBeautifyVariant(file, packageId, options = {}) {
  if (!packageId) throw new Error("packageId is required");
  return importBeautifyTheme(file, { ...options, package_id: packageId });
}

export async function importBeautifyWallpaper(file, packageId, variantId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("package_id", packageId);
  formData.append("variant_id", variantId);

  const res = await fetch("/api/beautify/import-wallpaper", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function importGlobalBeautifyWallpaper(file) {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/api/beautify/import-global-wallpaper", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function importSharedPreviewWallpaperForBeautify(file) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("selection_target", "preview");

  const res = await fetch("/api/shared-wallpapers/import", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function selectSharedPreviewWallpaperForBeautify(wallpaperId) {
  const res = await fetch("/api/shared-wallpapers/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      wallpaper_id: wallpaperId,
      selection_target: "preview",
    }),
  });
  return parseJson(res);
}

export async function importGlobalBeautifyAvatar(file, target) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("target", target);

  const res = await fetch("/api/beautify/import-global-avatar", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function importBeautifyScreenshot(file, packageId) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("package_id", packageId);

  const res = await fetch("/api/beautify/import-screenshot", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function updateBeautifyPackageIdentities(payload) {
  const res = await fetch("/api/beautify/update-package-identities", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(res);
}

export async function importBeautifyPackageAvatar(file, packageId, target) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("package_id", packageId);
  formData.append("target", target);

  const res = await fetch("/api/beautify/import-package-avatar", {
    method: "POST",
    body: formData,
  });
  return parseJson(res);
}

export async function updateBeautifyVariant(payload) {
  const res = await fetch("/api/beautify/update-variant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson(res);
}

export async function sendBeautifyThemeToSt(payload = {}) {
  const res = await fetch("/api/beautify/send-theme-to-st", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  return parseJson(res);
}

export async function deleteBeautifyPackage(packageId) {
  const res = await fetch("/api/beautify/delete-package", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ package_id: packageId }),
  });
  return parseJson(res);
}

export function buildBeautifyPreviewAssetUrl(relativePath) {
  if (!relativePath) return "";
  const normalized = String(relativePath).replace(
    /^data\/library\/beautify\//,
    "",
  );
  return `/api/beautify/preview-asset/${normalized.split("/").map(encodeURIComponent).join("/")}`;
}
